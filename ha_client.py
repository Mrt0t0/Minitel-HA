"""Acces a Home Assistant : etats, services, assistant, meteo, historique.

Les etats sont tenus a jour en continu par ha_live (WebSocket HA). Tant que
le WebSocket n'est pas connecte, ils sont lus par GET /api/states avec un
cache court.
"""
import time
from datetime import datetime, timedelta, timezone

import aiohttp

import devices
import journal
from i18n import t
from utils import log

HA_URL  = ''
HA_TOK  = ''
HDRS    = {}
TIMEOUT = aiohttp.ClientTimeout(total=10)

_STATES    = {'ts': 0.0, 'data': {}}
_CACHE_TTL = 2.0
LIVE       = {'connected': False}


def configure(url, token):
    global HA_URL, HA_TOK, HDRS
    HA_URL = url.rstrip('/')
    HA_TOK = token
    HDRS   = {'Authorization': f'Bearer {token}',
              'Content-Type':  'application/json'}


def invalidate_cache():
    _STATES['ts'] = 0.0


def replace_states(states):
    """Remplace tout l'index (reponse get_states du WebSocket)."""
    _STATES['data'] = {e['entity_id']: e for e in states}
    _STATES['ts']   = time.monotonic()


def apply_state(entity_id, new_state):
    """Applique un evenement state_changed."""
    if new_state is None:
        _STATES['data'].pop(entity_id, None)
    else:
        _STATES['data'][entity_id] = new_state


async def fetch_all_states(session, force=False):
    """Index entity_id -> etat. Un seul GET /api/states hors WebSocket."""
    if LIVE['connected'] and _STATES['data']:
        return _STATES['data']
    now = time.monotonic()
    if not force and (now - _STATES['ts']) < _CACHE_TTL and _STATES['data']:
        return _STATES['data']
    try:
        async with session.get(f'{HA_URL}/api/states',
                               headers=HDRS, timeout=TIMEOUT) as r:
            if r.status != 200:
                log('ERR', f'/api/states HTTP {r.status}')
                return _STATES['data']
            raw = await r.json()
    except Exception as e:
        log('ERR', f'fetch_all_states: {e}')
        return _STATES['data']
    replace_states(raw)
    return _STATES['data']


def _state_of(index, entity):
    e = index.get(entity) if entity else None
    return e.get('state', '?') if e else '?'


async def call_service(session, act, name=''):
    """Appelle un service HA. act = {domain, service, data} (devices.py)."""
    entity = act['data'].get('entity_id', '')
    label  = f'{act["domain"]}.{act["service"]}'
    try:
        async with session.post(
                f'{HA_URL}/api/services/{act["domain"]}/{act["service"]}',
                headers=HDRS, json=act['data'], timeout=TIMEOUT) as r:
            ok = r.status in (200, 201)
    except Exception as e:
        log('ERR', f'{label} {entity}: {e}')
        ok = False
    journal.add(name or entity, entity, act['service'], ok)
    invalidate_cache()
    log('HA', f'{label} {entity} -> {"OK" if ok else "ERR"}')
    return ok


async def activate(session, entity, name=''):
    """Active une scene / un script."""
    return await call_service(session, {'domain': entity.split('.')[0],
                                        'service': 'turn_on',
                                        'data': {'entity_id': entity}}, name)


async def converse(session, text, agent_id='conversation.home_assistant',
                   language='fr', conversation_id=None):
    payload = {'text': text, 'language': language, 'agent_id': agent_id}
    if conversation_id:
        payload['conversation_id'] = conversation_id
    try:
        async with session.post(f'{HA_URL}/api/conversation/process',
                                headers=HDRS, json=payload,
                                timeout=aiohttp.ClientTimeout(total=30)) as r:
            if r.status != 200:
                if conversation_id and r.status == 400:
                    return {'ok': False, 'speech': t('assist.expired'),
                            'reset_conv': True}
                return {'ok': False, 'speech': t('assist.error', s=r.status)}
            d = await r.json()
    except Exception as e:
        log('ERR', f'converse: {e}')
        return {'ok': False, 'speech': t('assist.unreachable')}
    resp   = d.get('response', {})
    speech = resp.get('speech', {}).get('plain', {}).get('speech', '')
    invalidate_cache()
    return {'ok': True, 'speech': speech or t('assist.none'),
            'conv_id': d.get('conversation_id')}


def _entry(index, cfg, i):
    e = index.get(cfg['entity']) or {}
    return {
        'num':    i,
        'name':   cfg.get('name', cfg['entity']),
        'entity': cfg['entity'],
        'area':   cfg.get('area', 'Autres'),
        'unit':   cfg.get('unit', ''),
        'state':  e.get('state', '?'),
        'attrs':  e.get('attributes', {}),
    }


async def fetch_data(session, devices_cfg, sensors_cfg):
    index = await fetch_all_states(session)
    devs  = [_entry(index, d, i) for i, d in enumerate(devices_cfg, 1)]
    sens  = [_entry(index, s, i) for i, s in enumerate(sensors_cfg, 1)]
    on    = sum(1 for d in devs if devices.is_active(d))
    stats = {'on': on, 'off': len(devs) - on, 'total': len(devs)}
    return devs, sens, stats


def condition_label(cond):
    return t('cond').get(cond, str(cond)[:10])


def _fmt_forecasts(raw, rtype='daily'):
    out = []
    for f in raw[:5]:
        dt_str = str(f.get('datetime', ''))
        try:
            dt = datetime.fromisoformat(dt_str.replace('Z', '+00:00'))
            label = (dt.strftime('%Hh') if rtype == 'hourly'
                     else t('days_short')[dt.weekday()] + dt.strftime(' %d'))
        except Exception:
            label = dt_str[:5] or '?'
        precip = f.get('precipitation')
        out.append({
            'label':  label,
            'cond':   condition_label(f.get('condition', '?')),
            'temp':   f.get('temperature'),
            'tlow':   f.get('templow'),
            'precip': f'{precip}mm' if precip not in (None, 0) else '--',
        })
    return out


async def fetch_meteo(session, meteo_cfg):
    index = await fetch_all_states(session)
    ms    = meteo_cfg.get('sensors') or {}

    def val(entity):
        v = _state_of(index, entity)
        return None if v in devices.UNAVAILABLE else v

    ext = {'temp': val(ms.get('temperature_ext', '')),
           'hum':  val(ms.get('humidity_ext', ''))}
    rooms = [{'name': room, 'temp': val(ent.get('temp', '')), 'hum': val(ent.get('hum', ''))}
             for room, ent in (ms.get('rooms') or {}).items()]

    forecast = []
    went = meteo_cfg.get('weather_entity')
    if went:
        for rtype in ('daily', 'hourly'):
            try:
                async with session.post(
                        f'{HA_URL}/api/services/weather/get_forecasts'
                        f'?return_response',
                        headers=HDRS,
                        json={'entity_id': went, 'type': rtype},
                        timeout=TIMEOUT) as r:
                    if r.status != 200:
                        continue
                    d = await r.json()
            except Exception as e:
                log('ERR', f'forecast {rtype}: {e}')
                continue
            # HA 2024.4+ renvoie les donnees sous service_response
            body = d.get('service_response', d) if isinstance(d, dict) else {}
            ent  = body.get(went, {}) if isinstance(body, dict) else {}
            raw  = ent.get('forecast', []) if isinstance(ent, dict) else []
            if raw:
                forecast = _fmt_forecasts(raw, rtype)
                break
        attrs = (index.get(went) or {}).get('attributes', {})
        if not forecast and attrs.get('forecast'):
            forecast = _fmt_forecasts(attrs['forecast'], 'daily')
        if ext['temp'] is None and attrs.get('temperature') is not None:
            ext['temp'] = attrs['temperature']

    return {'ext': ext, 'rooms': rooms, 'forecast': forecast}


async def fetch_history(session, entity, hours=24):
    """Points (datetime UTC, valeur) numeriques des `hours` dernieres heures."""
    start = datetime.now(timezone.utc) - timedelta(hours=hours)
    url = (f'{HA_URL}/api/history/period/{start.strftime("%Y-%m-%dT%H:%M:%S")}+00:00'
           f'?filter_entity_id={entity}&minimal_response&no_attributes')
    try:
        async with session.get(url, headers=HDRS,
                               timeout=aiohttp.ClientTimeout(total=20)) as r:
            if r.status != 200:
                log('ERR', f'history {entity}: HTTP {r.status}')
                return []
            data = await r.json()
    except Exception as e:
        log('ERR', f'history {entity}: {e}')
        return []
    points = []
    for e in (data[0] if data else []):
        try:
            v  = float(e['state'])
            dt = datetime.fromisoformat(str(e.get('last_changed', '')).replace('Z', '+00:00'))
        except (KeyError, TypeError, ValueError):
            continue
        points.append((dt, v))
    return points
