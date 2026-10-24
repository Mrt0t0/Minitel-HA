#!/usr/bin/env python3
"""Faux Home Assistant pour developper et tester sans installation HA.

    python tests/fake_ha.py [port]       (token : "test")

REST (/api/states, /api/services, /api/history, /api/template,
/api/conversation/process) et WebSocket (/api/websocket : auth, get_states,
subscribe_events). POST /test/set {"entity_id", "state"} simule un
changement exterieur, diffuse en temps reel.
"""
import json
import math
import sys
from datetime import datetime, timedelta, timezone

from aiohttp import web

TOKEN = 'test'


def _st(eid, state, **attrs):
    return {'entity_id': eid, 'state': state,
            'attributes': {'friendly_name': attrs.pop('name', eid), **attrs},
            'last_changed': datetime.now(timezone.utc).isoformat()}


STATES = {s['entity_id']: s for s in [
    _st('light.salon', 'on', name='Lampe salon', brightness=153),
    _st('light.cuisine', 'off', name='Led cuisine'),
    _st('switch.humidificateur', 'off', name='Humidificateur'),
    _st('cover.volet_salon', 'open', name='Volet salon', current_position=60),
    _st('climate.salon', 'heat', name='Thermostat', temperature=20.5, target_temp_step=0.5,
        current_temperature=19.8),
    _st('lock.porte', 'locked', name='Porte'),
    _st('media_player.radio', 'playing', name='Radio'),
    _st('sensor.salon_temperature', '21.4', name='Temperature salon',
        device_class='temperature', unit_of_measurement='°C'),
    _st('sensor.salon_humidite', '47', name='Humidite salon',
        device_class='humidity', unit_of_measurement='%'),
    _st('binary_sensor.porte_entree', 'off', name="Porte d'entree"),
    _st('weather.maison', 'sunny', name='Meteo', temperature=12.3),
]}
AREAS = {'light.salon': 'Salon', 'cover.volet_salon': 'Salon', 'climate.salon': 'Salon',
         'sensor.salon_temperature': 'Salon', 'sensor.salon_humidite': 'Salon',
         'light.cuisine': 'Cuisine', 'lock.porte': 'Entree'}
CLIENTS = set()


def _auth(request):
    if request.headers.get('Authorization') != f'Bearer {TOKEN}':
        raise web.HTTPUnauthorized()


async def _broadcast(eid):
    for ws, sub_id in list(CLIENTS):
        try:
            await ws.send_json({'id': sub_id, 'type': 'event', 'event': {
                'event_type': 'state_changed',
                'data': {'entity_id': eid, 'new_state': STATES.get(eid)}}})
        except Exception:
            CLIENTS.discard((ws, sub_id))


def _set(eid, state, **attrs):
    cur = STATES.setdefault(eid, _st(eid, state))
    cur['state'] = state
    cur['attributes'].update(attrs)
    cur['last_changed'] = datetime.now(timezone.utc).isoformat()


def apply_service(domain, service, data):
    eid = data.get('entity_id', '')
    cur = STATES.get(eid)
    if service == 'toggle' and cur:
        flip = {'on': 'off', 'off': 'on', 'open': 'closed', 'closed': 'open'}
        _set(eid, flip.get(cur['state'], 'on'))
    elif service in ('turn_on', 'turn_off') and cur:
        _set(eid, 'on' if service == 'turn_on' else 'off')
        if domain == 'climate' and service == 'turn_on':
            _set(eid, 'heat')
        if 'brightness_step_pct' in data:
            b = cur['attributes'].get('brightness') or 0
            _set(eid, 'on', brightness=max(0, min(255, round(b + 2.55 * data['brightness_step_pct']))))
    elif service in ('lock', 'unlock') and cur:
        _set(eid, service + 'ed')
    elif service == 'set_temperature' and cur:
        _set(eid, cur['state'], temperature=data['temperature'])
    elif service == 'set_cover_position' and cur:
        _set(eid, 'open' if data['position'] else 'closed', current_position=data['position'])
    return eid if cur else None


async def states(request):
    _auth(request)
    return web.json_response(list(STATES.values()))


async def services(request):
    _auth(request)
    d, s = request.match_info['domain'], request.match_info['service']
    data = await request.json()
    if d == 'weather' and s == 'get_forecasts':
        now = datetime.now(timezone.utc)
        return web.json_response({'service_response': {data['entity_id']: {'forecast': [
            {'datetime': (now + timedelta(days=i)).isoformat(), 'condition': c,
             'temperature': 14 + i, 'templow': 6 + i, 'precipitation': p}
            for i, (c, p) in enumerate([('sunny', 0), ('rainy', 3.2), ('cloudy', 0.4),
                                        ('partlycloudy', 0)])]}}})
    eid = apply_service(d, s, data)
    if eid:
        await _broadcast(eid)
    return web.json_response([])


async def history(request):
    _auth(request)
    eid = request.query.get('filter_entity_id', '')
    try:
        base = float(STATES[eid]['state'])
    except (KeyError, ValueError):
        return web.json_response([[]])
    now = datetime.now(timezone.utc)
    pts = [{'state': str(round(base + 3 * math.sin(k / 9), 1)),
            'last_changed': (now - timedelta(minutes=15 * k)).isoformat()} for k in range(96, -1, -1)]
    return web.json_response([pts])


async def template(request):
    _auth(request)
    body = await request.json()
    ids = (body.get('variables') or {}).get('ids')
    if ids is not None:
        return web.Response(text='\n'.join(f'{e}|{AREAS.get(e, "None")}' for e in ids))
    return web.Response(text='None')


async def conversation(request):
    _auth(request)
    body = await request.json()
    return web.json_response({'conversation_id': 'conv-1', 'response': {'speech': {'plain': {
        'speech': f'Bien reçu : « {body["text"]} ». Il fait 21 °C au salon.'}}}})


async def test_set(request):
    body = await request.json()
    _set(body['entity_id'], body['state'])
    await _broadcast(body['entity_id'])
    return web.json_response({'ok': True})


async def websocket(request):
    ws = web.WebSocketResponse()
    await ws.prepare(request)
    await ws.send_json({'type': 'auth_required', 'ha_version': '2026.10.0'})
    msg = await ws.receive_json()
    if msg.get('access_token') != TOKEN:
        await ws.send_json({'type': 'auth_invalid', 'message': 'Invalid access token'})
        await ws.close()
        return ws
    await ws.send_json({'type': 'auth_ok', 'ha_version': '2026.10.0'})
    async for m in ws:
        d = json.loads(m.data)
        if d['type'] == 'get_states':
            await ws.send_json({'id': d['id'], 'type': 'result', 'success': True,
                                'result': list(STATES.values())})
        elif d['type'] == 'subscribe_events':
            CLIENTS.add((ws, d['id']))
            await ws.send_json({'id': d['id'], 'type': 'result', 'success': True, 'result': None})
    CLIENTS.difference_update({c for c in CLIENTS if c[0] is ws})
    return ws


def create_app():
    app = web.Application()
    app.router.add_get('/api/states', states)
    app.router.add_post('/api/services/{domain}/{service}', services)
    app.router.add_get('/api/history/period/{start}', history)
    app.router.add_post('/api/template', template)
    app.router.add_post('/api/conversation/process', conversation)
    app.router.add_get('/api/websocket', websocket)
    app.router.add_post('/test/set', test_set)
    return app


if __name__ == '__main__':
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8123
    web.run_app(create_app(), port=port)
