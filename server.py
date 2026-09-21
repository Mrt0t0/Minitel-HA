#!/usr/bin/env python3
import asyncio
import yaml
import aiohttp
import websockets
from pathlib import Path
from aiohttp import web

import ha_client as HA
import pagevideo as P
import pagehtml
import ws_minitel as WM
import ws_browser as WB
from utils import log

BASE = Path(__file__).parent

with open(BASE / 'config.yaml', encoding='utf-8') as f:
    cfg = yaml.safe_load(f) or {}


def _get(section, key, default=None):
    """Lecture robuste : une cle presente mais vide vaut None en YAML."""
    sec = cfg.get(section) or {}
    val = sec.get(key, default)
    return default if val is None else val


HA_URL  = _get('homeassistant', 'url', '')
HA_TOK  = _get('homeassistant', 'token', '')
VT_PORT = int(_get('server', 'vt_port', 3615))
WB_PORT = int(_get('server', 'http_port', 8080))

if not HA_URL or not HA_TOK:
    log('ERR', 'config.yaml : homeassistant.url et .token sont obligatoires')
    raise SystemExit(1)

P.CFG['page_size']      = int(_get('display', 'page_size', 9))
P.CFG['date_format']    = _get('display', 'date_format', '%H:%M')
P.CFG['show_sensors']   = bool(_get('display', 'show_sensors', True))
P.CFG['splash_seconds'] = int(_get('display', 'splash_seconds', 7))
P.PAGE_SIZE             = P.CFG['page_size']

REFRESH_AUTO = int(_get('display', 'refresh_auto', 30))
AREA_ORDER   = cfg.get('area_order') or None

ARCHIVES_CFG    = cfg.get('archives') or {}
ARCHIVES_FOLDER = (BASE / ARCHIVES_CFG.get('folder', 'static/archives')).resolve()
ARCHIVES_FOLDER.mkdir(parents=True, exist_ok=True)

HA.configure(HA_URL, HA_TOK)
pagehtml.load(WB_PORT)


def _sort_devices(raw):
    if not AREA_ORDER:
        return sorted(raw, key=lambda d: d.get('area', 'Autres'))
    def key(d):
        a = d.get('area', 'Autres')
        return AREA_ORDER.index(a) if a in AREA_ORDER else len(AREA_ORDER)
    return sorted(raw, key=key)


_devices = [d for d in (cfg.get('devices') or []) if d.get('visible', True)]
_sensors = [s for s in (cfg.get('sensors') or []) if s.get('visible', True)]

_assistant = cfg.get('assistant') or {}
if not _assistant.get('agents'):
    _assistant['agents'] = [{'id': 'conversation.home_assistant',
                             'name': 'Assistant HA'}]

_cfg_shared = {
    'devices':    _sort_devices(_devices),
    'sensors':    _sensors,
    'scenes':     cfg.get('scenes') or [],
    'scripts':    cfg.get('scripts') or [],
    'quick_off':  cfg.get('quick_off'),
    'meteo':      cfg.get('meteo') or {},
    'assistant':  _assistant,
    'archives':   ARCHIVES_CFG,
    'area_order': AREA_ORDER,
    '_base':      str(BASE),
}

WM.configure(_cfg_shared)
WB.configure(_cfg_shared)


def list_vdt():
    try:
        return sorted(
            ({'name': f.stem, 'size': f.stat().st_size}
             for f in ARCHIVES_FOLDER.glob('*.vdt')),
            key=lambda x: x['name'])
    except Exception as e:
        log('ERR', f'list_vdt: {e}')
        return []


async def http_index(request):
    return web.Response(text=pagehtml.get(), content_type='text/html')


async def api_archives_list(request):
    files = list_vdt()
    return web.json_response({
        'files':       files,
        'total':       len(files),
        'auto_rotate': int(ARCHIVES_CFG.get('auto_rotate', 30) or 0),
    })


async def api_archives_vdt(request):
    name = request.match_info.get('name', '')
    if name.lower().endswith('.vdt'):
        name = name[:-4]
    target = (ARCHIVES_FOLDER / f'{name}.vdt').resolve()
    # Empeche toute traversee de repertoire (../)
    if ARCHIVES_FOLDER not in target.parents or not target.is_file():
        raise web.HTTPNotFound(text='fichier .vdt introuvable')
    return web.Response(body=target.read_bytes(),
                        content_type='application/octet-stream')


async def main():
    log('CFG', f'{len(_cfg_shared["devices"])} appareils | '
               f'{len(_cfg_shared["sensors"])} capteurs')
    log('CFG', f'{len(_cfg_shared["scenes"])} scenes | '
               f'{len(_cfg_shared["scripts"])} scripts | '
               f'{len(list_vdt())} pages .vdt')
    log('SRV', f'3615 MAISON -> ws://0.0.0.0:{VT_PORT}')
    log('SRV', f'Browser     -> http://0.0.0.0:{WB_PORT}')
    log('SRV', f'HA          -> {HA_URL}')

    # Session HTTP unique partagee par toutes les taches de fond
    session = aiohttp.ClientSession()
    WM.set_session(session)

    app = web.Application()
    app.router.add_get('/',                        http_index)
    app.router.add_get('/ws',                      WB.browser_ws_handler)
    app.router.add_get('/api/archives/list',       api_archives_list)
    app.router.add_get('/api/archives/vdt/{name}', api_archives_vdt)
    app.router.add_static('/static/', BASE / 'static')

    runner = web.AppRunner(app)
    await runner.setup()
    await web.TCPSite(runner, '0.0.0.0', WB_PORT).start()

    try:
        async with websockets.serve(WM.vt_ws_handler, '0.0.0.0', VT_PORT):
            await asyncio.gather(
                WM.auto_refresh(REFRESH_AUTO),
                WM.clock_update(),
            )
    finally:
        await session.close()
        await runner.cleanup()


if __name__ == '__main__':
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        log('SRV', 'arret demande')
