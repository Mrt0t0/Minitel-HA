import asyncio, aiohttp, json as _json
from collections import deque
from datetime    import datetime
from utils       import log

HA_URL  = ""
HDRS    = {}
TIMEOUT = aiohttp.ClientTimeout(total=10)
JOURNAL = deque(maxlen=50)

def configure(url, token):
    global HA_URL, HDRS
    HA_URL = url
    HDRS   = {'Authorization': f'Bearer {token}', 'Content-Type': 'application/json'}

def journal_add(name, entity, action, ok):
    JOURNAL.append({'ts': datetime.now().strftime('%H:%M'),
                    'name': name, 'entity': entity, 'action': action, 'ok': ok})

async def get_state(session, entity):
    if not entity:
        return '?', {}
    try:
        async with session.get(f'{HA_URL}/api/states/{entity}',
                               headers=HDRS, timeout=TIMEOUT) as r:
            if r.status == 200:
                d = await r.json()
                return d.get('state', '?'), d.get('attributes', {})
            log('WARN', f'get_state {entity} HTTP {r.status}')
    except Exception as e:
        log('WARN', f'get_state {entity}: {e}')
    return '?', {}

async def toggle(session, entity, name=""):
    domain = entity.split('.')[0]
    try:
        async with session.post(f'{HA_URL}/api/services/{domain}/toggle',
                                headers=HDRS, json={'entity_id': entity},
                                timeout=TIMEOUT) as r:
            ok = r.status in (200, 201)
            journal_add(name or entity, entity, 'toggle', ok)
            log('HA', f'toggle {entity} → {"OK" if ok else f"ERR {r.status}"}')
            return ok
    except Exception as e:
        log('ERR', f'toggle {entity}: {e}')
        journal_add(name or entity, entity, 'toggle', False)
    return False

async def activate(session, entity, name=""):
    domain = entity.split('.')[0]
    try:
        async with session.post(f'{HA_URL}/api/services/{domain}/turn_on',
                                headers=HDRS, json={'entity_id': entity},
                                timeout=TIMEOUT) as r:
            ok = r.status in (200, 201)
            journal_add(name or entity, entity, 'activate', ok)
            log('HA', f'activate {entity} → {"OK" if ok else f"ERR {r.status}"}')
            return ok
    except Exception as e:
        log('ERR', f'activate {entity}: {e}')
        journal_add(name or entity, entity, 'activate', False)
    return False

async def fetch_data(session, devices_cfg, sensors_cfg):
    devices, sensors = [], []
    for i, d in enumerate(devices_cfg, 1):
        state, _ = await get_state(session, d['entity'])
        devices.append({'num': i, 'name': d['name'], 'entity': d['entity'],
                        'area': d.get('area', 'Autres'), 'state': state})
    for s in sensors_cfg:
        state, _ = await get_state(session, s['entity'])
        sensors.append({'name': s['name'], 'area': s.get('area', '?'),
                        'unit': s.get('unit', ''), 'state': state})
    stats = {'on':    sum(1 for d in devices if d['state'] == 'on'),
             'off':   sum(1 for d in devices if d['state'] == 'off'),
             'total': len(devices)}
    return devices, sensors, stats

async def fetch_meteo(session, meteo_cfg):
    ms = meteo_cfg.get('sensors', {})
    t_ext, _ = await get_state(session, ms.get('temperature_ext', ''))
    h_ext, _ = await get_state(session, ms.get('humidity_ext', ''))
    ext = {'temp': t_ext if t_ext != '?' else None,
           'hum':  h_ext if h_ext != '?' else None}
    rooms = []
    for room_name, entities in ms.get('rooms', {}).items():
        rt, _ = await get_state(session, entities.get('temp', ''))
        rh, _ = await get_state(session, entities.get('hum', ''))
        rooms.append({'name': room_name,
                      'temp': rt if rt != '?' else None,
                      'hum':  rh if rh != '?' else None})
    forecast = await fetch_forecast(session, meteo_cfg.get('weather_entity', ''))
    return {'ext': ext, 'rooms': rooms, 'forecast': forecast}

_CONDITIONS = {
    'sunny': 'SOLEIL', 'clear-night': 'NUIT CL.',
    'partlycloudy': 'MI-NUAG.', 'cloudy': 'COUVERT',
    'fog': 'BROUILL.', 'hail': 'GRELE', 'lightning': 'ORAGE',
    'lightning-rainy': 'ORAGE/P.', 'pouring': 'PLUIE F.',
    'rainy': 'PLUIE', 'snowy': 'NEIGE', 'snowy-rainy': 'NEIGE/P.',
    'windy': 'VENTEUX', 'windy-variant': 'T.VENTE', 'exceptional': 'EXCEPT.',
}

def condition_label(cond):
    return _CONDITIONS.get(cond, (cond[:8].upper() + '        ')[:8])

_JOURS_FR = ['lun','mar','mer','jeu','ven','sam','dim']

def _fmt_forecasts(raw, rtype='daily'):
    """
    Formatte les entrées brutes HA en dicts simplifiés.
    rtype='daily'  → label = jour ex: "lun 07"
    rtype='hourly' → label = heure ex: "10h"
    FIX Sprint 10 : le type est maintenant passé explicitement pour éviter
    que tous les labels affichent la même heure (ex: "10h" × 4).
    """
    result = []
    for entry in raw[:5]:
        dt_str = entry.get('datetime', '')
        try:
            dt = datetime.fromisoformat(dt_str.replace('Z', '+00:00'))
            if rtype == 'hourly':
                label = dt.strftime('%Hh')
            else:
                label = _JOURS_FR[dt.weekday()] + dt.strftime(' %d')
        except Exception:
            label = dt_str[:5] or '?'

        precip = entry.get('precipitation_probability')
        precip_str = f"{int(precip)}%" if precip is not None else "--"

        result.append({
            'label':  label,
            'cond':   condition_label(entry.get('condition', '?')),
            'temp':   entry.get('temperature'),
            'tlow':   entry.get('templow'),
            'precip': precip_str,
        })
    return result

def _extract_fc(data, entity):
    """
    Extrait forecast[] depuis la réponse HA.
    FIX Sprint 10 : cherche d'abord dans service_response (HA 2024.4+),
    puis directement dans data (anciennes versions).
    Structure HA 2024.4+ : {"service_response": {"weather.xxx": {"forecast": [...]}}}
    """
    raw_fc = []
    if isinstance(data, dict):
        svc = data.get('service_response', {})
        if isinstance(svc, dict):
            nested = svc.get(entity, {})
            if isinstance(nested, dict):
                raw_fc = nested.get('forecast', [])
            if not raw_fc:
                for v in svc.values():
                    if isinstance(v, dict) and 'forecast' in v:
                        raw_fc = v['forecast']; break

        if not raw_fc:
            nested = data.get(entity, {})
            if isinstance(nested, dict):
                raw_fc = nested.get('forecast', [])
        if not raw_fc:
            for v in data.values():
                if isinstance(v, dict) and 'forecast' in v:
                    raw_fc = v['forecast']; break
    elif isinstance(data, list):
        for item in data:
            if isinstance(item, dict):
                svc = item.get('service_response', {})
                if isinstance(svc, dict):
                    nested = svc.get(entity, {})
                    if isinstance(nested, dict) and 'forecast' in nested:
                        raw_fc = nested['forecast']; break
                if 'forecast' in item:
                    raw_fc = item['forecast']; break
    return raw_fc

async def fetch_forecast(session, weather_entity):
    if not weather_entity:
        return []

    for rtype in ('daily', 'hourly'):
        try:
            async with session.post(
                    f'{HA_URL}/api/services/weather/get_forecasts',
                    params={'return_response': 'true'},
                    headers=HDRS,
                    json={'entity_id': weather_entity, 'type': rtype},
                    timeout=aiohttp.ClientTimeout(total=12)) as r:
                raw_text = await r.text()
                log('HA', f'forecast/{rtype} HTTP {r.status} | {len(raw_text)} oct')
                if r.status == 200:
                    data  = _json.loads(raw_text)
                    raw_fc = _extract_fc(data, weather_entity)
                    if raw_fc:
                        log('HA', f'forecast OK: {len(raw_fc)} entrées ({rtype})')
                        return _fmt_forecasts(raw_fc, rtype)
                    log('WARN', f'forecast/{rtype}: vide')
        except Exception as e:
            log('WARN', f'forecast/{rtype}: {e}')

    try:
        _, attrs = await get_state(session, weather_entity)
        raw_fc = attrs.get('forecast', [])
        if raw_fc:
            log('HA', f'forecast OK: {len(raw_fc)} entrées (attribut)')
            return _fmt_forecasts(raw_fc, 'daily')
    except Exception as e:
        log('ERR', f'forecast attribut {weather_entity}: {e}')

    log('WARN', f'forecast: aucune donnée pour {weather_entity}')
    return []

async def converse(session, text, agent_id="home_assistant",
                   language="fr", conversation_id=None):
    async def _call(payload):
        async with session.post(f'{HA_URL}/api/conversation/process',
                                headers=HDRS, json=payload,
                                timeout=aiohttp.ClientTimeout(total=15)) as r:
            raw = await r.text()
            log('HA', f'converse HTTP {r.status}')
            return r.status, raw

    def _parse(raw):
        try:
            d = _json.loads(raw)
            speech  = (d.get('response', {}).get('speech', {})
                        .get('plain', {}).get('speech', '…'))
            conv_id = d.get('conversation_id')
            rtype   = d.get('response', {}).get('response_type', 'error')
            return speech, conv_id, rtype
        except Exception:
            return 'Erreur décodage', None, 'error'

    payload = {'text': text, 'language': language}
    if agent_id and agent_id not in ('home_assistant', 'homeassistant', ''):
        payload['agent_id'] = agent_id
    if conversation_id:
        payload['conversation_id'] = conversation_id

    reset_conv = False
    try:
        status, raw = await _call(payload)
        if status == 400 and conversation_id:
            payload.pop('conversation_id', None)
            status, raw = await _call(payload)
            reset_conv = True
        if status != 200:
            return {'speech': f'Erreur HTTP {status}', 'conv_id': None,
                    'ok': False, 'type': 'error', 'reset_conv': reset_conv}
        speech, conv_id, rtype = _parse(raw)
        return {'speech': speech, 'conv_id': conv_id, 'ok': rtype != 'error',
                'type': rtype, 'reset_conv': reset_conv}
    except asyncio.TimeoutError:
        return {'speech': 'Délai dépassé', 'conv_id': None,
                'ok': False, 'type': 'error', 'reset_conv': False}
    except Exception as e:
        return {'speech': str(e), 'conv_id': None,
                'ok': False, 'type': 'error', 'reset_conv': False}
