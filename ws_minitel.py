"""Transport Minitel : WebSocket du port 3615 (ESP32 / TelnetPro / Minimit)."""
import websockets

from session import Session
from utils import log


class _Transport:
    def __init__(self, ws):
        self.ws = ws

    async def send(self, data):
        await self.ws.send(data)

    async def send_text(self, text):
        """Le Minitel n'a pas de canal de controle (jeton reserve au navigateur)."""

    async def close(self):
        await self.ws.close()


async def _incoming(ws):
    async for raw in ws:
        yield raw if isinstance(raw, bytes) else raw.encode()


async def vt_ws_handler(ws):
    host = ws.remote_address[0] if ws.remote_address else '?'
    try:
        await Session(_Transport(ws), str(host)).run(_incoming(ws))
    except websockets.ConnectionClosed:
        pass
    except Exception as e:
        log('ERR', f'session Minitel {host}: {type(e).__name__}: {e}')
