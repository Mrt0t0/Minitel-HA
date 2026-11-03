import json
from datetime import datetime, timedelta, timezone

import ha_client as HA
import hub
import journal
from tests.conftest import (
    ANNUL,
    CORR,
    ENVOI,
    GUIDE,
    REPET,
    RETOUR,
    SOMM,
    SUITE,
    open_session,
    press,
    run,
)


def test_menu_lettre_puis_envoi_ouvre_le_bon_mode(env):
    # Le 2e octet de ENVOI (0x13 'A') ne doit pas etre lu comme la lettre A
    async def go():
        s, tx = await open_session()
        assert s.mode == 'menu' and 'MENU PRINCIPAL' in tx.screen
        await press(s, b'd')
        assert s.mode == 'domotique'
        await press(s, b'm')
        assert s.mode == 'meteo'
        await press(s, SUITE)                 # 0x13 'H' n'ouvre pas l'aide
        assert s.mode == 'meteo'
        assert ' 0 C' in tx.screen.line(5) or '0' in tx.screen.line(5)
    run(go())


def test_numero_affiche_designe_l_appareil_commande(env):
    async def go():
        s, tx = await open_session()
        await press(s, b'd')
        scr = tx.screen
        assert scr.line(4).strip() == 'SALON'
        # 6e appareil affiche = Lampe X2 (piece Bureau, apres X1)
        row6 = next(r for r in range(4, 22) if scr.line(r).startswith(' 6.'))
        assert 'Lampe X2' in scr.line(row6)
        await press(s, b'6', ENVOI)
        assert env.calls[-1]['data']['entity_id'] == 'light.x2'
        assert env.calls[-1]['service'] == 'toggle'
        assert 'ON' in scr.line(row6)          # ligne redessinee apres l'action
        assert '[OK] Lampe X2' in scr.line(23)
    run(go())


def test_mise_a_jour_partielle_apres_action(env):
    async def go():
        s, tx = await open_session()
        await press(s, b'd')
        full = len(tx.sent[-1])
        n = len(tx.sent)
        await press(s, b'5', ENVOI)
        partial = sum(len(x) for x in tx.sent[n:])
        assert partial < full / 2              # seules les lignes changees partent
    run(go())


def test_reglage_luminosite_et_pages(env):
    async def go():
        s, tx = await open_session()
        await press(s, b'd', b'1')
        assert 'SUITE+' in tx.screen.line(24)  # lampe : reglable
        await press(s, SUITE)
        assert env.calls[-1] == {'domain': 'light', 'service': 'turn_on', 'confirm': False,
                                 'data': {'entity_id': 'light.salon', 'brightness_step_pct': 10}}
        await press(s, b'4', RETOUR)           # thermostat 20 -> 19.5
        assert env.calls[-1]['data'] == {'entity_id': 'climate.thermo', 'temperature': 19.5}
        await press(s, CORR, SUITE)            # sans selection : changement de page
        assert len(env.calls) == 2 and s.page == 0  # une seule page : on y reste
    run(go())


def test_deverrouillage_demande_confirmation(env):
    async def go():
        s, tx = await open_session()
        await press(s, b'd', b'2', ENVOI)
        assert env.calls == [] and 'ENVOI=oui' in tx.screen.line(23)
        await press(s, ANNUL)
        assert env.calls == [] and s.confirm is None
        await press(s, ENVOI)
        assert 'ENVOI=oui' in tx.screen.line(23)
        await press(s, ENVOI)
        assert env.calls[-1]['service'] == 'unlock'
    run(go())


def test_tout_eteindre_avec_confirmation(env):
    async def go():
        s, tx = await open_session()
        await press(s, b'd', b'*')
        assert env.calls == []
        await press(s, ENVOI)
        assert env.calls[-1]['data']['entity_id'] == 'scene.tout_eteindre'
    run(go())


def test_capteurs_et_graphique(env):
    now = datetime.now(timezone.utc)
    env.history['sensor.temp_salon'] = [(now - timedelta(hours=h), 15 + h % 7) for h in range(24)]

    async def go():
        s, tx = await open_session()
        await press(s, b'c')
        assert s.mode == 'capteurs'
        assert any('21.5' in tx.screen.line(r) and '°C' in tx.screen.line(r)
                   for r in range(4, 22))
        await press(s, b'1', ENVOI)
        assert s.mode == 'graph' and 'GRAPHIQUE 24H' in tx.screen
        assert '#' in tx.screen.line(20)       # barres semi-graphiques
        assert 'max 21°C' in tx.screen.line(4)
        await press(s, RETOUR)
        assert s.mode == 'capteurs'
    run(go())


def test_capteurs_masques(env):
    env.setup(display={'splash_seconds': 0, 'show_sensors': False})

    async def go():
        s, tx = await open_session()
        assert 'Capteurs' not in tx.screen
        await press(s, b'c')
        assert s.mode == 'menu'
    run(go())


def test_archives_selection_page_2(env):
    folder = env.tmp / 'archives'
    folder.mkdir(exist_ok=True)
    for i in range(1, 13):
        (folder / f'p{i:02d}.vdt').write_bytes(f'\x0cPAGE{i:02d}'.encode())

    async def go():
        s, tx = await open_session()
        await press(s, b'r', *[SUITE] * 9, b'3', ENVOI)
        assert tx.sent[-1] == b'\x0cPAGE12'
        await press(s, SUITE)
        assert tx.sent[-1] == b'\x0cPAGE01'    # fichier suivant (boucle)
        await press(s, ANNUL)
        assert not s.archives_viewing and 'ARCHIVES' in tx.screen
    run(go())


def test_assistant_accents_et_nouvelle_conversation(env):
    async def go():
        s, tx = await open_session()
        await press(s, b'a', b'caf\x19Be ?', ENVOI)
        assert env.asked[-1][0] == 'café ?'
        assert env.asked[-1][1]['agent_id'] == 'conversation.a'
        assert 'Il fait très beau' in tx.screen
        await press(s, SUITE)                  # agent suivant
        assert 'Agent B' in tx.screen.line(2)
        await press(s, b'x', REPET)
        assert s.assist_history == [] and s.assist_conv_id is None
    run(go())


def test_guide_et_retour(env):
    async def go():
        s, tx = await open_session()
        await press(s, b'j', GUIDE)
        assert s.mode == 'aide' and 'JOURNAL' in tx.screen.line(2)
        await press(s, GUIDE)
        assert s.aide_general and 'AIDE GENERALE' in tx.screen
        await press(s, SUITE)
        assert s.aide_page == 1
        await press(s, GUIDE)
        assert s.mode == 'journal'
        await press(s, SOMM)
        assert s.mode == 'menu'
    run(go())


def test_code_acces(env):
    env.setup(security={'access_code': '1234'})

    async def go():
        s, tx = await open_session()
        assert s.mode == 'login' and 'CODE' in tx.screen
        await press(s, SOMM, GUIDE)     # rien n'est accessible avant le code
        assert s.mode == 'login'
        await press(s, b'12')
        assert '**_' in tx.screen.line(10) and '12' not in tx.screen.line(10)
        await press(s, b'34', ENVOI)
        assert s.mode == 'menu'
        assert hub.token_valid(json.loads(tx.texts[-1])['token'])
    run(go())


def test_code_acces_refuse_puis_blocage(env):
    env.setup(security={'access_code': '1234'})

    async def go():
        s, tx = await open_session('10.0.0.9')
        for _ in range(3):
            await press(s, b'0000', ENVOI)
        assert s.closed and tx.closed           # 3 essais par connexion
        s2, tx2 = await open_session('10.0.0.9')
        await press(s2, b'1111', ENVOI, b'2222', ENVOI)
        assert s2.closed                        # 5 essais : IP bloquee
        s3, tx3 = await open_session('10.0.0.9')
        assert s3.closed and 'reessayez' in tx3.screen.line(12)
        s4, _ = await open_session('10.0.0.10')  # autre IP : non bloquee
        assert not s4.closed
    run(go())


def test_ingress_sans_code(env):
    env.setup(security={'access_code': '1234'})

    async def go():
        s, tx = await open_session(trusted=True)
        assert s.mode == 'menu'
    run(go())


def test_alerte_ligne_0_et_mise_a_jour_temps_reel(env):
    async def go():
        s, tx = await open_session()
        await press(s, b'd')
        HA.apply_state('binary_sensor.porte_entree', {'entity_id': 'binary_sensor.porte_entree',
                                                      'state': 'on', 'attributes': {}})
        HA.apply_state('light.x1', {'entity_id': 'light.x1', 'state': 'on', 'attributes': {}})
        n = len(tx.sent)
        hub.notify({'binary_sensor.porte_entree', 'light.x1'})
        await hub._pending['task']
        assert "! Porte d'entrée ouverte" in tx.screen.line(0)
        row5 = next(r for r in range(4, 22) if tx.screen.line(r).startswith(' 5.'))
        assert tx.screen.line(row5).endswith('ON')
        assert all(not m.startswith(b'\x0c') for m in tx.sent[n:])   # pas de page complete
        await press(s, SOMM)                    # la ligne 0 survit au changement d'ecran
        assert "Porte d'entrée" in tx.screen.line(0)
        HA.apply_state('binary_sensor.porte_entree', None)
        hub.notify({'binary_sensor.porte_entree'})
        await hub._pending['task']
        assert tx.screen.line(0) == ''
    run(go())


def test_journal_persistant(env):
    async def go():
        s, tx = await open_session()
        await press(s, b'd', b'1', ENVOI)
    run(go())
    path = env.tmp / 'journal.json'
    assert json.loads(path.read_text())[-1]['entity'] == 'light.salon'
    journal.configure(path, 50)
    assert journal.ENTRIES[-1]['name'] == 'Lampe salon'


def test_anglais(env):
    env.setup(display={'splash_seconds': 0, 'language': 'en'})

    async def go():
        s, tx = await open_session()
        assert 'MAIN MENU' in tx.screen and 'Devices' in tx.screen
    run(go())


def test_sequence_coupee_entre_deux_trames(env):
    async def go():
        s, tx = await open_session()
        await press(s, b'd', b'2\x13', b'A')
        assert s.mode == 'domotique' and s.confirm
    run(go())
