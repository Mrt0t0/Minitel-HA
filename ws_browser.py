import asyncio
import json
import aiohttp
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from aiohttp import web

import pagevideo as P
import ha_client as HA
from utils import log

LETTER_MODES = {
    'd': 'domotique', 'm': 'meteo', 's': 'scenes', 'j': 'journal',
    'a': 'assistant', 'h': 'aide', 'r': 'archives',
}

DEVICES = SENSORS = SCENES = SCRIPTS = ()
METEO_CFG = ASSIST_CFG = ARCHIVES_CFG = {}
AGENTS = []
ARCHIVES_FOLDER = Path('static/archives')


def configure(cfg):
    global DEVICES, SENSORS, SCENES, SCRIPTS
    global METEO_CFG, ASSIST_CFG, ARCHIVES_CFG, AGENTS, ARCHIVES_FOLDER
    DEVICES      = cfg['devices']
    SENSORS      = cfg['sensors']
    SCENES       = cfg['scenes']
    SCRIPTS      = cfg['scripts']
    METEO_CFG    = cfg.get('meteo') or {}
    ASSIST_CFG   = cfg.get('assistant') or {}
    AGENTS       = ASSIST_CFG.get('agents') or [
        {'id': 'conversation.home_assistant', 'name': 'Assistant HA'}]
    ARCHIVES_CFG = cfg.get('archives') or {}
    ARCHIVES_FOLDER = (Path(cfg.get('_base', '.'))
                       / ARCHIVES_CFG.get('folder', 'static/archives'))


def _list_vdt():
    try:
        ARCHIVES_FOLDER.mkdir(parents=True, exist_ok=True)
        return sorted(({'name': f.stem, 'size': f.stat().st_size}
                       for f in ARCHIVES_FOLDER.glob('*.vdt')),
                      key=lambda x: x['name'])
    except Exception as e:
        log('ERR', f'list_vdt: {e}')
        return []


async def browser_ws_handler(request):
    ws = web.WebSocketResponse(heartbeat=30)
    await ws.prepare(request)
    remote = request.remote
    log('BR', f'+ {remote}')

    st = {
        'mode': 'menu', 'page': 0, 'jp': 0,
        'assist_history': [], 'assist_agent_idx': 0, 'assist_conv_id': None,
        'aide_general': True, 'aide_page': 0,
    }

    try:
        async with aiohttp.ClientSession() as session:

            async def push(flash=''):
                ts   = datetime.now().isoformat()
                mode = st['mode']
                if mode in ('domotique', 'menu'):
                    devs, sens, stats = await HA.fetch_data(session, DEVICES, SENSORS)
                    if mode == 'menu':
                        payload = {'type': 'menu', 'mode': 'menu',
                                   'stats': stats, 'ts': ts}
                    else:
                        areas = defaultdict(list)
                        for dv in devs:
                            areas[dv['area']].append(dv)
                        payload = {
                            'type': 'update', 'mode': 'domotique',
                            'devices': devs, 'sensors': sens,
                            'areas': dict(areas), 'stats': stats,
                            'page': st['page'], 'page_size': P.PAGE_SIZE,
                            'title': P.CFG['title'], 'flash': flash, 'ts': ts,
                        }
                elif mode == 'meteo':
                    m = await HA.fetch_meteo(session, METEO_CFG)
                    payload = {'type': 'meteo', 'mode': 'meteo',
                               'ext': m['ext'], 'rooms': m['rooms'],
                               'forecast': m.get('forecast', []), 'ts': ts}
                elif mode == 'scenes':
                    payload = {'type': 'scenes', 'mode': 'scenes',
                               'scenes': SCENES, 'scripts': SCRIPTS,
                               'flash': flash, 'ts': ts}
                elif mode == 'journal':
                    payload = {'type': 'journal', 'mode': 'journal',
                               'journal': list(HA.JOURNAL), 'page': st['jp'], 'ts': ts}
                elif mode == 'assistant':
                    idx = st['assist_agent_idx']
                    payload = {
                        'type': 'assistant', 'mode': 'assistant',
                        'history': st['assist_history'], 'agents': AGENTS,
                        'agent_idx': idx,
                        'agent_name': AGENTS[idx]['name'] if AGENTS else '',
                        'conv_id': st['assist_conv_id'], 'flash': flash, 'ts': ts,
                    }
                elif mode == 'archives':
                    files = _list_vdt()
                    payload = {'type': 'archives', 'mode': 'archives',
                               'files': files, 'total': len(files),
                               'auto_rotate': int(ARCHIVES_CFG.get('auto_rotate', 30) or 0),
                               'flash': flash, 'ts': ts}
                elif mode == 'aide':
                    payload = {'type': 'aide', 'mode': 'aide',
                               'aide_general': st['aide_general'],
                               'aide_page': st['aide_page'],
                               'total_pages': len(P._AIDE_GENERAL_PAGES), 'ts': ts}
                else:
                    return
                await ws.send_str(json.dumps(payload))

            await push()

            async for msg in ws:
                if msg.type != aiohttp.WSMsgType.TEXT:
                    break
                cmd     = msg.data.strip()
                mode    = st['mode']
                total_p = max(1, -(-len(DEVICES) // P.PAGE_SIZE))
                flash   = ''
                log('BR', f'[{remote}][{mode}] {cmd[:40]}')

                if cmd == 'SOMMAIRE':
                    st['mode'] = 'menu'
                elif cmd == 'ANNULATION':
                    if mode != 'assistant':
                        st['mode'], st['page'] = 'domotique', 0
                elif cmd in ('DOMOTIQUE', 'D'):
                    st['mode'], st['page'] = 'domotique', 0
                elif cmd in ('METEO', 'SCENES', 'JOURNAL', 'ASSISTANT', 'ARCHIVES'):
                    st['mode'] = cmd.lower()
                elif cmd == 'AIDE':
                    st.update(mode='aide', aide_general=True, aide_page=0)
                elif cmd in ('GUIDE', 'AIDE_CONTEXTUEL'):
                    st.update(mode='aide', aide_general=False, aide_page=0)
                elif cmd == 'REFRESH':
                    HA.invalidate_cache()
                elif cmd == 'SUITE':
                    if mode == 'domotique':
                        st['page'] = (st['page'] + 1) % total_p
                    elif mode == 'journal':
                        tj = max(1, -(-len(HA.JOURNAL) // 17))
                        st['jp'] = (st['jp'] + 1) % tj
                    elif mode == 'assistant' and len(AGENTS) > 1:
                        i = (st['assist_agent_idx'] + 1) % len(AGENTS)
                        st.update(assist_agent_idx=i, assist_conv_id=None,
                                  assist_history=[])
                        flash = f'Agent: {AGENTS[i]["name"]}'
                    elif mode == 'aide' and st['aide_general']:
                        st['aide_page'] = (st['aide_page'] + 1) % len(P._AIDE_GENERAL_PAGES)
                elif cmd == 'RETOUR':
                    if mode == 'domotique':
                        st['page'] = (st['page'] - 1) % total_p
                    elif mode == 'journal':
                        tj = max(1, -(-len(HA.JOURNAL) // 17))
                        st['jp'] = (st['jp'] - 1) % tj
                    elif mode == 'aide' and st['aide_general']:
                        st['aide_page'] = (st['aide_page'] - 1) % len(P._AIDE_GENERAL_PAGES)
                elif len(cmd) == 1 and cmd.lower() in LETTER_MODES:
                    st['mode'], st['page'] = LETTER_MODES[cmd.lower()], 0
                    if st['mode'] == 'aide':
                        st.update(aide_general=True, aide_page=0)
                elif cmd.startswith('AGENT:'):
                    try:
                        i = int(cmd.split(':', 1)[1])
                        if 0 <= i < len(AGENTS):
                            st.update(assist_agent_idx=i, assist_conv_id=None,
                                      assist_history=[])
                            flash = f'Agent: {AGENTS[i]["name"]}'
                    except ValueError:
                        pass
                elif cmd.startswith('ASK:') and mode == 'assistant':
                    question = cmd[4:].strip()
                    if question:
                        idx = st['assist_agent_idx']
                        await ws.send_str(json.dumps({
                            'type': 'assistant', 'mode': 'assistant',
                            'history': st['assist_history'], 'agents': AGENTS,
                            'agent_idx': idx,
                            'agent_name': AGENTS[idx]['name'] if AGENTS else '',
                            'conv_id': st['assist_conv_id'],
                            'flash': 'En attente...', 'loading': True,
                            'ts': datetime.now().isoformat()}))
                        res = await HA.converse(
                            session, question,
                            agent_id=AGENTS[idx]['id'],
                            language=ASSIST_CFG.get('language', 'fr'),
                            conversation_id=st['assist_conv_id'])
                        st['assist_conv_id'] = (None if res.get('reset_conv')
                                                else res.get('conv_id'))
                        st['assist_history'].append({
                            'q': question, 'r': res.get('speech', '...'),
                            'ok': res.get('ok', False)})
                        st['assist_history'] = st['assist_history'][-20:]
                    await push()
                    continue
                elif cmd == 'CLEAR_HISTORY' and mode == 'assistant':
                    st.update(assist_history=[], assist_conv_id=None)
                elif cmd.isdigit() and mode == 'domotique':
                    idx = st['page'] * P.PAGE_SIZE + int(cmd) - 1
                    if 0 <= idx < len(DEVICES):
                        dev = DEVICES[idx]
                        ok  = await HA.toggle(session, dev['entity'], dev['name'])
                        flash = f'{"OK" if ok else "ERR"} - {dev["name"]}'
                        await asyncio.sleep(1.2)
                elif cmd.isdigit() and mode == 'scenes':
                    items = list(SCENES) + list(SCRIPTS)
                    idx   = int(cmd) - 1
                    if 0 <= idx < len(items):
                        it = items[idx]
                        ok = await HA.activate(session, it['entity'], it['name'])
                        flash = f'{"OK" if ok else "ERR"} - {it["name"]}'
                        await asyncio.sleep(0.5)

                await push(flash)

    except (asyncio.CancelledError, ConnectionResetError):
        pass
    except Exception as e:
        log('ERR', f'browser_ws: {type(e).__name__}: {e}')
    finally:
        log('BR', f'- {remote}')
    return ws
