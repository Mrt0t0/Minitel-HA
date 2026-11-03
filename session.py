"""Session d'un terminal : machine a etats commune au Minitel et au navigateur.

Le transport (WebSocket Minitel ou navigateur) fournit les octets tapes et
recoit les pages Videotex. Toute la logique des modes est ici, une seule
fois pour les deux interfaces.
"""
import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path

import devices
import ha_client as HA
import hub
import journal
import pagevideo as P
from i18n import t
from utils import log

LETTER_MODES = {
    'd': 'domotique', 'c': 'capteurs', 'm': 'meteo', 's': 'scenes',
    'j': 'journal', 'a': 'assistant', 'r': 'archives', 'h': 'aide',
}

# Touches de fonction : 0x13 suivi de ce code
FN_KEYS = {0x41: 'ENVOI', 0x42: 'RETOUR', 0x43: 'REPETITION', 0x44: 'GUIDE',
           0x45: 'ANNULATION', 0x46: 'SOMMAIRE', 0x47: 'CORRECTION',
           0x48: 'SUITE', 0x49: 'FIN'}

_G2_IN = {seq: ch for ch, seq in P.G2.items()}

ACTION_DELAY = 0.8     # laisse HA appliquer l'action avant de relire l'etat
FLASH_SECONDS = 3
LOGIN_TRIES = 3
LOGIN_MAX = 16


def tokens(data):
    """Decoupe les octets recus en touches : ('fn', nom) ou ('ch', caractere).
    Renvoie aussi le reste incomplet (sequence coupee entre deux trames)."""
    out, i = [], 0
    while i < len(data):
        b = data[i]
        if b == 0x13:
            if i + 1 >= len(data):
                return out, data[i:]
            name = FN_KEYS.get(data[i + 1])
            if name:
                out.append(('fn', name))
            i += 2
            continue
        if b == 0x19:
            n = 3 if i + 1 < len(data) and data[i + 1] in b'ABCHK' else 2
            if i + n > len(data):
                return out, data[i:]
            ch = _G2_IN.get(bytes(data[i:i + n]))
            if ch:
                out.append(('ch', ch))
            i += n
            continue
        if b == 0x0d:
            out.append(('fn', 'ENVOI'))
        elif b in (0x7f, 0x08):
            out.append(('fn', 'CORRECTION'))
        elif 0x20 <= b <= 0x7e:
            out.append(('ch', chr(b)))
        i += 1
    return out, b''


class Session:
    def __init__(self, transport, remote='?', trusted=False):
        self.tx      = transport
        self.remote  = remote
        self.ip      = remote.split(':')[0] if isinstance(remote, str) else str(remote)
        self.authed  = trusted or not hub.code_required()
        self.closed  = False
        self.lock    = asyncio.Lock()
        self._rest   = b''
        self._tasks  = {}

        self.mode, self.prev_mode = 'login', 'domotique'
        self.page, self.buf = 0, ''
        self.sel = self.sel_num = None
        self.confirm = None
        self.aide_general, self.aide_page = False, 0
        self.journal_page = 0
        self.assist_history, self.assist_agent_idx = [], 0
        self.assist_conv_id, self.assist_buf = None, ''
        self.archives_idx, self.archives_viewing = 0, False
        self.graph_idx = None
        self.login_buf, self.login_tries = '', 0
        self.devs, self.sens = [], []
        self.stats = {'on': 0, 'off': 0, 'total': 0}

    # ------------------------------------------------------------ cycle de vie

    @property
    def cfg(self):
        return hub.cfg

    async def run(self, incoming):
        hub.register(self)
        log('VT', f'+ {self.remote}')
        try:
            if await self.start():
                async for data in incoming:
                    async with self.lock:
                        await self.feed(data)
                    if self.closed:
                        break
        finally:
            self.closed = True
            for task in self._tasks.values():
                task.cancel()
            hub.unregister(self)
            log('VT', f'- {self.remote}')

    async def start(self):
        if not self.authed:
            allowed, mins = hub.login_allowed(self.ip)
            if not allowed:
                await self.bye(t('login.locked', m=mins))
                return False
        if P.CFG['splash_seconds'] > 0:
            await self.tx.send(P.build_splash())
            await asyncio.sleep(P.CFG['splash_seconds'])
        async with self.lock:
            if self.authed:
                await self.go('menu')
            else:
                self.mode = 'login'
                await self.show(P.build_login())
        return True

    async def bye(self, text):
        await self.tx.send(P.build_bye(text))
        self.closed = True
        await self.tx.close()

    def _later(self, name, coro):
        """Tache de fond unique par nom (la precedente est annulee)."""
        old = self._tasks.get(name)
        if old:
            old.cancel()
        self._tasks[name] = asyncio.ensure_future(coro)

    def _cancel(self, name):
        task = self._tasks.pop(name, None)
        if task:
            task.cancel()

    # ------------------------------------------------------------ affichage

    async def show(self, data):
        await self.tx.send(data)
        # La ligne 0 est redessinee apres chaque page complete
        if data[:1] == b'\x0c' and hub.ALERT['text'] and self.authed:
            await self.tx.send(P.build_status(hub.ALERT['text']))

    async def show_status(self):
        if self.authed and not self.closed:
            await self.tx.send(P.build_status(hub.ALERT['text']))

    async def clock_tick(self):
        if self.mode in ('menu', 'domotique') and not self.closed:
            async with self.lock:
                await self.tx.send(P.build_time_update() + P._goto(24, 40))

    def sel_dev(self):
        return next((d for d in self.devs if d['entity'] == self.sel), None)

    def _area_order(self):
        return self.cfg['area_order']

    async def reload(self):
        self.devs, self.sens, self.stats = await HA.fetch_data(
            hub.http, self.cfg['devices'], self.cfg['sensors'])

    def _files(self):
        folder = self.cfg['archives']['folder']
        try:
            folder.mkdir(parents=True, exist_ok=True)
            return sorted(({'name': f.stem, 'path': str(f), 'size': f.stat().st_size}
                           for f in folder.glob('*.vdt')), key=lambda x: x['name'])
        except OSError as e:
            log('ERR', f'archives: {e}')
            return []

    async def render(self, flash=''):
        m, ao = self.mode, self._area_order()
        if m == 'menu':
            data = P.build_menu(self.stats, self.buf, self.cfg['display']['show_sensors'])
        elif m == 'domotique':
            data = P.build_domotique(self.devs, self.stats, self.page, self.sel_num,
                                     self.sel_dev(), flash, ao)
        elif m == 'capteurs':
            data = P.build_capteurs(self.sens, self.page, self.sel_num, flash, ao)
        elif m == 'graph':
            data = await self._graph_page()
        elif m == 'meteo':
            data = P.build_meteo(await HA.fetch_meteo(hub.http, self.cfg['meteo']))
        elif m == 'scenes':
            data = P.build_scenes(self.cfg['scenes'], self.cfg['scripts'], self.buf, flash)
        elif m == 'journal':
            data = P.build_journal(journal.ENTRIES, self.journal_page)
        elif m == 'assistant':
            data = P.build_assistant(self.assist_history, self.cfg['assistant']['agents'],
                                     self.assist_agent_idx, self.assist_buf, flash)
        elif m == 'archives':
            data = P.build_archives(self._files(), self.archives_idx, flash,
                                    self._folder_label())
        elif m == 'aide':
            ctx = 'capteurs' if self.prev_mode == 'graph' else self.prev_mode
            data = P.build_aide(ctx, self.aide_page, self.aide_general)
        else:
            data = P.build_login(len(self.login_buf), flash)
        await self.show(data)

    def _folder_label(self):
        folder = self.cfg['archives']['folder']
        try:
            return str(folder.relative_to(self.cfg['base'])) + '/'
        except ValueError:
            return str(folder) + '/'

    async def go(self, mode, general=False):
        if mode == 'capteurs' and not self.cfg['display']['show_sensors']:
            return
        if self.mode != 'aide':
            self.prev_mode = self.mode
        self.mode, self.buf, self.page = mode, '', 0
        self.sel = self.sel_num = self.confirm = None
        self._cancel('rotate')
        self._cancel('flash')
        if mode == 'assistant':
            self.assist_buf = ''
        elif mode == 'aide':
            self.aide_general, self.aide_page = general, 0
        elif mode == 'journal':
            self.journal_page = 0
        elif mode == 'archives':
            self.archives_viewing = False
            self._later('rotate', self._rotate_archives())
        if mode in ('domotique', 'capteurs'):
            await self.tx.send(P.build_loading())
        if mode in ('menu', 'domotique', 'capteurs'):
            await self.reload()
        await self.render()

    async def letter(self, ch):
        """Lettre de mode : change de mode. Renvoie True si consommee."""
        mode = LETTER_MODES.get(ch.lower())
        if not mode or (mode == 'capteurs' and not self.cfg['display']['show_sensors']):
            return False
        await self.go(mode, general=(mode == 'aide'))
        return True

    # ------------------------------------------------------------ clavier

    async def feed(self, data):
        keys, self._rest = tokens(self._rest + bytes(data))
        if self.mode not in ('login', 'assistant'):     # pas de code ni de texte prive
            log('VT', f'[{self.ip}][{self.mode}] {bytes(data).hex()[:16]}')
        for kind, val in keys:
            if self.closed:
                return
            await self.on_key(kind, val)

    async def on_key(self, kind, val):
        if self.mode == 'login':
            return await self.k_login(kind, val)
        if self.confirm:
            return await self.k_confirm(kind, val)
        if kind == 'fn':
            if val in ('SOMMAIRE', 'FIN'):
                HA.invalidate_cache()
                return await self.go('menu')
            if val == 'GUIDE':
                return await self.k_guide()
            if val == 'REPETITION' and self.mode != 'assistant':
                if self.mode in ('domotique', 'capteurs', 'menu'):
                    await self.reload()
                return await self.render()
        await getattr(self, 'k_' + self.mode)(kind, val)

    def _back_mode(self):
        """Mode a retrouver en quittant l'aide."""
        if self.prev_mode == 'graph':
            return 'capteurs'
        return self.prev_mode if self.prev_mode not in ('aide', 'login') else 'menu'

    async def k_guide(self):
        if self.mode != 'aide':
            return await self.go('aide', general=False)
        if self.aide_general:
            return await self.go(self._back_mode())
        self.aide_general, self.aide_page = True, 0
        await self.render()

    async def k_login(self, kind, val):
        if kind == 'ch':
            if len(self.login_buf) < LOGIN_MAX:
                self.login_buf += val
                await self.tx.send(P.build_login_input(len(self.login_buf)))
            return
        if val in ('CORRECTION', 'ANNULATION'):
            self.login_buf = self.login_buf[:-1] if val == 'CORRECTION' else ''
            return await self.tx.send(P.build_login_input(len(self.login_buf)))
        if val != 'ENVOI':
            return
        code, self.login_buf = self.login_buf, ''
        if hub.check_code(code):
            hub.login_ok(self.ip)
            self.authed = True
            log('VT', f'{self.ip} : code d\'acces accepte')
            await self.tx.send_text(json.dumps({'token': hub.issue_token()}))
            return await self.go('menu')
        hub.login_failed(self.ip)
        self.login_tries += 1
        log('WARN', f'{self.ip} : code d\'acces refuse ({self.login_tries})')
        allowed, mins = hub.login_allowed(self.ip)
        if not allowed:
            return await self.bye(t('login.locked', m=mins))
        if self.login_tries >= LOGIN_TRIES:
            return await self.bye(t('login.bye'))
        await self.render(t('login.bad', n=LOGIN_TRIES - self.login_tries))

    async def k_confirm(self, kind, val):
        act, name, force = self.confirm
        self.confirm = None
        if kind == 'fn' and val == 'ENVOI':
            self.sel = self.sel_num = None
            return await self.execute(act, name, force)
        await self.tx.send(P.build_flash('') + P.build_prompt(P.dom_prompt(
            self.sel_num, self.sel_dev()), highlight=bool(self.sel_dev())))

    # ------------------------------------------------------------ actions HA

    async def ask_or_run(self, act, name, confirm_text, force=()):
        """Execute l'action, ou demande d'abord confirmation (ENVOI = oui).
        force = lignes a redessiner (ancienne selection)."""
        if act['confirm']:
            self.confirm = (act, name, force)
            return await self.tx.send(P.build_confirm(confirm_text))
        self.sel = self.sel_num = None
        await self.execute(act, name, force)

    async def execute(self, act, name, force=()):
        ok = await HA.call_service(hub.http, act, name)
        flash = f'[{"OK" if ok else "ERR"}] {P._safe(name)[:28]}'
        await asyncio.sleep(ACTION_DELAY)
        if self.mode == 'domotique':
            await self.refresh_rows(flash=flash, force=force)
        else:
            await self.render(flash)
        self._later('flash', self._clear_flash(self.mode))

    async def _clear_flash(self, mode):
        await asyncio.sleep(FLASH_SECONDS)
        async with self.lock:
            if self.closed or self.mode != mode or self.confirm:
                return
            data = P.build_flash('')
            if mode == 'domotique':
                data += P.build_prompt(P.dom_prompt(self.sel_num, self.sel_dev()),
                                       highlight=bool(self.sel_dev()))
            else:
                data += P._goto(24, 40)
            await self.tx.send(data)

    def _snapshot(self):
        return ({d['entity']: (devices.label(d), devices.is_active(d)) for d in self.devs},
                {s['entity']: devices.sensor_value(s) for s in self.sens},
                dict(self.stats))

    async def refresh_rows(self, flash=None, force=()):
        """Relit HA puis redessine seulement les lignes qui ont change."""
        old_d, old_s, old_stats = self._snapshot()
        await self.reload()
        ao = self._area_order()
        if self.mode == 'domotique':
            shown = P.page_entries(self.devs, self.page, ao)
            nums = {n for n, d in enumerate(shown, 1)
                    if old_d.get(d['entity']) != (devices.label(d), devices.is_active(d))}
            nums |= set(force)
            if nums or flash is not None or self.stats != old_stats:
                await self.tx.send(P.build_dom_update(self.devs, self.stats, self.page, nums,
                                                      self.sel_num, self.sel_dev(), flash, ao))
        elif self.mode == 'capteurs':
            shown = P.page_entries(self.sens, self.page, ao)
            nums = {n for n, s in enumerate(shown, 1)
                    if old_s.get(s['entity']) != devices.sensor_value(s)}
            if nums:
                await self.tx.send(P.build_cap_update(self.sens, self.page, nums,
                                                      self.sel_num, ao))
        elif self.mode == 'menu' and self.stats != old_stats:
            await self.tx.send(P.build_stats_line(self.stats))

    async def on_states_changed(self):
        """Appele par hub quand des etats HA ont change."""
        if self.closed or not self.authed or self.mode not in ('domotique', 'capteurs', 'menu'):
            return
        async with self.lock:
            if self.mode in ('domotique', 'capteurs', 'menu') and not self.confirm:
                await self.refresh_rows()

    # ------------------------------------------------------------ modes

    async def k_menu(self, kind, val):
        if kind == 'ch':
            await self.letter(val)

    async def _select(self, entries, n, update):
        """Selection d'un element numerote de la page courante."""
        shown = P.page_entries(entries, self.page, self._area_order())
        if not 1 <= n <= len(shown):
            return
        old, self.sel_num, self.sel = self.sel_num, n, shown[n - 1]['entity']
        await self.tx.send(update({x for x in (old, n) if x}))

    async def _unselect(self, update):
        old, self.sel_num, self.sel = self.sel_num, None, None
        await self.tx.send(update({old} if old else set()))

    def _dom_update(self, nums, flash=None):
        return P.build_dom_update(self.devs, self.stats, self.page, nums, self.sel_num,
                                  self.sel_dev(), flash, self._area_order())

    async def k_domotique(self, kind, val):
        dev = self.sel_dev()
        if kind == 'ch':
            if val in '123456789':
                return await self._select(self.devs, int(val), self._dom_update)
            if val == '0':
                return await self.go('journal')
            if val == '*':
                qo = self.cfg['quick_off']
                if qo:
                    act = {'domain': qo['entity'].split('.')[0], 'service': 'turn_on',
                           'confirm': qo['confirm'], 'data': {'entity_id': qo['entity']}}
                    await self.ask_or_run(act, qo['name'], qo['name'])
                return
            await self.letter(val)
            return
        if val == 'ENVOI' and dev:
            await self.ask_or_run(devices.action(dev), dev['name'],
                                  t('act.unlock', name=dev['name']), force={self.sel_num})
        elif val in ('SUITE', 'RETOUR'):
            step = 1 if val == 'SUITE' else -1
            act = devices.adjust(dev, step) if dev else None
            if act:
                ok = await HA.call_service(hub.http, act, dev['name'])
                await asyncio.sleep(ACTION_DELAY)
                await self.refresh_rows(flash='' if ok else f'[ERR] {P._safe(dev["name"])[:28]}',
                                        force={self.sel_num})
            else:
                self.page = (self.page + step) % P.page_count(self.devs)
                self.sel = self.sel_num = None
                await self.render()
        elif val in ('CORRECTION', 'ANNULATION'):
            await self._unselect(self._dom_update)

    async def k_capteurs(self, kind, val):
        if kind == 'ch':
            if val in '123456789':
                def upd(nums):
                    return P.build_cap_update(self.sens, self.page, nums, self.sel_num,
                                              self._area_order())
                return await self._select(self.sens, int(val), upd)
            await self.letter(val)
        elif val == 'ENVOI' and self.sel:
            self.graph_idx = next(i for i, s in enumerate(self.sens) if s['entity'] == self.sel)
            self.prev_mode, self.mode = 'capteurs', 'graph'
            await self.tx.send(P.build_loading())
            await self.render()
        elif val in ('SUITE', 'RETOUR'):
            step = 1 if val == 'SUITE' else -1
            self.page = (self.page + step) % P.page_count(self.sens)
            self.sel = self.sel_num = None
            await self.render()
        elif val in ('CORRECTION', 'ANNULATION') and self.sel:
            self.sel = self.sel_num = None
            await self.render()

    async def _graph_page(self):
        sensor = self.sens[self.graph_idx]
        points = await HA.fetch_history(hub.http, sensor['entity'])
        return P.build_graph(sensor, P.bucket(points, datetime.now(timezone.utc)))

    async def k_graph(self, kind, val):
        if kind == 'ch':
            await self.letter(val)
        elif val == 'SUITE' and self.sens:
            self.graph_idx = (self.graph_idx + 1) % len(self.sens)
            self.sel = self.sens[self.graph_idx]['entity']
            await self.tx.send(P.build_loading())
            await self.render()
        elif val in ('RETOUR', 'ANNULATION', 'ENVOI', 'CORRECTION'):
            self.mode = 'capteurs'
            # Revient sur la page du capteur affiche
            for page in range(P.page_count(self.sens)):
                shown = P.page_entries(self.sens, page, self._area_order())
                if any(s['entity'] == self.sel for s in shown):
                    self.page = page
                    self.sel_num = next(n for n, s in enumerate(shown, 1)
                                        if s['entity'] == self.sel)
                    break
            await self.render()

    async def k_meteo(self, kind, val):
        if kind == 'ch':
            await self.letter(val)
        elif val == 'ENVOI':
            await self.render()

    async def k_scenes(self, kind, val):
        items = list(self.cfg['scenes']) + list(self.cfg['scripts'])
        if kind == 'ch':
            if val in '123456789' and int(val) <= len(items):
                self.buf = val
                return await self.tx.send(P.build_flash(
                    f'> {val}. {P._safe(items[int(val) - 1]["name"])[:32]}') + P._goto(24, 40))
            await self.letter(val)
        elif val == 'ENVOI' and self.buf:
            it = items[int(self.buf) - 1]
            self.buf = ''
            await self.execute({'domain': it['entity'].split('.')[0], 'service': 'turn_on',
                                'confirm': False, 'data': {'entity_id': it['entity']}},
                               it['name'])
        elif val in ('CORRECTION', 'ANNULATION'):
            self.buf = ''
            await self.tx.send(P.build_flash('') + P._goto(24, 40))

    async def k_journal(self, kind, val):
        if kind == 'ch':
            await self.letter(val)
        elif val in ('SUITE', 'RETOUR'):
            step = 1 if val == 'SUITE' else -1
            self.journal_page = (self.journal_page + step) % P.journal_pages(journal.ENTRIES)
            await self.render()

    async def k_aide(self, kind, val):
        if kind == 'ch':
            await self.letter(val)
        elif val in ('SUITE', 'RETOUR'):
            if self.aide_general:
                step = 1 if val == 'SUITE' else -1
                self.aide_page = (self.aide_page + step) % len(P.help_pages())
                await self.render()
        elif val in ('ENVOI', 'ANNULATION'):
            await self.go(self._back_mode())

    async def k_assistant(self, kind, val):
        agents = self.cfg['assistant']['agents']
        if kind == 'ch':
            self.assist_buf = (self.assist_buf + val)[:P.ASSIST_MAX]
            return await self.tx.send(P.build_assist_input_line(self.assist_buf))
        if val == 'CORRECTION':
            self.assist_buf = self.assist_buf[:-1]
            await self.tx.send(P.build_assist_input_line(self.assist_buf))
        elif val == 'ANNULATION':
            self.assist_buf = ''
            await self.tx.send(P.build_assist_input_line(''))
        elif val == 'REPETITION':
            self.assist_history, self.assist_conv_id = [], None
            await self.render(t('assist.new'))
        elif val == 'SUITE' and len(agents) > 1:
            self.assist_agent_idx = (self.assist_agent_idx + 1) % len(agents)
            self.assist_history, self.assist_conv_id = [], None
            await self.render(f' Agent: {P._safe(agents[self.assist_agent_idx]["name"])}')
        elif val == 'ENVOI' and self.assist_buf.strip():
            q = self.assist_buf.strip()
            await self.tx.send(P.build_assist_input_line('', t('assist.wait')))
            res = await HA.converse(hub.http, q, agent_id=agents[self.assist_agent_idx]['id'],
                                    language=self.cfg['assistant']['language'],
                                    conversation_id=self.assist_conv_id)
            self.assist_conv_id = None if res.get('reset_conv') else res.get('conv_id')
            self.assist_history = (self.assist_history
                                   + [{'q': q, 'r': res.get('speech', '...')}])[-10:]
            self.assist_buf = ''
            await self.render()

    async def _rotate_archives(self):
        interval = self.cfg['archives']['auto_rotate']
        if interval <= 0:
            return
        while True:
            await asyncio.sleep(interval)
            async with self.lock:
                if self.closed or self.mode != 'archives' or self.archives_viewing:
                    continue
                files = self._files()
                if len(files) < 2:
                    continue
                self.archives_idx = (self.archives_idx + 1) % len(files)
                await self.render()

    async def _open_vdt(self, files):
        f = files[self.archives_idx]
        try:
            data = Path(f['path']).read_bytes()
        except OSError as e:
            self.archives_viewing = False
            return await self.render(t('arch.error', e=e))
        self.archives_viewing = True
        log('VT', f'vdt: {f["name"]}')
        await self.tx.send(data)

    async def k_archives(self, kind, val):
        files = self._files()
        total = len(files)
        if total:
            self.archives_idx = min(self.archives_idx, total - 1)
        if self.archives_viewing:
            if kind == 'fn' and val in ('SUITE', 'RETOUR') and total:
                step = 1 if val == 'SUITE' else -1
                self.archives_idx = (self.archives_idx + step) % total
                return await self._open_vdt(files)
            self.archives_viewing = False
            return await self.render()
        if kind == 'ch':
            if val in '123456789' and total:
                i = (self.archives_idx // P.ARCH_PAGE) * P.ARCH_PAGE + int(val) - 1
                if i < total:
                    self.archives_idx = i
                    await self.render()
                return
            await self.letter(val)
        elif val in ('SUITE', 'RETOUR') and total:
            step = 1 if val == 'SUITE' else -1
            self.archives_idx = (self.archives_idx + step) % total
            await self.render()
        elif val == 'ENVOI' and total:
            await self._open_vdt(files)
