"""Etat partage entre toutes les sessions (Minitel et navigateur).

- registre des sessions ouvertes ;
- diffusion des changements d'etat HA (temps reel ou REST periodique) ;
- alertes de la ligne 0 ;
- code d'acces : essais limites par adresse IP, jetons pour l'API HTTP.
"""
import asyncio
import hmac
import secrets
import time

import alerts
import ha_client as HA
import pagevideo as P
from utils import log

cfg  = None            # configuration normalisee (settings.normalize)
http = None            # aiohttp.ClientSession partagee

SESSIONS = set()
ALERT    = {'text': ''}
TOKENS   = {}          # jeton -> expiration (monotonic)
FAILS    = {}          # ip -> {'count', 'since', 'until'}

DEBOUNCE      = 0.3
TOKEN_TTL     = 12 * 3600
MAX_FAILS     = 5      # essais par IP ...
FAIL_WINDOW   = 600    # ... sur 10 minutes
LOCK_SECONDS  = 300

_pending = {'ids': set(), 'all': False, 'task': None}


def setup(cfg_, http_):
    global cfg, http
    cfg, http = cfg_, http_
    alerts.configure(cfg['alerts'])


def register(session):
    SESSIONS.add(session)


def unregister(session):
    SESSIONS.discard(session)


def watched_entities():
    ids = {d['entity'] for d in cfg['devices']} | {s['entity'] for s in cfg['sensors']}
    return ids | alerts.entities()


# ------------------------------------------------------------------ etats HA

def notify(ids):
    """Appele par ha_live (ou la boucle REST) : regroupe les changements
    proches et les traite une seule fois."""
    if ids is None:
        _pending['all'] = True
    else:
        ids = set(ids) & watched_entities()
        if not ids:
            return
        _pending['ids'] |= ids
    if _pending['task'] is None or _pending['task'].done():
        _pending['task'] = asyncio.ensure_future(_flush())


async def _flush():
    await asyncio.sleep(DEBOUNCE)
    _pending['ids'], _pending['all'] = set(), False
    await update_alerts()
    for s in list(SESSIONS):
        try:
            await s.on_states_changed()
        except Exception as e:
            log('ERR', f'mise a jour {s.remote}: {type(e).__name__}: {e}')


async def update_alerts():
    text = P.alerts_text(alerts.evaluate(HA._STATES['data']))
    if text == ALERT['text']:
        return
    ALERT['text'] = text
    if text:
        log('WARN', f'alerte: {text}')
    for s in list(SESSIONS):
        try:
            await s.show_status()
        except Exception:
            pass


async def refresh_loop(delay):
    """Hors temps reel : relit les etats toutes les `delay` secondes."""
    while True:
        await asyncio.sleep(delay)
        if HA.LIVE['connected'] or not (SESSIONS or alerts.ALERTS):
            continue
        HA.invalidate_cache()
        await HA.fetch_all_states(http, force=True)
        notify(None)


async def clock_loop():
    while True:
        await asyncio.sleep(60 - time.localtime().tm_sec)
        for s in list(SESSIONS):
            try:
                await s.clock_tick()
            except Exception:
                pass


# ------------------------------------------------------------------ acces

def code_required():
    return bool(cfg['security']['access_code'])


def check_code(code):
    return hmac.compare_digest(str(code).encode(), cfg['security']['access_code'].encode())


def login_allowed(ip):
    """(autorise, minutes restantes de blocage)."""
    f = FAILS.get(ip)
    if f and f['until'] > time.monotonic():
        return False, max(1, round((f['until'] - time.monotonic()) / 60))
    return True, 0


def login_failed(ip):
    now = time.monotonic()
    f = FAILS.get(ip)
    if not f or now - f['since'] > FAIL_WINDOW:
        f = FAILS[ip] = {'count': 0, 'since': now, 'until': 0}
    f['count'] += 1
    if f['count'] >= MAX_FAILS:
        f['until'] = now + LOCK_SECONDS
        log('WARN', f'code d\'acces : {ip} bloque {LOCK_SECONDS // 60} min')


def login_ok(ip):
    FAILS.pop(ip, None)


def issue_token():
    now = time.monotonic()
    for tok, exp in list(TOKENS.items()):
        if exp < now:
            del TOKENS[tok]
    tok = secrets.token_urlsafe(24)
    TOKENS[tok] = now + TOKEN_TTL
    return tok


def token_valid(tok):
    exp = TOKENS.get(tok or '')
    return bool(exp and exp > time.monotonic())
