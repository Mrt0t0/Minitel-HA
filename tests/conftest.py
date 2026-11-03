import asyncio
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import ha_client as HA  # noqa: E402
import hub  # noqa: E402
import i18n  # noqa: E402
import journal  # noqa: E402
import server  # noqa: E402
import session  # noqa: E402
import settings  # noqa: E402
from tests.vt import Screen  # noqa: E402

DEVICES = [
    # Pieces absentes de area_order et melangees : l'ordre d'affichage
    # doit rester celui des numeros
    {'entity': 'light.x1', 'name': 'Lampe X1', 'area': 'Bureau'},
    {'entity': 'switch.y1', 'name': 'Prise Y1', 'area': 'Garage'},
    {'entity': 'light.salon', 'name': 'Lampe salon', 'area': 'Salon'},
    {'entity': 'light.x2', 'name': 'Lampe X2', 'area': 'Bureau'},
    {'entity': 'lock.porte', 'name': 'Porte', 'area': 'Salon'},
    {'entity': 'cover.volet', 'name': 'Volet', 'area': 'Salon'},
    {'entity': 'climate.thermo', 'name': 'Thermostat', 'area': 'Salon'},
]
SENSORS = [
    {'entity': 'sensor.temp_salon', 'name': 'Température salon', 'area': 'Salon', 'unit': '°C'},
    {'entity': 'sensor.hum_salon', 'name': 'Humidité salon', 'area': 'Salon', 'unit': '%'},
]
STATES = {
    'light.x1': ('off', {}), 'switch.y1': ('on', {}),
    'light.salon': ('on', {'brightness': 128}), 'light.x2': ('off', {}),
    'lock.porte': ('locked', {}), 'cover.volet': ('open', {'current_position': 40}),
    'climate.thermo': ('heat', {'temperature': 20, 'target_temp_step': 0.5}),
    'sensor.temp_salon': ('21.46', {}), 'sensor.hum_salon': ('48', {}),
    'binary_sensor.porte_entree': ('off', {}),
}


def make_states(states=STATES):
    return [{'entity_id': e, 'state': s, 'attributes': dict(a)} for e, (s, a) in states.items()]


class FakeTransport:
    def __init__(self):
        self.sent, self.texts, self.closed = [], [], False
        self.screen = Screen()

    async def send(self, data):
        self.sent.append(data)
        self.screen.feed(data)

    async def send_text(self, text):
        self.texts.append(text)

    async def close(self):
        self.closed = True


def raw_config(tmp_path, **extra):
    raw = {
        'homeassistant': {'url': 'http://ha.test:8123', 'token': 'x'},
        'display': {'splash_seconds': 0, 'page_size': 9},
        'area_order': ['Salon'],
        'devices': DEVICES, 'sensors': SENSORS,
        'scenes': [{'name': 'Cinéma', 'entity': 'scene.cinema'}],
        'scripts': [{'name': 'Alarme OFF', 'entity': 'script.alarme_off'}],
        'quick_off': {'entity': 'scene.tout_eteindre', 'name': 'Tout eteindre', 'confirm': True},
        'archives': {'folder': str(tmp_path / 'archives'), 'auto_rotate': 0},
        'journal': {'file': str(tmp_path / 'journal.json')},
        'alerts': [{'entity': 'binary_sensor.porte_entree', 'state': True,
                    'message': "Porte d'entrée ouverte"}],
        'assistant': {'agents': [{'id': 'conversation.a', 'name': 'Agent A'},
                                 {'id': 'conversation.b', 'name': 'Agent B'}]},
    }
    for key, val in extra.items():
        raw[key] = {**raw.get(key, {}), **val} if isinstance(val, dict) else val
    return raw


@pytest.fixture
def env(tmp_path, monkeypatch):
    calls, asked, history = [], [], {}

    def setup(**extra):
        cfg = settings.normalize(raw_config(tmp_path, **extra), tmp_path)
        server.configure(cfg)
        hub.setup(cfg, None)
        return cfg

    async def fake_call(http, act, name=''):
        calls.append(act)
        eid = act['data'].get('entity_id', '')
        cur = HA._STATES['data'].get(eid)
        if cur and act['service'] == 'toggle':
            cur['state'] = 'off' if cur['state'] == 'on' else 'on'
        elif cur and act['service'] in ('lock', 'unlock'):
            cur['state'] = act['service'] + 'ed'
        journal.add(name or eid, eid, act['service'], True)
        return True

    async def fake_converse(http, text, **kw):
        asked.append((text, kw))
        return {'ok': True, 'speech': 'Il fait très beau', 'conv_id': 'c1'}

    async def fake_history(http, entity, hours=24):
        return history.get(entity, [])

    async def fake_meteo(http, meteo_cfg):
        return {'ext': {'temp': 0, 'hum': 80}, 'rooms': [], 'forecast': []}

    HA.LIVE['connected'] = True
    HA.replace_states(make_states())
    monkeypatch.setattr(HA, 'call_service', fake_call)
    monkeypatch.setattr(HA, 'converse', fake_converse)
    monkeypatch.setattr(HA, 'fetch_history', fake_history)
    monkeypatch.setattr(HA, 'fetch_meteo', fake_meteo)
    monkeypatch.setattr(session, 'ACTION_DELAY', 0)
    monkeypatch.setattr(hub, 'DEBOUNCE', 0)
    setup()
    yield SimpleNamespace(setup=setup, calls=calls, asked=asked, history=history,
                          tmp=tmp_path)
    HA.LIVE['connected'] = False
    hub.SESSIONS.clear()
    hub.FAILS.clear()
    hub.TOKENS.clear()
    hub.ALERT['text'] = ''
    i18n.set_lang('fr')


async def open_session(remote='10.0.0.2', trusted=False):
    tx = FakeTransport()
    s = session.Session(tx, remote, trusted=trusted)
    hub.register(s)
    await s.start()
    return s, tx


async def press(s, *msgs):
    for m in msgs:
        async with s.lock:
            await s.feed(m)


ENVOI, SUITE, RETOUR = b'\x13A', b'\x13H', b'\x13B'
ANNUL, CORR, GUIDE, SOMM, REPET = b'\x13E', b'\x13G', b'\x13D', b'\x13F', b'\x13C'


def run(coro):
    return asyncio.run(coro)
