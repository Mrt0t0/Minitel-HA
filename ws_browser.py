import asyncio, json, aiohttp
from collections import defaultdict
from datetime    import datetime
from pathlib     import Path
from aiohttp     import web
from utils       import log
import pagevideo as P
import ha_client as HA

LETTER_MODES = {'d':'domotique','m':'meteo','s':'scenes','j':'journal',
                'a':'assistant','h':'aide','r':'archives'}

DEVICES=[]; SENSORS=[]; SCENES=[]; SCRIPTS=[]
METEO_CFG={}; AGENTS=[]; ASSIST_CFG={}
ARCHIVES_CFG={}; ARCHIVES_FOLDER=Path('static/archives')

def configure(cfg):
    global DEVICES,SENSORS,SCENES,SCRIPTS,METEO_CFG,AGENTS,ASSIST_CFG,ARCHIVES_CFG,ARCHIVES_FOLDER
    DEVICES=cfg['devices']; SENSORS=cfg['sensors']
    SCENES=cfg['scenes'];   SCRIPTS=cfg['scripts']
    METEO_CFG=cfg.get('meteo',{}); ASSIST_CFG=cfg.get('assistant',{})
    AGENTS=ASSIST_CFG.get('agents',[{'id':'home_assistant','name':'Assistant HA'}])
    ARCHIVES_CFG=cfg.get('archives',{})
    ARCHIVES_FOLDER=Path(cfg.get('_base','.'))/ARCHIVES_CFG.get('folder','static/archives')

def _list_vdt():
    try:
        ARCHIVES_FOLDER.mkdir(parents=True, exist_ok=True)
        return [{'name':f.stem,'size':f.stat().st_size}
                for f in sorted(ARCHIVES_FOLDER.glob('*.vdt'))]
    except Exception as e:
        log('ERR', f'list_vdt: {e}'); return []

async def vdt_file_handler(request):
    name = Path(request.match_info['name']).name
    vdt_path = ARCHIVES_FOLDER / (name + '.vdt')
    if not vdt_path.is_file():
        raise web.HTTPNotFound()
    return web.Response(body=vdt_path.read_bytes(),
                        content_type='application/octet-stream',
                        headers={'Cache-Control': 'no-cache'})
async def browser_ws_handler(request):
    ws = web.WebSocketResponse()
    await ws.prepare(request)
    remote = request.remote
    log('BR', f'+ {remote}')

    cur_mode     = 'menu'
    cur_page     = 0; cur_jp = 0
    assist_history = []; assist_agent_idx = 0; assist_conv_id = None
    aide_general = True; aide_page = 0

    try:
        async with aiohttp.ClientSession() as session:

            async def push(flash=''):
                ts = datetime.now().isoformat()
                if cur_mode == 'domotique':
                    devs,sens,stats = await HA.fetch_data(session, DEVICES, SENSORS)
                    areas = defaultdict(list)
                    for dv in devs: areas[dv['area']].append(dv)
                    await ws.send_str(json.dumps({
                        'type':'update','mode':'domotique',
                        'devices':devs,'sensors':sens,'areas':dict(areas),'stats':stats,
                        'page':cur_page,'page_size':P.PAGE_SIZE,'title':P.CFG['title'],
                        'flash':flash,'ts':ts}))
                elif cur_mode == 'menu':
                    _,__,stats = await HA.fetch_data(session, DEVICES, SENSORS)
                    await ws.send_str(json.dumps({'type':'menu','mode':'menu','stats':stats,'ts':ts}))
                elif cur_mode == 'meteo':
                    meteo = await HA.fetch_meteo(session, METEO_CFG)
                    await ws.send_str(json.dumps({
                        'type':'meteo','mode':'meteo',
                        'ext':meteo['ext'],'rooms':meteo['rooms'],
                        'forecast':meteo.get('forecast',[]),'ts':ts}))
                elif cur_mode == 'scenes':
                    await ws.send_str(json.dumps({
                        'type':'scenes','mode':'scenes',
                        'scenes':SCENES,'scripts':SCRIPTS,'flash':flash,'ts':ts}))
                elif cur_mode == 'journal':
                    await ws.send_str(json.dumps({
                        'type':'journal','mode':'journal',
                        'journal':list(HA.JOURNAL),'page':cur_jp,'ts':ts}))
                elif cur_mode == 'assistant':
                    await ws.send_str(json.dumps({
                        'type':'assistant','mode':'assistant',
                        'history':assist_history,'agents':AGENTS,
                        'agent_idx':assist_agent_idx,
                        'agent_name':AGENTS[assist_agent_idx]['name'] if AGENTS else '',
                        'conv_id':assist_conv_id,'flash':flash,'ts':ts}))
                elif cur_mode == 'archives':
                    files = _list_vdt()
                    await ws.send_str(json.dumps({
                        'type':'archives','mode':'archives',
                        'files':files,'total':len(files),
                        'auto_rotate':int(ARCHIVES_CFG.get('auto_rotate',30)),
                        'flash':flash,'ts':ts}))
                elif cur_mode == 'aide':
                    await ws.send_str(json.dumps({
                        'type':'aide','mode':'aide',
                        'aide_general':aide_general,'aide_page':aide_page,
                        'total_pages':len(P._AIDE_GENERAL_PAGES),'ts':ts}))

            await push()

            async for msg in ws:
                if msg.type != aiohttp.WSMsgType.TEXT: break
                cmd = msg.data.strip()
                total_p = max(1, -(-len(DEVICES) // P.PAGE_SIZE))
                flash = ''
                log('BR', f'[{remote}][{cur_mode}] {cmd}')

                if   cmd == 'SOMMAIRE':   cur_mode = 'menu'
                elif cmd == 'ANNULATION':
                    if cur_mode != 'assistant': cur_mode = 'domotique'; cur_page = 0
                elif cmd in ('DOMOTIQUE','D'): cur_mode = 'domotique'; cur_page = 0
                elif cmd == 'METEO':      cur_mode = 'meteo'
                elif cmd == 'SCENES':     cur_mode = 'scenes'
                elif cmd == 'JOURNAL':    cur_mode = 'journal'
                elif cmd == 'ASSISTANT':  cur_mode = 'assistant'
                elif cmd == 'ARCHIVES':   cur_mode = 'archives'
                elif cmd == 'AIDE':
                    cur_mode = 'aide'
                    aide_general = True; aide_page = 0
                elif cmd == 'AIDE_CONTEXTUEL':
                    cur_mode = 'aide'; aide_general = False; aide_page = 0
                elif cmd == 'REFRESH':    pass
                elif cmd == 'SUITE':
                    if cur_mode == 'domotique': cur_page = (cur_page+1) % total_p
                    elif cur_mode == 'journal':
                        total_jp = max(1,-(-len(HA.JOURNAL)//17)); cur_jp = (cur_jp+1) % total_jp
                    elif cur_mode == 'assistant' and len(AGENTS) > 1:
                        assist_agent_idx = (assist_agent_idx+1) % len(AGENTS)
                        assist_conv_id = None; assist_history = []
                        flash = f"Agent: {AGENTS[assist_agent_idx]['name']}"
                    elif cur_mode == 'aide' and aide_general:
                        aide_page = (aide_page+1) % len(P._AIDE_GENERAL_PAGES)
                elif cmd == 'RETOUR':
                    if cur_mode == 'domotique': cur_page = (cur_page-1) % total_p
                    elif cur_mode == 'journal':
                        total_jp = max(1,-(-len(HA.JOURNAL)//17)); cur_jp = (cur_jp-1) % total_jp
                    elif cur_mode == 'aide' and aide_general:
                        aide_page = (aide_page-1) % len(P._AIDE_GENERAL_PAGES)
                elif len(cmd) == 1 and cmd.lower() in LETTER_MODES:
                    cur_mode = LETTER_MODES[cmd.lower()]; cur_page = 0
                    if cur_mode == 'aide':
                        aide_general = True; aide_page = 0
                elif cmd.startswith('AGENT:'):
                    try:
                        idx = int(cmd.split(':')[1])
                        if 0 <= idx < len(AGENTS):
                            assist_agent_idx = idx; assist_conv_id = None; assist_history = []
                            flash = f"Agent: {AGENTS[idx]['name']}"
                    except: pass
                elif cmd.startswith('ASK:') and cur_mode == 'assistant':
                    question = cmd[4:].strip()
                    if question:
                        await ws.send_str(json.dumps({
                            'type':'assistant','mode':'assistant',
                            'history':assist_history,'agents':AGENTS,
                            'agent_idx':assist_agent_idx,
                            'agent_name':AGENTS[assist_agent_idx]['name'] if AGENTS else '',
                            'conv_id':assist_conv_id,'flash':"En attente...",
                            'loading':True,'ts':datetime.now().isoformat()}))
                        agent = AGENTS[assist_agent_idx] if AGENTS else {'id':'home_assistant'}
                        result = await HA.converse(session, question,
                            agent_id=agent['id'],
                            language=ASSIST_CFG.get('language','fr'),
                            conversation_id=assist_conv_id)
                        if result.get('reset_conv'): assist_conv_id = None
                        else: assist_conv_id = result.get('conv_id')
                        assist_history.append({
                            'q': question, 'r': result.get('speech','…'),
                            'ok': result.get('ok', False)})
                        if len(assist_history) > 20:
                            assist_history = assist_history[-20:]
                    await push(); continue
                elif cmd == 'CLEAR_HISTORY' and cur_mode == 'assistant':
                    assist_history = []; assist_conv_id = None
                elif cmd.isdigit() and cur_mode == 'domotique':
                    idx = cur_page * P.PAGE_SIZE + int(cmd) - 1
                    if 0 <= idx < len(DEVICES):
                        dev = DEVICES[idx]
                        ok  = await HA.toggle(session, dev['entity'], dev['name'])
                        flash = f'{"OK" if ok else "ERR"} — {dev["name"]}'
                        await asyncio.sleep(1.5)
                elif cmd.isdigit() and cur_mode == 'scenes':
                    all_items = SCENES + SCRIPTS; idx = int(cmd) - 1
                    if 0 <= idx < len(all_items):
                        item = all_items[idx]
                        ok   = await HA.activate(session, item['entity'], item['name'])
                        flash = f'{"OK" if ok else "ERR"} — {item["name"]}'
                        await asyncio.sleep(0.5)

                await push(flash)

    except Exception as e:
        log('ERR', f'browser_ws: {e}')
    finally:
        log('BR', f'- {remote}')
    return ws
