"""Etats HA en temps reel via l'API WebSocket de Home Assistant.

Connexion, authentification, get_states puis abonnement a state_changed.
Chaque changement met a jour l'index de ha_client et appelle on_change
avec l'ensemble des entites modifiees (None = tout l'index a change).
Reconnexion automatique ; pendant une coupure, ha_client repasse en REST.
"""
import asyncio
import json

import aiohttp

import ha_client as HA
from utils import log


def ws_url(http_url):
    """URL du WebSocket HA a partir de l'URL REST.
    http://ha:8123 -> ws://ha:8123/api/websocket
    http://supervisor/core -> ws://supervisor/core/websocket (add-on)"""
    url = http_url.rstrip('/')
    if url.startswith('https://'):
        url = 'wss://' + url[len('https://'):]
    elif url.startswith('http://'):
        url = 'ws://' + url[len('http://'):]
    return url + ('/websocket' if url.endswith('/core') else '/api/websocket')


def handle_message(msg, on_change):
    """Traite un message HA deja decode. Renvoie True quand l'index initial
    (reponse a get_states, id 1) vient d'etre charge."""
    if msg.get('type') == 'result' and msg.get('id') == 1:
        if msg.get('success'):
            HA.replace_states(msg.get('result') or [])
            on_change(None)
            return True
        log('ERR', f'HA get_states: {msg.get("error")}')
    elif msg.get('type') == 'event':
        data = (msg.get('event') or {}).get('data') or {}
        eid = data.get('entity_id')
        if eid:
            HA.apply_state(eid, data.get('new_state'))
            on_change({eid})
    return False


async def _session(http, url, token, on_change):
    async with http.ws_connect(ws_url(url), heartbeat=30, max_msg_size=0) as ws:
        msg = await ws.receive_json(timeout=15)
        if msg.get('type') != 'auth_required':
            raise RuntimeError(f'reponse inattendue: {msg.get("type")}')
        await ws.send_json({'type': 'auth', 'access_token': token})
        msg = await ws.receive_json(timeout=15)
        if msg.get('type') != 'auth_ok':
            raise PermissionError('token refuse par Home Assistant')
        await ws.send_json({'id': 1, 'type': 'get_states'})
        await ws.send_json({'id': 2, 'type': 'subscribe_events',
                            'event_type': 'state_changed'})
        async for m in ws:
            if m.type != aiohttp.WSMsgType.TEXT:
                break
            if handle_message(json.loads(m.data), on_change):
                HA.LIVE['connected'] = True
                log('HA', 'temps reel actif (WebSocket HA)')


async def run(http, url, token, on_change):
    delay = 5
    while True:
        try:
            await _session(http, url, token, on_change)
            delay = 5
        except asyncio.CancelledError:
            raise
        except PermissionError as e:
            log('ERR', f'WebSocket HA: {e}')
            delay = 300
        except Exception as e:
            log('WARN', f'WebSocket HA indisponible ({type(e).__name__}: {e}) '
                        f'- mode REST, nouvel essai dans {delay}s')
        finally:
            if HA.LIVE['connected']:
                log('WARN', 'temps reel interrompu - retour au mode REST')
            HA.LIVE['connected'] = False
        await asyncio.sleep(delay)
        delay = min(delay * 2, 60) if delay < 300 else 300
