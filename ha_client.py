import time
import aiohttp
from collections import deque
from datetime import datetime
from utils import log

HA_URL  = ''
HA_TOK  = ''
HDRS    = {}
TIMEOUT = aiohttp.ClientTimeout(total=10)

JOURNAL = deque(maxlen=50)

_STATES_CACHE = {'ts': 0.0, 'data': {}}
_CACHE_TTL    = 2.0

_JOURS_FR = ['lun', 'mar', 'mer', 'jeu', 'ven', 'sam', 'dim']

_CONDITIONS = {
    'clear-night': 'Nuit clair', 'cloudy': 'Nuageux', 'fog': 'Brouillard',
    'hail': 'Grele', 'lightning': 'Orage', 'lightning-rainy': 'Orage pluie',
    'partlycloudy': 'Eclaircie', 'pouring': 'Averses', 'rainy': 'Pluie',
    'snowy': 'Neige', 'snowy-rainy': 'Neige pluie', 'sunny': 'Ensoleille',
    'windy': 'Venteux', 'windy-variant': 'Venteux', 'exceptional': 'Exception',
}


def configure(url, token):
    global HA_URL, HA_TOK, HDRS
    HA_URL = url.rstrip('/')
    HA_TOK = token
    HDRS   = {'Authorization': f'Bearer {token}',
              'Content-Type':  'application/json'}


def journal_add(name, entity, action, ok):
    JOURNAL.append({
        'ts':     datetime.now().strftime('%H:%M'),
        'name':   name, 'entity': entity,
        'action': action, 'ok': ok,
    })


def invalidate_cache():
    _STATES_CACHE['ts'] = 0.0


async def fetch_all_states(session, force=False):
    """Un seul GET /api/states pour toutes les entites, avec cache TTL court.
    Remplace N appels /api/states/<entity> par 1 seul."""
    now = time.monotonic()
    if not force and (now - _STATES_CACHE['ts']) < _CACHE_TTL and _STATES_CACHE['data']:
        return _STATES_CACHE['data']
    try:
        async with session.get(f'{HA_URL}/api/states',
                               headers=HDRS, timeout=TIMEOUT) as r:
            if r.status != 200:
                log('ERR', f'/api/states HTTP {r.status}')
                return _STATES_CACHE['data']
            raw = await r.json()
    except Exception as e:
        log('ERR', f'fetch_all_states: {e}')
        return _STATES_CACHE['data']
    index = {e['entity_id']: e for e in raw}
    _STATES_CACHE['ts']   = now
    _STATES_CACHE['data'] = index
    return index


def _state_of(index, entity):
    if not entity:
        return '?'
    e = index.get(entity)
    return e.get('state', '?') if e else '?'


async def get_state(session, entity):
    index = await fetch_all_states(session)
    e = index.get(entity)
    if not e:
        return '?', {}
    return e.get('state', '?'), e.get('attributes', {})


async def _call_service(session, domain, service, entity, name, action):
    try:
        async with session.post(
                f'{HA_URL}/api/services/{domain}/{service}',
                headers=HDRS, json={'entity_id': entity},
                timeout=TIMEOUT) as r:
            ok = r.status in (200, 201)
    except Exception as e:
        log('ERR', f'{service} {entity}: {e}')
        ok = False
    journal_add(name or entity, entity, action, ok)
    invalidate_cache()
    log('HA', f'{action} {entity} -> {"OK" if ok else "ERR"}')
    return ok


async def toggle(session, entity, name=''):
    return await _call_service(session, entity.split('.')[0],
                               'toggle', entity, name, 'toggle')


async def activate(session, entity, name=''):
    return await _call_service(session, entity.split('.')[0],
                               'turn_on', entity, name, 'activate')


async def converse(session, text, agent_id='home_assistant',
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
                    return {'ok': False, 'speech': 'Session expiree, reessayez.',
                            'reset_conv': True}
                return {'ok': False, 'speech': f'Erreur HA {r.status}'}
            d = await r.json()
    except Exception as e:
        log('ERR', f'converse: {e}')
        return {'ok': False, 'speech': 'Assistant injoignable'}
    resp   = d.get('response', {})
    speech = resp.get('speech', {}).get('plain', {}).get('speech', '')
    invalidate_cache()
    return {'ok': True, 'speech': speech or '(pas de reponse)',
            'conv_id': d.get('conversation_id')}


async def fetch_data(session, devices_cfg, sensors_cfg):
    index = await fetch_all_states(session)
    devices = [{
        'num':    i,
        'name':   d['name'],
        'entity': d['entity'],
        'area':   d.get('area', 'Autres'),
        'state':  _state_of(index, d['entity']),
    } for i, d in enumerate(devices_cfg, 1)]
    sensors = [{
        'name':  s['name'],
        'area':  s.get('area', '?'),
        'unit':  s.get('unit', ''),
        'state': _state_of(index, s['entity']),
    } for s in sensors_cfg]
    stats = {
        'on':    sum(1 for d in devices if d['state'] == 'on'),
        'off':   sum(1 for d in devices if d['state'] == 'off'),
        'total': len(devices),
    }
    return devices, sensors, stats


def condition_label(cond):
    return _CONDITIONS.get(cond, str(cond)[:10])


def _fmt_forecasts(raw, rtype='daily'):
    out = []
    for f in raw[:5]:
        dt_str = str(f.get('datetime', ''))
        try:
            dt = datetime.fromisoformat(dt_str.replace('Z', '+00:00'))
            label = (dt.strftime('%Hh') if rtype == 'hourly'
                     else _JOURS_FR[dt.weekday()] + dt.strftime(' %d'))
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
    ms    = meteo_cfg.get('sensors', {})

    t = _state_of(index, ms.get('temperature_ext', ''))
    h = _state_of(index, ms.get('humidity_ext', ''))
    ext = {'temp': t if t != '?' else None, 'hum': h if h != '?' else None}

    rooms = [{
        'name': room,
        'temp': (lambda v: v if v != '?' else None)(_state_of(index, ent.get('temp', ''))),
        'hum':  (lambda v: v if v != '?' else None)(_state_of(index, ent.get('hum', ''))),
    } for room, ent in ms.get('rooms', {}).items()]

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
        if not forecast:
            attrs = (index.get(went) or {}).get('attributes', {})
            raw   = attrs.get('forecast', [])
            if raw:
                forecast = _fmt_forecasts(raw, 'daily')
            if ext['temp'] is None:
                tmp = attrs.get('temperature')
                if tmp is not None:
                    ext['temp'] = tmp

    return {'ext': ext, 'rooms': rooms, 'forecast': forecast}
