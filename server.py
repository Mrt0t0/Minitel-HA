#!/usr/bin/env python3
"""Minitel-HA : 3615 MAISON.

- ws://:3615   Minitel physique (ESP32 / TelnetPro / Minimit)
- http://:8080 emulateur Minitel dans le navigateur + API des archives .vdt
"""
import asyncio
import os
import re
from pathlib import Path
from urllib.parse import unquote

import aiohttp
import websockets
from aiohttp import web

import alerts
import ha_client as HA
import ha_live
import hub
import i18n
import journal
import pagehtml
import pagevideo as P
import settings
import ws_browser as WB
import ws_minitel as WM
from utils import log

BASE = Path(__file__).parent

_VDT_NAME = re.compile(r'[\w][\w .-]{0,59}')


def configure(cfg):
    """Applique la configuration aux modules (sans demarrer de serveur)."""
    disp = cfg['display']
    P.CFG.update(title=disp['title'], page_size=disp['page_size'],
                 date_format=disp['date_format'], splash_seconds=disp['splash_seconds'])
    i18n.set_lang(disp['language'])
    HA.configure(cfg['ha']['url'], cfg['ha']['token'])
    journal.configure(cfg['journal']['file'], cfg['journal']['size'])
    alerts.configure(cfg['alerts'])
    cfg['archives']['folder'].mkdir(parents=True, exist_ok=True)
    pagehtml.load(disp['language'], P.VERSION)


# ------------------------------------------------------------------ HTTP

def _authorized(request):
    if not hub.code_required() or WB.is_trusted(request):
        return True
    tok = request.headers.get('X-Minitel-Token') or request.query.get('token')
    return hub.token_valid(tok)


def protected(handler):
    async def wrapper(request):
        if not _authorized(request):
            raise web.HTTPUnauthorized(text='code d\'acces requis')
        return await handler(request)
    return wrapper


def _folder():
    return hub.cfg['archives']['folder']


def list_vdt():
    try:
        return sorted(({'name': f.stem, 'size': f.stat().st_size}
                       for f in _folder().glob('*.vdt')), key=lambda x: x['name'])
    except OSError as e:
        log('ERR', f'list_vdt: {e}')
        return []


async def http_index(request):
    return web.Response(text=pagehtml.get(), content_type='text/html')


@protected
async def api_archives_list(request):
    files = list_vdt()
    return web.json_response({'files': files, 'total': len(files),
                              'auto_rotate': hub.cfg['archives']['auto_rotate']})


@protected
async def api_archives_vdt(request):
    name = request.match_info.get('name', '')
    if name.lower().endswith('.vdt'):
        name = name[:-4]
    target = (_folder() / f'{name}.vdt').resolve()
    # Empeche toute traversee de repertoire (../)
    if _folder() not in target.parents or not target.is_file():
        raise web.HTTPNotFound(text='fichier .vdt introuvable')
    return web.Response(body=target.read_bytes(), content_type='application/octet-stream')


@protected
async def api_archives_upload(request):
    """Depot d'une page .vdt (formulaire multipart, champ `file`)."""
    try:
        reader = await request.multipart()
        field = await reader.next()
    except (AssertionError, ValueError) as e:
        raise web.HTTPBadRequest(text='formulaire multipart attendu') from e
    if field is None or field.name != 'file':
        raise web.HTTPBadRequest(text='champ "file" manquant')
    # Certains clients encodent le nom (Ma%20page.vdt)
    name = Path(unquote(field.filename or '')).name
    if not name.lower().endswith('.vdt') or not _VDT_NAME.fullmatch(name[:-4]):
        raise web.HTTPBadRequest(text='nom invalide (lettres, chiffres, espace . _ - ; .vdt)')
    limit = hub.cfg['archives']['max_upload_kb'] * 1024
    data = bytearray()
    while chunk := await field.read_chunk():
        data += chunk
        if len(data) > limit:
            raise web.HTTPRequestEntityTooLarge(max_size=limit, actual_size=len(data))
    if not data:
        raise web.HTTPBadRequest(text='fichier vide')
    target = _folder() / f'{name[:-4]}.vdt'
    tmp = target.with_suffix('.part')
    tmp.write_bytes(bytes(data))
    os.replace(tmp, target)
    log('SRV', f'archive deposee : {target.name} ({len(data)} octets) par {request.remote}')
    return web.json_response({'ok': True, 'name': target.stem, 'size': len(data)})


def create_app():
    app = web.Application()
    app.router.add_get('/',                          http_index)
    app.router.add_get('/ws',                        WB.browser_ws_handler)
    app.router.add_get('/api/archives/list',         api_archives_list)
    app.router.add_get('/api/archives/vdt/{name}',   api_archives_vdt)
    app.router.add_post('/api/archives/upload',      api_archives_upload)
    return app


# ------------------------------------------------------------------ demarrage

async def main(cfg):
    srv = cfg['server']
    log('CFG', f'{len(cfg["devices"])} appareils | {len(cfg["sensors"])} capteurs | '
               f'{len(cfg["alerts"])} alertes')
    log('CFG', f'{len(cfg["scenes"])} scenes | {len(cfg["scripts"])} scripts | '
               f'{len(list(cfg["archives"]["folder"].glob("*.vdt")))} pages .vdt | '
               f'langue {cfg["display"]["language"]}')
    log('CFG', 'code d\'acces : ' + ('actif' if cfg['security']['access_code'] else 'aucun'))
    log('SRV', f'3615 MAISON -> ws://0.0.0.0:{srv["vt_port"]}')
    log('SRV', f'Navigateur  -> http://0.0.0.0:{srv["http_port"]}')
    log('SRV', f'HA          -> {cfg["ha"]["url"]}')

    # Session HTTP unique pour tous les appels a Home Assistant
    http = aiohttp.ClientSession()
    hub.setup(cfg, http)

    runner = web.AppRunner(create_app())
    await runner.setup()
    await web.TCPSite(runner, '0.0.0.0', srv['http_port']).start()

    try:
        async with websockets.serve(WM.vt_ws_handler, '0.0.0.0', srv['vt_port']):
            await asyncio.gather(
                ha_live.run(http, cfg['ha']['url'], cfg['ha']['token'], hub.notify),
                hub.refresh_loop(cfg['display']['refresh_auto']),
                hub.clock_loop(),
            )
    finally:
        await http.close()
        await runner.cleanup()


if __name__ == '__main__':
    config = settings.load(Path(os.environ.get('MINITEL_CONFIG', BASE / 'config.yaml')))
    if not config['ha']['url'] or not config['ha']['token']:
        log('ERR', 'config.yaml : homeassistant.url et .token sont obligatoires')
        raise SystemExit(1)
    configure(config)
    try:
        asyncio.run(main(config))
    except KeyboardInterrupt:
        log('SRV', 'arret demande')
