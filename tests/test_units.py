from datetime import datetime, timedelta, timezone

import alerts
import devices
import discover
import ha_client as HA
import ha_live
import i18n
import pagevideo as P
import settings
from tests.vt import Screen

# ------------------------------------------------------------------ settings

def test_settings_bornes_et_valeurs_par_defaut(tmp_path):
    cfg = settings.normalize({'display': {'page_size': 42, 'splash_seconds': None,
                                          'language': 'de'},
                              'devices': [{'entity': 'light.a', 'visible': False},
                                          {'entity': 'light.b'}, {'name': 'sans entite'}]},
                             tmp_path)
    assert cfg['display']['page_size'] == 9
    assert cfg['display']['splash_seconds'] == 7
    assert cfg['display']['language'] == 'fr'
    assert [d['entity'] for d in cfg['devices']] == ['light.b']
    assert cfg['assistant']['agents'][0]['id'] == 'conversation.home_assistant'
    assert cfg['security']['access_code'] == ''


def test_settings_alertes_yaml_booleens(tmp_path):
    # `state: on` sans guillemets est lu comme True par YAML
    cfg = settings.normalize({'alerts': [{'entity': 'binary_sensor.p', 'state': True},
                                         {'entity': 'sensor.t', 'above': 30}]}, tmp_path)
    assert cfg['alerts'][0]['states'] == {'on'}
    assert cfg['alerts'][1]['states'] is None and cfg['alerts'][1]['above'] == 30


def test_ordre_des_appareils_suit_le_regroupement():
    devs = [{'entity': 'a.1', 'area': 'X'}, {'entity': 'a.2', 'area': 'Y'},
            {'entity': 'a.3', 'area': 'Salon'}, {'entity': 'a.4', 'area': 'X'}]
    ordered = settings.sort_devices(devs, ['Salon'])
    shown = P.page_entries(ordered, 0, ['Salon'])
    assert [d['entity'] for d in shown] == [d['entity'] for d in ordered]


# ------------------------------------------------------------------ appareils

def dev(entity, state, **attrs):
    return {'entity': entity, 'name': entity, 'state': state, 'attrs': attrs}


def test_libelles_appareils():
    assert devices.label(dev('light.a', 'on', brightness=255)) == '100%'
    assert devices.label(dev('light.a', 'off')) == 'OFF'
    assert devices.label(dev('cover.v', 'open', current_position=40)) == '40%'
    assert devices.label(dev('cover.v', 'closed', current_position=0)) == 'FERME'
    assert devices.label(dev('climate.t', 'heat', temperature=21.0)) == '21°C'
    assert devices.label(dev('lock.p', 'locked')) == 'VERROU'
    assert devices.label(dev('media_player.r', 'playing')) == 'LECTURE'
    assert devices.label(dev('switch.s', 'unavailable')) == '--'
    assert not devices.is_active(dev('switch.s', 'unavailable'))
    assert devices.is_active(dev('cover.v', 'open'))


def test_actions_et_reglages():
    assert devices.action(dev('lock.p', 'locked'))['service'] == 'unlock'
    assert devices.action(dev('lock.p', 'locked'))['confirm'] is True
    assert devices.action(dev('lock.p', 'unlocked'))['confirm'] is False
    assert devices.action(dev('climate.t', 'off'))['service'] == 'turn_on'
    assert devices.action(dev('media_player.r', 'paused'))['service'] == 'media_play_pause'
    assert devices.action(dev('input_boolean.x', 'on'))['service'] == 'toggle'
    assert devices.action(dev('sensor.x', 'on'))['domain'] == 'homeassistant'
    up = devices.adjust(dev('cover.v', 'open', current_position=95), +1)
    assert up['data']['position'] == 100
    t = devices.adjust(dev('climate.t', 'heat', temperature=7, min_temp=7), -1)
    assert t['data']['temperature'] == 7
    assert devices.adjust(dev('switch.s', 'on'), +1) is None


def test_valeur_capteur():
    assert devices.sensor_value({'state': '21.46'}) == '21.5'
    assert devices.sensor_value({'state': '48.0'}) == '48'
    assert devices.sensor_value({'state': 'unknown'}) == '--'


# ------------------------------------------------------------------ alertes

def test_alertes():
    alerts.configure([{'entity': 'binary_sensor.p', 'states': {'on'}, 'message': 'Porte'},
                      {'entity': 'sensor.t', 'states': None, 'above': 30, 'below': None,
                       'message': 'Chaud'}])
    idx = {'binary_sensor.p': {'state': 'on'}, 'sensor.t': {'state': '31.2'}}
    assert alerts.evaluate(idx) == ['Porte', 'Chaud']
    idx['sensor.t']['state'] = 'unavailable'
    assert alerts.evaluate(idx) == ['Porte']
    assert P.alerts_text(['Porte', 'Chaud']) == '! Porte (+1)'
    alerts.configure([])


# ------------------------------------------------------------------ Videotex

def test_accents_g2_sans_octet_8_bits():
    b = P._line(4, 'Réponse : très, ça à 20°C …')
    assert all(x < 0x80 for x in b)
    assert b'R\x19Beponse' in b and b'\x19Kca' in b and b'20\x190C' in b and b'...' in b
    assert P._vt('ÉTÉ') == b'ETE'


def test_horloge_a_la_colonne_de_l_heure():
    scr = Screen()
    scr.feed(P.build_menu({'on': 3, 'off': 5, 'total': 8}))
    col = scr.line(2).index(datetime.now().strftime('%H:%M')[:2]) + 1
    assert col == P.CLOCK_COL


def test_tous_les_ecrans_tiennent_en_40_colonnes_et_7_bits():
    for lang in ('fr', 'en'):
        i18n.set_lang(lang)
        stats = {'on': 1, 'off': 2, 'total': 3}
        d = [{'entity': 'light.a', 'name': 'Lampe é' * 9, 'area': 'Pièce', 'state': 'on',
              'attrs': {}}]
        pages = [P.build_splash(), P.build_menu(stats), P.build_login(3, 'x'),
                 P.build_domotique(d, stats), P.build_capteurs(d), P.build_meteo({}),
                 P.build_scenes([], []), P.build_journal([]), P.build_archives([]),
                 P.build_assistant([], [{'id': 'a', 'name': 'A'}]), P.build_aide('menu', 0, True),
                 P.build_graph({'name': 'T', 'unit': '°C'}, [None] * 80)]
        pages += [P.build_aide('menu', i, True) for i in range(len(P.help_pages()))]
        for data in pages:
            assert all(x < 0x80 for x in data)
            scr = Screen()
            scr.feed(data)
            assert all(len(scr.line(r)) <= 40 for r in range(25))
    for key in ('dom.hint', 'dom.sel_adj', 'menu.footer', 'graph.axis', 'cap.footer'):
        for lang in ('fr', 'en'):
            i18n.set_lang(lang)
            assert len(i18n.t(key)) <= 40, (lang, key)
    i18n.set_lang('fr')


def test_mosaique_et_echantillonnage():
    assert P.mosaic([1, 1, 1, 1, 1, 1]) == 0x7f
    assert P.mosaic([0, 0, 0, 0, 0, 0]) == 0x20
    assert P.mosaic([1, 0, 0, 0, 0, 0]) == 0x21
    now = datetime(2026, 1, 1, 12, tzinfo=timezone.utc)
    pts = [(now - timedelta(hours=20), 10.0), (now - timedelta(hours=2), 20.0)]
    vals = P.bucket(pts, now, hours=24, n=24)
    assert vals[0] is None and vals[4] == 10.0 and vals[-1] == 20.0
    rows = P.graph_rows([0.0, 1.0] * 40, rows=2)
    assert len(rows) == 2 and all(len(r) == 40 for r in rows)


def test_ligne_0_retour_curseur():
    scr = Screen()
    scr.feed(P.build_menu({'on': 0, 'off': 0, 'total': 0}))
    scr.feed(P.build_status('! Alerte'))
    assert scr.line(0) == '! Alerte' and (scr.r, scr.c) == (24, 39)
    scr.feed(b'\x0c')                      # l'effacement d'ecran garde la ligne 0
    assert scr.line(0) == '! Alerte'


# ------------------------------------------------------------------ HA

def test_url_websocket():
    assert ha_live.ws_url('http://ha.local:8123/') == 'ws://ha.local:8123/api/websocket'
    assert ha_live.ws_url('https://x.ui.nabu.casa') == 'wss://x.ui.nabu.casa/api/websocket'
    assert ha_live.ws_url('http://supervisor/core') == 'ws://supervisor/core/websocket'


def test_messages_websocket():
    seen = []
    loaded = ha_live.handle_message({'id': 1, 'type': 'result', 'success': True, 'result': [
        {'entity_id': 'light.a', 'state': 'on'}]}, seen.append)
    assert loaded and HA._STATES['data']['light.a']['state'] == 'on' and seen == [None]
    ha_live.handle_message({'id': 2, 'type': 'event', 'event': {'data': {
        'entity_id': 'light.a', 'new_state': {'entity_id': 'light.a', 'state': 'off'}}}},
        seen.append)
    assert HA._STATES['data']['light.a']['state'] == 'off' and seen[-1] == {'light.a'}
    ha_live.handle_message({'id': 2, 'type': 'event', 'event': {'data': {
        'entity_id': 'light.a', 'new_state': None}}}, seen.append)
    assert 'light.a' not in HA._STATES['data']


# ------------------------------------------------------------------ decouverte

def test_decouverte_fusion():
    assert discover.parse_areas('light.a|Salon\nlight.b|None\n') == {
        'light.a': 'Salon', 'light.b': 'Autres'}
    found = [{'entity': 'light.a', 'name': 'HA', 'area': 'Salon', 'visible': True}]
    existing = {'light.a': {'entity': 'light.a', 'name': 'Perso', 'visible': False},
                'light.z': {'entity': 'light.z', 'name': 'Disparue', 'visible': True}}
    out = discover.merge(found, existing, False, ('name', 'area', 'visible'))
    assert out[0]['name'] == 'Perso' and out[0]['visible'] is False
    assert out[1] == {'entity': 'light.z', 'name': 'Disparue', 'visible': False}
    assert discover.merge(found, existing, True, ('name',))[0]['name'] == 'HA'
