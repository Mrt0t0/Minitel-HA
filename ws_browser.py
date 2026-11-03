"""Transport navigateur : l'emulateur Minitel de la page web, sur /ws.

Trames binaires dans les deux sens : touches Minitel vers le serveur,
pages Videotex vers l'emulateur. Une trame texte JSON transmet le jeton
d'acces a l'API HTTP apres saisie du code.
"""
import aiohttp
from aiohttp import web

import hub
from session import Session
from utils import log

INGRESS_PROXY = '172.30.32.2'   # adresse du proxy ingress du Supervisor HA


def is_trusted(request):
    """Requete passee par l'ingress HA : l'utilisateur est deja authentifie."""
    return bool(hub.cfg['server']['trust_ingress']
                and request.remote == INGRESS_PROXY
                and request.headers.get('X-Ingress-Path'))


class _Transport:
    def __init__(self, ws):
        self.ws = ws

    async def send(self, data):
        await self.ws.send_bytes(data)

    async def send_text(self, text):
        await self.ws.send_str(text)

    async def close(self):
        await self.ws.close()


async def _incoming(ws):
    async for msg in ws:
        if msg.type == aiohttp.WSMsgType.BINARY:
            yield msg.data
        elif msg.type != aiohttp.WSMsgType.TEXT:
            break


async def browser_ws_handler(request):
    ws = web.WebSocketResponse(heartbeat=30, max_msg_size=4096)
    await ws.prepare(request)
    try:
        await Session(_Transport(ws), request.remote or '?',
                      trusted=is_trusted(request)).run(_incoming(ws))
    except (ConnectionResetError, aiohttp.ClientConnectionResetError):
        pass
    except Exception as e:
        log('ERR', f'session navigateur {request.remote}: {type(e).__name__}: {e}')
    return ws
