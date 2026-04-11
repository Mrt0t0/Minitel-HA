import asyncio, aiohttp, websockets
from pathlib  import Path
from utils    import log
import pagevideo as P
import ha_client  as HA

LETTER_MODES = {
    'd': 'domotique', 'm': 'meteo',    's': 'scenes',
    'j': 'journal',   'a': 'assistant','h': 'aide',   'r': 'archives',
}

VT_STATE = {}

def new_state():
    return {
        'mode': 'domotique', 'page': 0, 'buf': '',
        'journal_page': 0, 'prev_mode': 'domotique',
        'aide_general': False, 'aide_page': 0,
        'assist_history': [], 'assist_agent_idx': 0,
        'assist_conv_id': None, 'assist_buf': '',
        'archives_idx': 0, 'archives_viewing': False,
    }

DEVICES=[]; SENSORS=[]; SCENES=[]; SCRIPTS=[]
QUICK_OFF=None; METEO_CFG={}; AREA_ORDER=None
AGENTS=[]; ASSIST_CFG={}; ARCHIVES_CFG={}; ARCHIVES_FOLDER=Path('static/archives')

def configure(cfg):
    global DEVICES,SENSORS,SCENES,SCRIPTS,QUICK_OFF,METEO_CFG,AREA_ORDER
    global AGENTS,ASSIST_CFG,ARCHIVES_CFG,ARCHIVES_FOLDER
    DEVICES=cfg['devices']; SENSORS=cfg['sensors']
    SCENES=cfg['scenes'];   SCRIPTS=cfg['scripts']
    QUICK_OFF=cfg.get('quick_off')
    METEO_CFG=cfg.get('meteo',{})
    AREA_ORDER=cfg.get('area_order')
    ASSIST_CFG=cfg.get('assistant',{})
    AGENTS=ASSIST_CFG.get('agents',[{'id':'home_assistant','name':'Assistant HA'}])
    ARCHIVES_CFG=cfg.get('archives',{})
    ARCHIVES_FOLDER=Path(cfg.get('_base','.'))/ARCHIVES_CFG.get('folder','static/archives')

def _list_vdt():
    try:
        return [{'name':f.stem,'path':str(f),'size':f.stat().st_size}
                for f in sorted(ARCHIVES_FOLDER.glob('*.vdt'))]
    except Exception as e:
        log('ERR', f'list_vdt: {e}'); return []

async def vt_ws_handler(ws):
    addr = ws.remote_address
    VT_STATE[ws] = new_state()
    log('VT', f'+ {addr}')

    splash_dur = P.CFG.get('splash_seconds', 7)
    if splash_dur > 0:
        await ws.send(P.build_splash())
        await asyncio.sleep(splash_dur)

    try:
        async with aiohttp.ClientSession() as session:
            await ws.send(P.build_loading())
            d, s, stats = await HA.fetch_data(session, DEVICES, SENSORS)
            st = VT_STATE[ws]
            st['mode'] = 'menu'
            await ws.send(P.build_menu(stats))

            _input_timer = None
            _arc_rotate_task = None

            def _reset_timer():
                nonlocal _input_timer
                if _input_timer: _input_timer.cancel()
                _input_timer = asyncio.get_event_loop().call_later(
                    10, lambda: asyncio.ensure_future(_clear_buf()))

            async def _clear_buf():
                st = VT_STATE.get(ws)
                if st and st['buf']:
                    st['buf'] = ''
                    await ws.send(P.build_input_line(''))

            async def _arc_rotate():
                interval = int(ARCHIVES_CFG.get('auto_rotate', 30))
                if interval <= 0: return
                while True:
                    await asyncio.sleep(interval)
                    st = VT_STATE.get(ws, {})
                    if st.get('mode') != 'archives' or st.get('archives_viewing'): continue
                    files = _list_vdt()
                    if len(files) < 2: continue
                    st['archives_idx'] = (st.get('archives_idx', 0) + 1) % len(files)
                    try: await ws.send(P.build_archives(files, st['archives_idx']))
                    except Exception: break

            async def _refresh(d, s, stats, flash=''):
                st = VT_STATE.get(ws, {}); mode = st.get('mode','domotique')
                if mode=='domotique':
                    await ws.send(P.build(d,s,stats,st.get('page',0),
                        st.get('buf',''),area_order=AREA_ORDER,flash_msg=flash))
                elif mode=='menu':   await ws.send(P.build_menu(stats,st.get('buf','')))
                elif mode=='journal':await ws.send(P.build_journal(HA.JOURNAL,st.get('journal_page',0)))
                elif mode=='scenes': await ws.send(P.build_scenes(SCENES,SCRIPTS,st.get('buf',''),flash))
                elif mode=='meteo':
                    meteo=await HA.fetch_meteo(session,METEO_CFG)
                    await ws.send(P.build_meteo(meteo))
                elif mode=='aide':
                    await ws.send(P.build_aide(st.get('prev_mode','domotique'),
                        st.get('aide_page',0),st.get('aide_general',False)))
                elif mode=='assistant':
                    await ws.send(P.build_assistant(st.get('assist_history',[]),AGENTS,
                        st.get('assist_agent_idx',0),st.get('assist_buf',''),flash))
                elif mode=='archives':
                    await ws.send(P.build_archives(_list_vdt(),
                        st.get('archives_idx',0),flash))

            async def _switch(mode, general_aide=False):
                """
                Sprint 12 : general_aide=True → aide générale directe (depuis [H])
                """
                nonlocal _arc_rotate_task
                st = VT_STATE.get(ws, {})
                if st.get('mode') != 'aide':
                    st['prev_mode'] = st.get('mode', 'domotique')
                st['mode'] = mode; st['buf'] = ''; st['page'] = 0
                if mode != 'assistant': st['assist_buf'] = ''
                if mode == 'aide':
                    st['aide_general'] = general_aide
                    st['aide_page']    = 0
                if mode == 'archives':
                    st['archives_viewing'] = False
                    if _arc_rotate_task: _arc_rotate_task.cancel()
                    _arc_rotate_task = asyncio.ensure_future(_arc_rotate())
                await _refresh(d, s, stats)

            async for raw in ws:
                data = raw if isinstance(raw, bytes) else raw.encode()
                st   = VT_STATE.get(ws, {}); mode = st.get('mode','domotique')
                page = st.get('page', 0); jp = st.get('journal_page', 0)
                total_p  = max(1, -(-len(d) // P.PAGE_SIZE))
                total_jp = max(1, -(-len(HA.JOURNAL) // 17))
                refresh  = False; flash = ''

                log('VT', f'[{addr[0]}][{mode}] {data.hex()[:16]}')

                if data in (b'\x13\x49', b'\x13\x46'):
                    d,s,stats = await HA.fetch_data(session, DEVICES, SENSORS)
                    st['mode'] = 'menu'; st['buf'] = ''
                    await ws.send(P.build_menu(stats)); continue

                elif data == b'\x13\x44':
                    if mode == 'aide':
                        if st.get('aide_general'):
                            await _switch(st.get('prev_mode', 'domotique'))
                        else:
                            st['aide_general'] = True; st['aide_page'] = 0
                            await ws.send(P.build_aide(st.get('prev_mode','domotique'), 0, True))
                    else:
                        st['prev_mode'] = mode; st['mode'] = 'aide'
                        st['buf'] = ''; st['aide_general'] = False; st['aide_page'] = 0
                        await ws.send(P.build_aide(mode, 0, False))
                    continue

                elif data == b'\x13\x45':
                    if mode == 'assistant':
                        st['assist_buf'] = ''; await ws.send(P.build_assist_input_line(''))
                    elif mode == 'archives' and st.get('archives_viewing'):
                        st['archives_viewing'] = False; await _refresh(d, s, stats)
                    else:
                        st['buf'] = ''; await ws.send(P.build_input_line(''))
                    continue

                elif mode == 'aide':
                    gen = st.get('aide_general', False)
                    total_aide = len(P._AIDE_GENERAL_PAGES)
                    if data == b'\x13\x48':
                        if gen: st['aide_page'] = (st.get('aide_page',0)+1) % total_aide
                        await ws.send(P.build_aide(st.get('prev_mode','domotique'),st.get('aide_page',0),gen))
                    elif data == b'\x13\x42':
                        if gen: st['aide_page'] = (st.get('aide_page',0)-1) % total_aide
                        await ws.send(P.build_aide(st.get('prev_mode','domotique'),st.get('aide_page',0),gen))
                    elif data == b'\x13\x41' or any(b == 0x0d for b in data):
                        await _switch(st.get('prev_mode','domotique'))
                    else:
                        for byte in data:
                            if chr(byte).lower() in LETTER_MODES:
                                tgt = LETTER_MODES[chr(byte).lower()]
                                await _switch(tgt, general_aide=(tgt == 'aide')); break
                    continue

                elif mode == 'archives':
                    files = _list_vdt(); total_files = len(files)
                    aidx = st.get('archives_idx', 0)
                    viewing = st.get('archives_viewing', False)
                    if viewing:
                        if data == b'\x13\x48':
                            aidx = (aidx+1) % max(1,total_files); st['archives_idx'] = aidx
                            if files: await ws.send(Path(files[aidx]['path']).read_bytes())
                        elif data == b'\x13\x42':
                            aidx = (aidx-1) % max(1,total_files); st['archives_idx'] = aidx
                            if files: await ws.send(Path(files[aidx]['path']).read_bytes())
                        else:
                            st['archives_viewing'] = False
                            await ws.send(P.build_archives(files, aidx))
                    else:
                        if data == b'\x13\x48':
                            if total_files > 0: st['archives_idx'] = (aidx+1) % total_files
                            await ws.send(P.build_archives(_list_vdt(), st['archives_idx']))
                        elif data == b'\x13\x42':
                            if total_files > 0: st['archives_idx'] = (aidx-1) % total_files
                            await ws.send(P.build_archives(_list_vdt(), st['archives_idx']))
                        elif data == b'\x13\x41' or any(b == 0x0d for b in data):
                            buf = st.get('buf', '')
                            if buf.isdigit(): aidx = int(buf) - 1
                            if files and 0 <= aidx < total_files:
                                try:
                                    vdt = Path(files[aidx]['path']).read_bytes()
                                    st['archives_idx'] = aidx
                                    st['archives_viewing'] = True; st['buf'] = ''
                                    log('VT', f'vdt: {files[aidx]["name"]}')
                                    await ws.send(vdt)
                                except Exception as e:
                                    await ws.send(P.build_archives(files, aidx, f'Erreur: {e}'))
                            continue
                        else:
                            for byte in data:
                                ch = chr(byte)
                                if ch in '123456789' and total_files > 0:
                                    n = int(ch)-1; offset = (st.get('archives_idx',0)//9)*9
                                    ri = offset + n
                                    if ri < total_files: st['archives_idx'] = ri; st['buf'] = ch
                                elif ch.lower() in LETTER_MODES:
                                    tgt = LETTER_MODES[ch.lower()]
                                    await _switch(tgt, general_aide=(tgt == 'aide')); break
                            await ws.send(P.build_archives(_list_vdt(), st.get('archives_idx',0)))
                    continue

                elif mode == 'assistant':
                    abuf = st.get('assist_buf', '')
                    if data == b'\x13\x48':
                        if len(AGENTS) > 1:
                            idx = (st.get('assist_agent_idx',0)+1) % len(AGENTS)
                            st['assist_agent_idx'] = idx
                            st['assist_conv_id'] = None; st['assist_history'] = []
                            await ws.send(P.build_assistant([],AGENTS,idx,'',
                                f"Agent: {P._clean(AGENTS[idx].get('name',''))}"))
                        continue
                    elif data in (b'\x13\x41',) or any(b == 0x0d for b in data):
                        abuf = st.get('assist_buf', '').strip()
                        if abuf:
                            await ws.send(P.build_assist_input_line('', 'En attente...'))
                            agent = AGENTS[st.get('assist_agent_idx', 0)]
                            result = await HA.converse(session, abuf,
                                agent_id=agent['id'],
                                language=ASSIST_CFG.get('language','fr'),
                                conversation_id=st.get('assist_conv_id'))
                            if result.get('reset_conv'): st['assist_conv_id'] = None
                            else: st['assist_conv_id'] = result.get('conv_id')
                            st['assist_history'].append({
                                'q': abuf, 'r': result.get('speech', '…')})
                            if len(st['assist_history']) > 10:
                                st['assist_history'] = st['assist_history'][-10:]
                            st['assist_buf'] = ''
                            await ws.send(P.build_assistant(st['assist_history'],AGENTS,
                                st.get('assist_agent_idx',0),'',''))
                        continue
                    elif data in (b'\x13\x47',) or any(b in (0x7f,0x08) for b in data):
                        st['assist_buf'] = abuf[:-1]
                        await ws.send(P.build_assist_input_line(st['assist_buf'])); continue
                    else:
                        for byte in data:
                            if 0x20 <= byte <= 0x7e and len(abuf) < 38: abuf += chr(byte)
                        st['assist_buf'] = abuf
                        await ws.send(P.build_assist_input_line(abuf)); continue

                elif mode == 'journal':
                    if data == b'\x13\x48': st['journal_page'] = (jp+1) % total_jp
                    elif data == b'\x13\x42': st['journal_page'] = (jp-1) % total_jp
                    else:
                        for byte in data:
                            if chr(byte).lower() in LETTER_MODES:
                                tgt = LETTER_MODES[chr(byte).lower()]
                                await _switch(tgt, general_aide=(tgt=='aide')); break
                    await ws.send(P.build_journal(HA.JOURNAL, st['journal_page'])); continue

                elif mode == 'meteo':
                    switched = False
                    for byte in data:
                        if chr(byte).lower() in LETTER_MODES:
                            tgt = LETTER_MODES[chr(byte).lower()]
                            await _switch(tgt, general_aide=(tgt=='aide'))
                            switched = True; break
                    if not switched:
                        meteo = await HA.fetch_meteo(session, METEO_CFG)
                        await ws.send(P.build_meteo(meteo))
                    continue

                elif mode == 'scenes':
                    all_items = SCENES + SCRIPTS
                    if data == b'\x13\x41' or any(b == 0x0d for b in data):
                        buf = st.get('buf', '')
                        if buf.isdigit():
                            idx = int(buf) - 1
                            if 0 <= idx < len(all_items):
                                item = all_items[idx]
                                ok = await HA.activate(session, item['entity'], item['name'])
                                fl = f"[{'OK' if ok else 'ERR'}] {P._clean(item['name'])[:28]}"
                                st['buf'] = ''
                                await ws.send(P.build_scenes(SCENES,SCRIPTS,"",fl))
                                await asyncio.sleep(1.5)
                                await ws.send(P.build_scenes(SCENES,SCRIPTS)); continue
                        st['buf'] = ''; await ws.send(P.build_scenes(SCENES,SCRIPTS)); continue
                    for byte in data:
                        ch = chr(byte).lower()
                        if ch in LETTER_MODES:
                            await _switch(LETTER_MODES[ch], general_aide=(ch=='h')); break
                        elif chr(byte) in '123456789':
                            st['buf'] = chr(byte); _reset_timer()
                            await ws.send(P.build_input_line(st['buf']))
                    continue

                elif mode == 'menu':
                    for byte in data:
                        ch = chr(byte).lower()
                        if ch in LETTER_MODES:
                            st['buf'] = ch
                            d,s,stats = await HA.fetch_data(session, DEVICES, SENSORS)
                            await ws.send(P.build_menu(stats, ch))
                    if data == b'\x13\x41' or any(b == 0x0d for b in data):
                        buf = st.get('buf', '').lower()
                        if buf in LETTER_MODES:
                            await _switch(LETTER_MODES[buf], general_aide=(buf == 'h'))
                            if LETTER_MODES[buf] == 'domotique':
                                await ws.send(P.build_loading())
                                d,s,stats = await HA.fetch_data(session, DEVICES, SENSORS)
                                await ws.send(P.build(d,s,stats,0,"",area_order=AREA_ORDER))
                    continue

                else:
                    if data == b'\x13\x48':
                        st['page'] = (page+1) % total_p; st['buf'] = ''; refresh = True
                    elif data == b'\x13\x42':
                        st['page'] = (page-1) % total_p; st['buf'] = ''; refresh = True
                    elif data == b'\x13\x41':
                        _reset_timer(); buf = st.get('buf', '')
                        if buf.lower() in LETTER_MODES:
                            await _switch(LETTER_MODES[buf.lower()],
                                          general_aide=(buf.lower()=='h')); continue
                        if buf.isdigit():
                            idx = page * P.PAGE_SIZE + int(buf) - 1
                            if 0 <= idx < len(DEVICES):
                                dev = DEVICES[idx]
                                ok  = await HA.toggle(session, dev['entity'], dev['name'])
                                await asyncio.sleep(1.5)
                                flash = f"[{'OK' if ok else 'ERR'}] {P._clean(dev['name'])[:28]}"
                        st['buf'] = ''; refresh = True
                    elif data in (b'\x13\x45', b'\x13\x47'):
                        st['buf'] = ''; await ws.send(P.build_input_line('')); continue
                    else:
                        for byte in data:
                            ch = chr(byte)
                            if ch == '*' and QUICK_OFF:
                                ok = await HA.activate(session, QUICK_OFF['entity'],
                                                        QUICK_OFF.get('name',''))
                                flash = f"[{'OK' if ok else 'ERR'}] {QUICK_OFF.get('name','')}"
                                await asyncio.sleep(1.5); refresh = True
                            elif ch == '0':
                                await _switch('journal'); break
                            elif ch.lower() in LETTER_MODES:
                                st['buf'] = ch.lower(); _reset_timer()
                                await ws.send(P.build_input_line(ch.lower()))
                            elif ch in '123456789':
                                st['buf'] = ch; _reset_timer()
                                await ws.send(P.build_input_line(ch))
                            elif byte == 0x0d:
                                _reset_timer(); buf = st.get('buf', '')
                                if buf.lower() in LETTER_MODES:
                                    await _switch(LETTER_MODES[buf.lower()],
                                                  general_aide=(buf.lower()=='h')); break
                                if buf.isdigit():
                                    idx = page * P.PAGE_SIZE + int(buf) - 1
                                    if 0 <= idx < len(DEVICES):
                                        dev = DEVICES[idx]
                                        ok  = await HA.toggle(session, dev['entity'], dev['name'])
                                        await asyncio.sleep(1.5)
                                        flash = f"[{'OK' if ok else 'ERR'}] {P._clean(dev['name'])[:28]}"
                                st['buf'] = ''; refresh = True
                            elif byte in (0x7f, 0x08):
                                st['buf'] = ''; await ws.send(P.build_input_line(''))

                    if refresh:
                        await ws.send(P.build_loading())
                        d,s,stats = await HA.fetch_data(session, DEVICES, SENSORS)
                        await ws.send(P.build(d,s,stats,VT_STATE[ws]['page'],"",
                                             area_order=AREA_ORDER, flash_msg=flash))
                        if flash:
                            await asyncio.sleep(1.5)
                            await ws.send(P.build(d,s,stats,VT_STATE[ws]['page'],"",
                                                 area_order=AREA_ORDER))

    except websockets.exceptions.ConnectionClosed:
        pass
    except Exception as e:
        log('ERR', f'vt handler: {e}')
    finally:
        VT_STATE.pop(ws, None)
        log('VT', f'- {addr}')

async def auto_refresh(delay):
    while True:
        await asyncio.sleep(delay)
        if not VT_STATE: continue
        async with aiohttp.ClientSession() as session:
            d,s,stats = await HA.fetch_data(session, DEVICES, SENSORS)
            dead = set()
            for ws, st in list(VT_STATE.items()):
                if st.get('mode') != 'domotique': continue
                try: await ws.send(P.build(d,s,stats,st.get('page',0),"",area_order=AREA_ORDER))
                except: dead.add(ws)
            for ws in dead: VT_STATE.pop(ws, None)

async def clock_update():
    while True:
        await asyncio.sleep(60)
        if not VT_STATE: continue
        tick = P.build_time_update(); dead = set()
        for ws, st in list(VT_STATE.items()):
            if st.get('mode') != 'domotique': continue
            try: await ws.send(tick)
            except: dead.add(ws)
        for ws in dead: VT_STATE.pop(ws, None)
