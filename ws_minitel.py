import asyncio
import aiohttp
import websockets
from pathlib import Path

import pagevideo as P
import ha_client as HA
from utils import log

LETTER_MODES = {
    'd': 'domotique', 'm': 'meteo', 's': 'scenes', 'j': 'journal',
    'a': 'assistant', 'h': 'aide', 'r': 'archives',
}

VT_STATE = {}
_SESSION = None

DEVICES = SENSORS = SCENES = SCRIPTS = ()
QUICK_OFF = None
METEO_CFG = ASSIST_CFG = ARCHIVES_CFG = {}
AREA_ORDER = None
AGENTS = []
ARCHIVES_FOLDER = Path('static/archives')


def set_session(session):
    global _SESSION
    _SESSION = session


def configure(cfg):
    global DEVICES, SENSORS, SCENES, SCRIPTS, QUICK_OFF, METEO_CFG
    global AREA_ORDER, AGENTS, ASSIST_CFG, ARCHIVES_CFG, ARCHIVES_FOLDER
    DEVICES    = cfg['devices']
    SENSORS    = cfg['sensors']
    SCENES     = cfg['scenes']
    SCRIPTS    = cfg['scripts']
    QUICK_OFF  = cfg.get('quick_off')
    METEO_CFG  = cfg.get('meteo') or {}
    AREA_ORDER = cfg.get('area_order')
    ASSIST_CFG = cfg.get('assistant') or {}
    AGENTS     = ASSIST_CFG.get('agents') or [
        {'id': 'conversation.home_assistant', 'name': 'Assistant HA'}]
    ARCHIVES_CFG = cfg.get('archives') or {}
    ARCHIVES_FOLDER = (Path(cfg.get('_base', '.'))
                       / ARCHIVES_CFG.get('folder', 'static/archives'))


def new_state():
    return {
        'mode': 'menu', 'page': 0, 'buf': '', 'journal_page': 0,
        'prev_mode': 'domotique', 'aide_general': False, 'aide_page': 0,
        'assist_history': [], 'assist_agent_idx': 0,
        'assist_conv_id': None, 'assist_buf': '',
        'archives_idx': 0, 'archives_viewing': False,
    }


def _list_vdt():
    try:
        ARCHIVES_FOLDER.mkdir(parents=True, exist_ok=True)
        return sorted(({'name': f.stem, 'path': str(f), 'size': f.stat().st_size}
                       for f in ARCHIVES_FOLDER.glob('*.vdt')),
                      key=lambda x: x['name'])
    except Exception as e:
        log('ERR', f'list_vdt: {e}')
        return []


async def vt_ws_handler(ws):
    addr = ws.remote_address
    VT_STATE[ws] = new_state()
    log('VT', f'+ {addr}')

    input_timer = None
    rotate_task = None

    try:
        splash = P.CFG.get('splash_seconds', 7)
        if splash > 0:
            await ws.send(P.build_splash())
            await asyncio.sleep(splash)

        async with aiohttp.ClientSession() as session:
            await ws.send(P.build_loading())
            d, s, stats = await HA.fetch_data(session, DEVICES, SENSORS)
            st = VT_STATE[ws]
            await ws.send(P.build_menu(stats))

            async def clear_buf():
                cur = VT_STATE.get(ws)
                if cur and cur['buf']:
                    cur['buf'] = ''
                    await ws.send(P.build_input_line(''))

            def reset_timer():
                nonlocal input_timer
                if input_timer:
                    input_timer.cancel()
                input_timer = asyncio.get_running_loop().call_later(
                    10, lambda: asyncio.ensure_future(clear_buf()))

            async def rotate_archives():
                interval = int(ARCHIVES_CFG.get('auto_rotate', 30) or 0)
                if interval <= 0:
                    return
                while True:
                    await asyncio.sleep(interval)
                    cur = VT_STATE.get(ws)
                    if not cur or cur['mode'] != 'archives' or cur['archives_viewing']:
                        continue
                    files = _list_vdt()
                    if len(files) < 2:
                        continue
                    cur['archives_idx'] = (cur['archives_idx'] + 1) % len(files)
                    try:
                        await ws.send(P.build_archives(files, cur['archives_idx']))
                    except Exception:
                        return

            async def refresh(flash=''):
                cur  = VT_STATE.get(ws, {})
                mode = cur.get('mode', 'domotique')
                if mode == 'domotique':
                    await ws.send(P.build(d, s, stats, cur['page'], cur['buf'],
                                          area_order=AREA_ORDER, flash_msg=flash))
                elif mode == 'menu':
                    await ws.send(P.build_menu(stats, cur['buf']))
                elif mode == 'journal':
                    await ws.send(P.build_journal(HA.JOURNAL, cur['journal_page']))
                elif mode == 'scenes':
                    await ws.send(P.build_scenes(SCENES, SCRIPTS, cur['buf'], flash))
                elif mode == 'meteo':
                    await ws.send(P.build_meteo(await HA.fetch_meteo(session, METEO_CFG)))
                elif mode == 'aide':
                    await ws.send(P.build_aide(cur['prev_mode'], cur['aide_page'],
                                               cur['aide_general']))
                elif mode == 'assistant':
                    await ws.send(P.build_assistant(cur['assist_history'], AGENTS,
                                                    cur['assist_agent_idx'],
                                                    cur['assist_buf'], flash))
                elif mode == 'archives':
                    await ws.send(P.build_archives(_list_vdt(), cur['archives_idx'], flash))

            async def switch(mode, general_aide=False):
                nonlocal rotate_task
                cur = VT_STATE.get(ws, {})
                if cur.get('mode') != 'aide':
                    cur['prev_mode'] = cur.get('mode', 'domotique')
                cur.update(mode=mode, buf='', page=0)
                if mode != 'assistant':
                    cur['assist_buf'] = ''
                if mode == 'aide':
                    cur.update(aide_general=general_aide, aide_page=0)
                if mode == 'archives':
                    cur['archives_viewing'] = False
                    if rotate_task:
                        rotate_task.cancel()
                    rotate_task = asyncio.ensure_future(rotate_archives())
                elif rotate_task:
                    rotate_task.cancel()
                    rotate_task = None
                await refresh()

            async for raw in ws:
                data = raw if isinstance(raw, bytes) else raw.encode()
                st   = VT_STATE.get(ws)
                if st is None:
                    break
                mode  = st['mode']
                flash = ''
                log('VT', f'[{addr[0]}][{mode}] {data.hex()[:16]}')

                if data in (b'\x13\x49', b'\x13\x46'):          # SOMMAIRE
                    HA.invalidate_cache()
                    d, s, stats = await HA.fetch_data(session, DEVICES, SENSORS)
                    st.update(mode='menu', buf='')
                    await ws.send(P.build_menu(stats))
                    continue

                if data == b'\x13\x44':                          # GUIDE
                    if mode == 'aide':
                        if st['aide_general']:
                            await switch(st['prev_mode'])
                        else:
                            st.update(aide_general=True, aide_page=0)
                            await ws.send(P.build_aide(st['prev_mode'], 0, True))
                    else:
                        st.update(prev_mode=mode, mode='aide', buf='',
                                  aide_general=False, aide_page=0)
                        await ws.send(P.build_aide(mode, 0, False))
                    continue

                if data == b'\x13\x45':                          # ANNULATION
                    if mode == 'assistant':
                        st['assist_buf'] = ''
                        await ws.send(P.build_assist_input_line(''))
                    elif mode == 'archives' and st['archives_viewing']:
                        st['archives_viewing'] = False
                        await refresh()
                    else:
                        st['buf'] = ''
                        await ws.send(P.build_input_line(''))
                    continue

                if mode == 'aide':
                    total = len(P._AIDE_GENERAL_PAGES)
                    if data in (b'\x13\x48', b'\x13\x42'):
                        if st['aide_general']:
                            step = 1 if data == b'\x13\x48' else -1
                            st['aide_page'] = (st['aide_page'] + step) % total
                        await ws.send(P.build_aide(st['prev_mode'], st['aide_page'],
                                                   st['aide_general']))
                    elif data == b'\x13\x41' or 0x0d in data:
                        await switch(st['prev_mode'])
                    else:
                        for byte in data:
                            ch = chr(byte).lower()
                            if ch in LETTER_MODES:
                                await switch(LETTER_MODES[ch], general_aide=(ch == 'h'))
                                break
                    continue

                if mode == 'archives':
                    files = _list_vdt()
                    total = len(files)
                    aidx  = st['archives_idx']
                    if st['archives_viewing']:
                        if data in (b'\x13\x48', b'\x13\x42') and total:
                            step = 1 if data == b'\x13\x48' else -1
                            aidx = (aidx + step) % total
                            st['archives_idx'] = aidx
                            await ws.send(Path(files[aidx]['path']).read_bytes())
                        else:
                            st['archives_viewing'] = False
                            await ws.send(P.build_archives(files, aidx))
                        continue
                    if data in (b'\x13\x48', b'\x13\x42') and total:
                        step = 1 if data == b'\x13\x48' else -1
                        st['archives_idx'] = (aidx + step) % total
                        await ws.send(P.build_archives(files, st['archives_idx']))
                    elif data == b'\x13\x41' or 0x0d in data:
                        if st['buf'].isdigit():
                            aidx = int(st['buf']) - 1
                        if files and 0 <= aidx < total:
                            try:
                                vdt = Path(files[aidx]['path']).read_bytes()
                                st.update(archives_idx=aidx, archives_viewing=True, buf='')
                                log('VT', f'vdt: {files[aidx]["name"]}')
                                await ws.send(vdt)
                            except Exception as e:
                                await ws.send(P.build_archives(files, aidx, f'Erreur: {e}'))
                    else:
                        for byte in data:
                            ch = chr(byte)
                            if ch in '123456789' and total:
                                ri = (st['archives_idx'] // 9) * 9 + int(ch) - 1
                                if ri < total:
                                    st.update(archives_idx=ri, buf=ch)
                            elif ch.lower() in LETTER_MODES:
                                await switch(LETTER_MODES[ch.lower()],
                                             general_aide=(ch.lower() == 'h'))
                                break
                        else:
                            await ws.send(P.build_archives(_list_vdt(), st['archives_idx']))
                    continue

                if mode == 'assistant':
                    abuf = st['assist_buf']
                    if data == b'\x13\x48':
                        if len(AGENTS) > 1:
                            i = (st['assist_agent_idx'] + 1) % len(AGENTS)
                            st.update(assist_agent_idx=i, assist_conv_id=None,
                                      assist_history=[])
                            await ws.send(P.build_assistant([], AGENTS, i, '',
                                          f'Agent: {P._clean(AGENTS[i]["name"])}'))
                    elif data == b'\x13\x41' or 0x0d in data:
                        q = abuf.strip()
                        if q:
                            await ws.send(P.build_assist_input_line('', 'En attente...'))
                            i   = st['assist_agent_idx']
                            res = await HA.converse(
                                session, q, agent_id=AGENTS[i]['id'],
                                language=ASSIST_CFG.get('language', 'fr'),
                                conversation_id=st['assist_conv_id'])
                            st['assist_conv_id'] = (None if res.get('reset_conv')
                                                    else res.get('conv_id'))
                            st['assist_history'].append({'q': q, 'r': res.get('speech', '...')})
                            st['assist_history'] = st['assist_history'][-10:]
                            st['assist_buf'] = ''
                            await ws.send(P.build_assistant(st['assist_history'], AGENTS,
                                                            i, '', ''))
                    elif data == b'\x13\x47' or any(b in (0x7f, 0x08) for b in data):
                        st['assist_buf'] = abuf[:-1]
                        await ws.send(P.build_assist_input_line(st['assist_buf']))
                    else:
                        for byte in data:
                            if 0x20 <= byte <= 0x7e and len(abuf) < 38:
                                abuf += chr(byte)
                        st['assist_buf'] = abuf
                        await ws.send(P.build_assist_input_line(abuf))
                    continue

                if mode == 'journal':
                    total_jp = max(1, -(-len(HA.JOURNAL) // 17))
                    if data in (b'\x13\x48', b'\x13\x42'):
                        step = 1 if data == b'\x13\x48' else -1
                        st['journal_page'] = (st['journal_page'] + step) % total_jp
                    else:
                        for byte in data:
                            ch = chr(byte).lower()
                            if ch in LETTER_MODES:
                                await switch(LETTER_MODES[ch], general_aide=(ch == 'h'))
                                break
                        else:
                            await ws.send(P.build_journal(HA.JOURNAL, st['journal_page']))
                            continue
                        continue
                    await ws.send(P.build_journal(HA.JOURNAL, st['journal_page']))
                    continue

                if mode == 'meteo':
                    for byte in data:
                        ch = chr(byte).lower()
                        if ch in LETTER_MODES:
                            await switch(LETTER_MODES[ch], general_aide=(ch == 'h'))
                            break
                    else:
                        await ws.send(P.build_meteo(await HA.fetch_meteo(session, METEO_CFG)))
                    continue

                if mode == 'scenes':
                    items = list(SCENES) + list(SCRIPTS)
                    if data == b'\x13\x41' or 0x0d in data:
                        if st['buf'].isdigit():
                            idx = int(st['buf']) - 1
                            if 0 <= idx < len(items):
                                it = items[idx]
                                ok = await HA.activate(session, it['entity'], it['name'])
                                st['buf'] = ''
                                await ws.send(P.build_scenes(
                                    SCENES, SCRIPTS, '',
                                    f'[{"OK" if ok else "ERR"}] {P._clean(it["name"])[:28]}'))
                                await asyncio.sleep(1.5)
                        st['buf'] = ''
                        await ws.send(P.build_scenes(SCENES, SCRIPTS))
                        continue
                    for byte in data:
                        ch = chr(byte)
                        if ch.lower() in LETTER_MODES:
                            await switch(LETTER_MODES[ch.lower()],
                                         general_aide=(ch.lower() == 'h'))
                            break
                        if ch in '123456789':
                            st['buf'] = ch
                            reset_timer()
                            await ws.send(P.build_input_line(ch))
                    continue

                if mode == 'menu':
                    for byte in data:
                        ch = chr(byte).lower()
                        if ch in LETTER_MODES:
                            st['buf'] = ch
                            await ws.send(P.build_menu(stats, ch))
                    if data == b'\x13\x41' or 0x0d in data:
                        buf = st['buf'].lower()
                        if buf in LETTER_MODES:
                            target = LETTER_MODES[buf]
                            await switch(target, general_aide=(buf == 'h'))
                            if target == 'domotique':
                                await ws.send(P.build_loading())
                                d, s, stats = await HA.fetch_data(session, DEVICES, SENSORS)
                                await ws.send(P.build(d, s, stats, 0, '',
                                                      area_order=AREA_ORDER))
                    continue

                # ---- mode domotique ----
                total_p = max(1, -(-len(DEVICES) // P.PAGE_SIZE))
                do_refresh = False

                if data in (b'\x13\x48', b'\x13\x42'):
                    step = 1 if data == b'\x13\x48' else -1
                    st.update(page=(st['page'] + step) % total_p, buf='')
                    do_refresh = True
                elif data == b'\x13\x41':
                    reset_timer()
                    buf = st['buf']
                    if buf.lower() in LETTER_MODES:
                        await switch(LETTER_MODES[buf.lower()],
                                     general_aide=(buf.lower() == 'h'))
                        continue
                    if buf.isdigit():
                        idx = st['page'] * P.PAGE_SIZE + int(buf) - 1
                        if 0 <= idx < len(DEVICES):
                            dev = DEVICES[idx]
                            ok  = await HA.toggle(session, dev['entity'], dev['name'])
                            await asyncio.sleep(1.2)
                            flash = f'[{"OK" if ok else "ERR"}] {P._clean(dev["name"])[:28]}'
                    st['buf'] = ''
                    do_refresh = True
                elif data in (b'\x13\x45', b'\x13\x47'):
                    st['buf'] = ''
                    await ws.send(P.build_input_line(''))
                    continue
                else:
                    for byte in data:
                        ch = chr(byte)
                        if ch == '*' and QUICK_OFF:
                            ok = await HA.activate(session, QUICK_OFF['entity'],
                                                   QUICK_OFF.get('name', ''))
                            flash = f'[{"OK" if ok else "ERR"}] {QUICK_OFF.get("name", "")}'
                            await asyncio.sleep(1.2)
                            do_refresh = True
                        elif ch == '0':
                            await switch('journal')
                            break
                        elif ch.lower() in LETTER_MODES or ch in '123456789':
                            st['buf'] = ch.lower() if ch.isalpha() else ch
                            reset_timer()
                            await ws.send(P.build_input_line(st['buf']))
                        elif byte == 0x0d:
                            reset_timer()
                            buf = st['buf']
                            if buf.lower() in LETTER_MODES:
                                await switch(LETTER_MODES[buf.lower()],
                                             general_aide=(buf.lower() == 'h'))
                                break
                            if buf.isdigit():
                                idx = st['page'] * P.PAGE_SIZE + int(buf) - 1
                                if 0 <= idx < len(DEVICES):
                                    dev = DEVICES[idx]
                                    ok  = await HA.toggle(session, dev['entity'], dev['name'])
                                    await asyncio.sleep(1.2)
                                    flash = f'[{"OK" if ok else "ERR"}] {P._clean(dev["name"])[:28]}'
                            st['buf'] = ''
                            do_refresh = True
                        elif byte in (0x7f, 0x08):
                            st['buf'] = ''
                            await ws.send(P.build_input_line(''))

                if do_refresh:
                    await ws.send(P.build_loading())
                    d, s, stats = await HA.fetch_data(session, DEVICES, SENSORS)
                    cur = VT_STATE.get(ws, st)
                    await ws.send(P.build(d, s, stats, cur['page'], '',
                                          area_order=AREA_ORDER, flash_msg=flash))
                    if flash:
                        await asyncio.sleep(1.5)
                        await ws.send(P.build(d, s, stats, cur['page'], '',
                                              area_order=AREA_ORDER))

    except websockets.exceptions.ConnectionClosed:
        pass
    except Exception as e:
        log('ERR', f'vt handler: {type(e).__name__}: {e}')
    finally:
        if input_timer:
            input_timer.cancel()
        if rotate_task:
            rotate_task.cancel()
        VT_STATE.pop(ws, None)
        log('VT', f'- {addr}')


async def _broadcast(payload_fn, only_mode='domotique'):
    dead = []
    for ws, st in list(VT_STATE.items()):
        if st.get('mode') != only_mode:
            continue
        try:
            await ws.send(payload_fn(st))
        except Exception:
            dead.append(ws)
    for ws in dead:
        VT_STATE.pop(ws, None)


async def auto_refresh(delay):
    while True:
        await asyncio.sleep(delay)
        if not VT_STATE or _SESSION is None:
            continue
        HA.invalidate_cache()
        d, s, stats = await HA.fetch_data(_SESSION, DEVICES, SENSORS)
        await _broadcast(lambda st: P.build(d, s, stats, st.get('page', 0), '',
                                            area_order=AREA_ORDER))


async def clock_update():
    while True:
        await asyncio.sleep(60)
        if not VT_STATE:
            continue
        tick = P.build_time_update()
        await _broadcast(lambda st: tick)
