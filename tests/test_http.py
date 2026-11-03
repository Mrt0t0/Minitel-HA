import aiohttp
from aiohttp.test_utils import TestClient, TestServer

import hub
import server
from tests.conftest import run


async def _client():
    client = TestClient(TestServer(server.create_app()))
    await client.start_server()
    return client


def _form(name, data=b'\x0cPAGE'):
    form = aiohttp.FormData()
    form.add_field('file', data, filename=name, content_type='application/octet-stream')
    return form


def test_page_et_api_sans_code(env):
    async def go():
        c = await _client()
        try:
            r = await c.get('/')
            assert r.status == 200 and 'Minitel-HA' in await r.text()
            r = await c.post('/api/archives/upload', data=_form('Ma page.vdt'))
            assert r.status == 200 and (await r.json())['name'] == 'Ma page'
            r = await c.get('/api/archives/list')
            assert [f['name'] for f in (await r.json())['files']] == ['Ma page']
            r = await c.get('/api/archives/vdt/Ma%20page')
            assert await r.read() == b'\x0cPAGE'
        finally:
            await c.close()
    run(go())


def test_depot_refuse_noms_et_tailles_invalides(env):
    env.setup(archives={'folder': str(env.tmp / 'archives'), 'max_upload_kb': 1})

    async def go():
        c = await _client()
        try:
            for name in ('.cache.vdt', 'page.exe', 'x' * 70 + '.vdt'):
                r = await c.post('/api/archives/upload', data=_form(name))
                assert r.status == 400, name
            # Un chemin est reduit a son nom : le fichier reste dans le dossier
            for name in ('../evil.vdt', 'a/b.vdt'):
                r = await c.post('/api/archives/upload', data=_form(name))
                assert r.status == 200, name
            r = await c.post('/api/archives/upload', data=_form('gros.vdt', b'x' * 2048))
            assert r.status == 413
            r = await c.get('/api/archives/vdt/..%2F..%2Fjournal')
            assert r.status == 404
        finally:
            await c.close()
    run(go())
    assert not (env.tmp / 'evil.vdt').exists()
    assert sorted(p.name for p in (env.tmp / 'archives').iterdir()) == ['b.vdt', 'evil.vdt']


def test_api_protegee_par_le_code(env):
    env.setup(security={'access_code': '1234'})

    async def go():
        c = await _client()
        try:
            assert (await c.get('/')).status == 200
            assert (await c.get('/api/archives/list')).status == 401
            r = await c.post('/api/archives/upload', data=_form('p.vdt'))
            assert r.status == 401
            tok = hub.issue_token()
            r = await c.get('/api/archives/list', headers={'X-Minitel-Token': tok})
            assert r.status == 200
            r = await c.get('/api/archives/list', headers={'X-Minitel-Token': 'faux'})
            assert r.status == 401
        finally:
            await c.close()
    run(go())
