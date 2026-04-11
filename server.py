#!/usr/bin/env python3
import asyncio, yaml, websockets
from pathlib  import Path
from aiohttp  import web
from utils    import log
import ha_client  as HA
import pagevideo  as P
import pagehtml
import ws_minitel as WM
import ws_browser as WB

BASE = Path(__file__).parent
cfg  = yaml.safe_load(open(BASE / 'config.yaml'))

HA_URL  = cfg['homeassistant']['url']
HA_TOK  = cfg['homeassistant']['token']
VT_PORT = cfg['server']['vt_port']
WB_PORT = cfg['server']['http_port']
DISP    = cfg.get('display', {})
REFRESH_AUTO = DISP.get('refresh_auto', 30)
AREA_ORDER   = cfg.get('area_order', None)
ARCHIVES_CFG = cfg.get('archives', {})
ASSIST_CFG   = cfg.get('assistant', {
    'language': 'fr', 'default_agent': 'home_assistant',
    'agents': [{'id': 'home_assistant', 'name': 'Assistant HA'}]
})

P.CFG['title']          = DISP.get('title',         P.CFG['title'])
P.CFG['page_size']      = DISP.get('page_size',      9)
P.CFG['date_format']    = DISP.get('date_format',    '%H:%M')
P.CFG['show_sensors']   = DISP.get('show_sensors',   True)
P.CFG['splash_seconds'] = DISP.get('splash_seconds', 7)
P.PAGE_SIZE             = P.CFG['page_size']

HA.configure(HA_URL, HA_TOK)
pagehtml.load(WB_PORT)

ARCHIVES_FOLDER = BASE / ARCHIVES_CFG.get('folder', 'static/archives')
ARCHIVES_FOLDER.mkdir(parents=True, exist_ok=True)

def _sort_devices(raw):
    if not AREA_ORDER:
        return sorted(raw, key=lambda d: d.get('area', 'Autres'))
    def key(d):
        a = d.get('area', 'Autres')
        try:    return AREA_ORDER.index(a)
        except: return len(AREA_ORDER)
    return sorted(raw, key=key)

_cfg_shared = {
    'devices':    _sort_devices([d for d in cfg.get('devices', []) if d.get('visible', True)]),
    'sensors':    [s for s in cfg.get('sensors', []) if s.get('visible', True)],
    'scenes':     cfg.get('scenes',   []),
    'scripts':    cfg.get('scripts',  []),
    'quick_off':  cfg.get('quick_off', None),
    'meteo':      cfg.get('meteo',    {}),
    'area_order': AREA_ORDER,
    'assistant':  ASSIST_CFG,
    'archives':   ARCHIVES_CFG,
    '_base':      str(BASE),
}

WM.configure(_cfg_shared)
WB.configure(_cfg_shared)

n_vdt = len(list(ARCHIVES_FOLDER.glob('*.vdt')))
log('INFO', '═' * 46)
log('INFO', f'  3615 MAISON — Minitel-HA v{P.VERSION}')
log('INFO', '─' * 46)
log('INFO', f'  Minitel     ws://0.0.0.0:{VT_PORT}  (ESP32/MiniPavi)')
log('INFO', f'  Navigateur  http://0.0.0.0:{WB_PORT}')
log('INFO', f'  HA          {HA_URL}')
log('INFO', '─' * 46)
log('INFO', f'  Appareils : {len(_cfg_shared["devices"])} | Capteurs : {len(_cfg_shared["sensors"])}')
log('INFO', f'  Météo     : {cfg.get("meteo", {}).get("weather_entity", "—")}')
log('INFO', f'  Archives  : {n_vdt} .vdt dans {ARCHIVES_FOLDER}')
log('INFO', '═' * 46)

async def http_handler(request):
    return web.Response(text=pagehtml.get(), content_type='text/html')

async def archives_list_handler(request):
    files = [{'name': f.stem, 'size': f.stat().st_size}
             for f in sorted(ARCHIVES_FOLDER.glob('*.vdt'))]
    return web.json_response({'files': files, 'total': len(files)})

async def archives_vdt_handler(request):
    name = request.match_info.get('name', '')
    name = name.replace('/', '').replace('\\', '').replace('..', '')
    if not name.endswith('.vdt'):
        name += '.vdt'
    vdt_path = (ARCHIVES_FOLDER / name).resolve()
    if not str(vdt_path).startswith(str(ARCHIVES_FOLDER.resolve())):
        return web.Response(status=403, text='Accès refusé')
    if not vdt_path.exists() or not vdt_path.is_file():
        return web.Response(status=404, text='Fichier introuvable')
    data = vdt_path.read_bytes()
    log('INFO', f'VDT servi: {name} ({len(data)} oct)')
    return web.Response(
        body=data,
        content_type='application/octet-stream',
        headers={'Access-Control-Allow-Origin': '*',
                 'Content-Disposition': f'inline; filename="{name}"'})

async def main():
    app = web.Application()
    app.router.add_get('/',                       http_handler)
    app.router.add_get('/ws',                     WB.browser_ws_handler)
    app.router.add_get('/api/archives/list',      archives_list_handler)
    app.router.add_get('/api/archives/vdt/{name}',archives_vdt_handler)
    runner = web.AppRunner(app)
    await runner.setup()
    await web.TCPSite(runner, '0.0.0.0', WB_PORT).start()
    log('INFO', 'Serveurs démarrés')
    async with websockets.serve(WM.vt_ws_handler, '0.0.0.0', VT_PORT):
        await asyncio.gather(
            asyncio.Future(),
            WM.auto_refresh(REFRESH_AUTO),
            WM.clock_update(),
        )

asyncio.run(main())
