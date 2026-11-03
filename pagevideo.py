"""Construction des pages Videotex (40 x 24, ligne 0 de service).

Chaque fonction build_* renvoie les octets a envoyer tels quels au Minitel
(ou a l'emulateur du navigateur). Les textes viennent de i18n.
"""
from collections import OrderedDict
from datetime import datetime, timedelta

import devices
import journal
from i18n import t

VERSION   = '1.3'
PAGE_SIZE = 9

CFG = {
    'title':          '   MINITEL-HA  DOMOTIQUE',
    'page_size':      9,
    'date_format':    '%H:%M',
    'splash_seconds': 7,
}

_TRANSLIT = str.maketrans({
    '’': "'", '‘': "'", '“': '"', '”': '"',
    '–': '-', '—': '-', '…': '...', '•': '*',
    ' ': ' ', '«': '"', '»': '"', '‹': '<',
    '›': '>', '­': '-', '−': '-', '×': 'x',
    '÷': '/', '€': 'E', '²': '2', '³': '3',
})

_ACCENTS = str.maketrans(
    'àâäéèêëîïôöùûüçÀÂÄÉÈÊËÎÏÔÖÙÛÜÇ',
    'aaaeeeeiioouuucAAAEEEEIIOOUUUC')

# Le Minitel est en 7 bits : les accents passent par le jeu G2 (SS2 = 0x19).
# Seules les minuscules accentuees existent ; les majuscules perdent l'accent.
G2 = {
    'à': b'\x19Aa', 'â': b'\x19Ca', 'ä': b'\x19Ha',
    'é': b'\x19Be', 'è': b'\x19Ae', 'ê': b'\x19Ce', 'ë': b'\x19He',
    'î': b'\x19Ci', 'ï': b'\x19Hi', 'ô': b'\x19Co', 'ö': b'\x19Ho',
    'ù': b'\x19Au', 'û': b'\x19Cu', 'ü': b'\x19Hu', 'ç': b'\x19Kc',
    '°': b'\x190',  '£': b'\x19#',  'œ': b'\x19z',  'Œ': b'\x19j',
}

# Colonne de l'heure dans le sous-titre ' ON:xx OFF:xx/xx   HH:MM'
CLOCK_COL = 20

SO, SI = b'\x0e', b'\x0f'      # passage en semi-graphique (G1) / retour G0


def _goto(r, c):  return bytes([0x1f, 0x40 + r, 0x40 + c])
def _fg(c):       return bytes([0x1b, 0x40 + c])
def _bg(c):       return bytes([0x1b, 0x50 + c])
def _blink_on():  return bytes([0x1b, 0x48])
def _blink_off(): return bytes([0x1b, 0x49])


def _center(text, width=40):
    return text.center(width)[:width]


def _safe(t_):
    """Normalise la ponctuation typographique en conservant les accents."""
    return str(t_).translate(_TRANSLIT)


def _vt(text):
    """Encode une chaine pour le Minitel : ASCII 7 bits, accents via G2."""
    out = bytearray()
    for ch in _safe(text):
        if ch in G2:
            out += G2[ch]
        else:
            out += ch.translate(_ACCENTS).encode('ascii', 'replace')
    return bytes(out)


def _line(row, text, fg_c=7, bg_c=0, blink=False):
    out = _goto(row, 1) + _bg(bg_c) + _fg(fg_c)
    if blink:
        out += _blink_on()
    out += _vt(_safe(text)[:40].ljust(40))
    if blink:
        out += _blink_off()
    return out


def _page(build_rows):
    """Ecran complet : effacement, curseur masque, lignes, curseur en 24/40."""
    out = bytearray(b'\x0c\x14')
    build_rows(out)
    return bytes(out + b'\x11' + _goto(24, 40))


def _header(out, title, subtitle, fg_sub=3):
    out += _line(1, _safe(title)[:40], fg_c=0, bg_c=7)
    out += _line(2, subtitle, fg_c=fg_sub)
    out += _line(3, ' ' + '=' * 38, fg_c=7)
    return out


def _fill(out, start, end):
    for r in range(start, end + 1):
        out += _line(r, '')


def _v(x, default='?'):
    """Valeur affichable : 0 reste 0, seule l'absence donne `default`."""
    return default if x is None or x == '' else str(x)


def _now():
    return datetime.now().strftime(CFG['date_format'])


def stats_subtitle(stats):
    return f' ON:{stats["on"]:2d} OFF:{stats["off"]:2d}/{stats["total"]:2d}   {_now()}'


# ------------------------------------------------------------------ ligne 0

def build_status(text):
    """Ligne de service (rangee 0) : alertes. Le LF final ramene le curseur
    a sa position precedente ; la ligne 0 survit aux effacements d'ecran."""
    out = bytearray(_goto(0, 1))
    if text:
        out += _fg(3) + _blink_on() + _vt(_safe(text)[:38]) + _blink_off()
    out += b'\x18\x0a'
    return bytes(out)


def alerts_text(messages):
    if not messages:
        return ''
    more = t('alerts.more', n=len(messages) - 1) if len(messages) > 1 else ''
    return '! ' + _safe(messages[0])[:36 - len(more)] + more


# ------------------------------------------------------------------ communs

def build_splash():
    now  = datetime.now()
    jour = t('days')[now.weekday()]
    date_str = (f'{jour} {now.day:02d}/{now.month:02d}/{now.year}'
                f'   {now.strftime("%H:%M")}')

    def rows(out):
        _fill(out, 1, 3)
        out += _line(4,  _center('* MINITEL-HA *'), fg_c=7)
        out += _line(5,  '')
        out += _line(6,  _center(t('splash.sub')), fg_c=3)
        out += _line(7,  '')
        out += _line(8,  _center(t('splash.version', v=VERSION)), fg_c=7)
        out += _line(9,  '')
        out += _line(10, _center('3615 MAISON'), fg_c=3)
        out += _line(11, '')
        out += _line(12, _center(date_str), fg_c=3)
        _fill(out, 13, 22)
        out += _line(23, _center(t('splash.loading', s=CFG['splash_seconds'])), fg_c=7)
        out += _line(24, _center(t('splash.connected')), fg_c=0, bg_c=7)
    return _page(rows)


def build_loading():
    return bytes(_goto(24, 1) + _bg(4) + _fg(3) + _vt(t('loading').ljust(40)))


def build_time_update():
    return bytes(_goto(2, CLOCK_COL) + _bg(0) + _fg(3) + _vt(_now()))


def build_prompt(text, highlight=False):
    """Ligne 24 seule (aide de saisie ou selection en cours)."""
    out = _goto(24, 1) + (_bg(4) + _fg(3) if highlight else _bg(7) + _fg(0))
    return bytes(out + _vt(_safe(text)[:40].ljust(40)) + b'\x11')


def build_flash(text):
    """Ligne 23 seule : message clignotant (ou effacement)."""
    return bytes(_line(23, f' {text}' if text else '', fg_c=3, blink=bool(text)))


def build_confirm(text):
    return build_flash(t('dom.confirm', name=_safe(text))[1:]) + \
        build_prompt(t('dom.confirm_footer'), highlight=True)


def build_bye(text):
    return bytes(b'\x0c' + _line(12, text, fg_c=1) + b'\x14')


# ------------------------------------------------------------------ connexion

def build_login_input(typed):
    return bytes(_line(10, t('login.label') + '*' * typed + '_', fg_c=7) + b'\x11')


def build_login(typed=0, msg=''):
    def rows(out):
        _header(out, t('login.title'), t('login.prompt'))
        _fill(out, 4, 9)
        out += _line(10, t('login.label') + '*' * typed + '_', fg_c=7)
        out += _line(11, '')
        out += _line(12, msg, fg_c=1)
        _fill(out, 13, 23)
        out += _line(24, t('login.footer'), fg_c=0, bg_c=7)
    return _page(rows)


# ------------------------------------------------------------------ menu

MENU = [('d', 'domotique'), ('c', 'capteurs'), ('m', 'meteo'), ('s', 'scenes'),
        ('j', 'journal'), ('a', 'assistant'), ('r', 'archives'), ('h', 'aide')]


def build_menu(stats, selected='', show_sensors=True):
    def rows(out):
        _header(out, t('menu.title'), stats_subtitle(stats))
        row = 4
        for letter, mode in MENU:
            if mode == 'capteurs' and not show_sensors:
                continue
            name, desc = t('mode.' + mode)
            sel = selected == letter
            out += _line(row, f' {">" if sel else " "}[{letter.upper()}] {name:<12} {desc}',
                         fg_c=0 if sel else 7, bg_c=7 if sel else 0)
            row += 1
        _fill(out, row, 23)
        out += _line(24, t('menu.footer'), fg_c=0, bg_c=7)
    return _page(rows)


# ------------------------------------------------------------------ pagination

def group_by_area(entries, area_order=None):
    areas = OrderedDict()
    for a in area_order or []:
        areas[a] = []
    for e in entries:
        areas.setdefault(e.get('area', 'Autres'), []).append(e)
    return [(a, es) for a, es in areas.items() if es]


def page_count(entries):
    return max(1, -(-len(entries) // CFG['page_size']))


def page_entries(entries, page, area_order=None):
    """Entrees de la page `page`, dans l'ordre d'affichage (num local = rang+1)."""
    ordered = [e for _, es in group_by_area(entries, area_order) for e in es]
    page = max(0, min(page, page_count(entries) - 1))
    return ordered[page * CFG['page_size']:(page + 1) * CFG['page_size']]


def _rows_with_headers(entries):
    rows, last = [], None
    for n, e in enumerate(entries, 1):
        if e.get('area', 'Autres') != last:
            last = e.get('area', 'Autres')
            rows.append(('header', last, None))
        rows.append(('item', n, e))
    return rows


# ------------------------------------------------------------------ domotique

def dom_prompt(sel_num=None, dev=None):
    if not dev:
        return t('dom.hint')
    tail = t('dom.sel_adj') if devices.adjustable(dev) else t('dom.sel')
    head = f' > {sel_num} '
    return head + _safe(dev['name'])[:40 - len(head) - len(tail)].ljust(
        40 - len(head) - len(tail)) + tail


def _dom_item(row, n, d, sel=False):
    fg = 7 if not devices.is_available(d) else (2 if devices.is_active(d) else 1)
    return _line(row, f' {n}. {_safe(d["name"])[:26]:<26} {devices.label(d):>8}',
                 fg_c=0 if sel else fg, bg_c=fg if sel else 0)


def _cap_item(row, n, s, sel=False):
    return _line(row, f' {n}. {_safe(s["name"])[:23]:<23} '
                      f'{devices.sensor_value(s):>7} {_safe(s.get("unit", ""))[:4]}',
                 fg_c=0 if sel else 6, bg_c=7 if sel else 0)


def _list_rows(out, shown, item, sel_num=None, only=None):
    """Lignes 4-21 : en-tetes de piece et elements numerotes.
    only = ensemble de numeros a redessiner (mise a jour partielle)."""
    row = 4
    for kind, n, e in _rows_with_headers(shown):
        if row > 21:
            break
        if only is None:
            if kind == 'header':
                out += _line(row, f' {_safe(n).upper()}', fg_c=0, bg_c=7)
            else:
                out += item(row, n, e, n == sel_num)
        elif kind == 'item' and n in only:
            out += item(row, n, e, n == sel_num)
        row += 1
    return row


def build_stats_line(stats):
    """Ligne 2 seule (ON/OFF + heure), curseur rendu en 24/40."""
    return bytes(_line(2, stats_subtitle(stats), fg_c=3) + _goto(24, 40))


def build_dom_update(devs, stats, page, nums, sel_num=None, sel_dev=None,
                     flash=None, area_order=None):
    """Redessine seulement les appareils `nums`, la ligne 2 et la saisie."""
    out = bytearray(_line(2, stats_subtitle(stats), fg_c=3))
    _list_rows(out, page_entries(devs, page, area_order), _dom_item, sel_num, set(nums))
    if flash is not None:
        out += build_flash(flash)
    out += build_prompt(dom_prompt(sel_num, sel_dev), highlight=bool(sel_dev))
    return bytes(out)


def build_cap_update(sens, page, nums, sel_num=None, area_order=None):
    out = bytearray()
    _list_rows(out, page_entries(sens, page, area_order), _cap_item, sel_num, set(nums))
    return bytes(out + _goto(24, 40))


def build_domotique(devs, stats, page=0, sel_num=None, sel_dev=None,
                    flash='', area_order=None):
    shown = page_entries(devs, page, area_order)

    def rows(out):
        _header(out, CFG['title'], stats_subtitle(stats))
        row = _list_rows(out, shown, _dom_item, sel_num)
        _fill(out, row, 21)
        out += _line(22, t('dom.pages', p=min(page, page_count(devs) - 1) + 1,
                           t=page_count(devs)), fg_c=7)
        out += _line(23, f' {flash}' if flash else '', fg_c=3, blink=bool(flash))
        out += build_prompt(dom_prompt(sel_num, sel_dev), highlight=bool(sel_dev))
    out = bytearray(b'\x0c\x14')
    rows(out)
    return bytes(out)


# ------------------------------------------------------------------ capteurs

def build_capteurs(sens, page=0, sel_num=None, flash='', area_order=None):
    shown = page_entries(sens, page, area_order)

    def rows(out):
        _header(out, t('cap.title'), f' {len(sens)}   {_now()}')
        if not sens:
            out += _line(4, '')
            out += _line(5, t('cap.empty'), fg_c=7)
            row = 6
        else:
            row = _list_rows(out, shown, _cap_item, sel_num)
        _fill(out, row, 21)
        out += _line(22, t('dom.pages', p=min(page, page_count(sens) - 1) + 1,
                           t=page_count(sens)), fg_c=7)
        out += _line(23, f' {flash}' if flash else '', fg_c=3, blink=bool(flash))
        out += _line(24, t('cap.footer'), fg_c=0, bg_c=7)
    return _page(rows)


# ------------------------------------------------------------------ graphique

GRAPH_COLS = 80          # 40 caracteres x 2 pixels
GRAPH_ROWS = 16          # lignes 5 a 20, 3 pixels chacune


def bucket(points, now, hours=24, n=GRAPH_COLS):
    """n valeurs regulierement espacees : derniere valeur connue a chaque pas."""
    start = now - timedelta(hours=hours)
    span  = (now - start) / n
    pts   = sorted(points)
    out, i, last = [], 0, None
    for k in range(n):
        end = start + span * (k + 1)
        while i < len(pts) and pts[i][0] <= end:
            last = pts[i][1]
            i += 1
        out.append(last)
    return out


def mosaic(px):
    """Caractere semi-graphique G1 a partir de 6 pixels
    [haut-g, haut-d, milieu-g, milieu-d, bas-g, bas-d]."""
    code = 0x20
    for bit, on in enumerate(px[:5]):
        if on:
            code |= 1 << bit
    if px[5]:
        code |= 0x40
    return code


def graph_rows(values, rows=GRAPH_ROWS):
    """Octets G1 de chaque ligne du graphique (aire sous la courbe)."""
    known = [v for v in values if v is not None]
    height = rows * 3
    if not known:
        return [bytes([0x20] * (len(values) // 2)) for _ in range(rows)]
    lo, hi = min(known), max(known)
    cols = []
    for v in values:
        if v is None:
            cols.append(0)
        elif hi == lo:
            cols.append(height // 2)
        else:
            cols.append(1 + round((v - lo) / (hi - lo) * (height - 1)))
    out = []
    for r in range(rows):
        line = bytearray()
        for c in range(0, len(cols) - 1, 2):
            px = []
            for dy in range(3):
                y = r * 3 + dy                      # 0 = haut
                px += [y >= height - cols[c], y >= height - cols[c + 1]]
            line.append(mosaic(px))
        out.append(bytes(line))
    return out


def _fmt(v, unit=''):
    if v is None:
        return '--'
    v = round(v, 1)
    return f'{int(v) if v == int(v) else v}{_safe(unit)}'


def build_graph(sensor, values):
    known = [v for v in values if v is not None]
    unit  = sensor.get('unit', '')

    def rows(out):
        _header(out, t('graph.title'), f' {_safe(sensor["name"])[:38]}')
        if not known:
            _fill(out, 4, 10)
            out += _line(11, t('graph.nodata'), fg_c=1)
            _fill(out, 12, 23)
        else:
            out += _line(4, t('graph.max', v=_fmt(max(known), unit)), fg_c=3)
            for i, g in enumerate(graph_rows(values)):
                out += _goto(5 + i, 1) + _bg(0) + _fg(6) + SO + g + SI
            out += _line(21, t('graph.min', v=_fmt(min(known), unit)), fg_c=3)
            out += _line(22, t('graph.axis'), fg_c=7)
            out += _line(23, t('graph.stats', avg=_fmt(sum(known) / len(known), unit),
                               cur=_fmt(known[-1], unit)), fg_c=3)
        out += _line(24, t('graph.footer'), fg_c=0, bg_c=7)
    return _page(rows)


# ------------------------------------------------------------------ meteo

def build_meteo(meteo_data):
    now = datetime.now().strftime('%d/%m  %H:%M')
    forecasts = meteo_data.get('forecast', [])
    ext       = meteo_data.get('ext', {})

    def rows(out):
        _header(out, t('meteo.title'), t('meteo.reading', t=now))
        row = 4
        if forecasts:
            out += _line(row, t('meteo.forecast'), fg_c=0, bg_c=7); row += 1
            out += _line(row, t('meteo.cols'), fg_c=7); row += 1
            for f in forecasts[:4]:
                if row > 9:
                    break
                tlow   = str(f.get('tlow') or '')
                temp   = str(f.get('temp', '?'))
                temp_s = f'{tlow}>{temp}' if tlow else temp
                out += _line(row,
                             f'  {str(f.get("label", "?"))[:8]:<8} '
                             f'{_safe(f.get("cond", "?"))[:10]:<10} '
                             f'{temp_s:>5}C {str(f.get("precip", "--")):>4}', fg_c=3)
                row += 1
        else:
            out += _line(row, t('meteo.outside'), fg_c=0, bg_c=7); row += 1
            out += _line(row, t('meteo.temp', v=_v(ext.get('temp'))), fg_c=3); row += 1
            out += _line(row, t('meteo.hum', v=_v(ext.get('hum'))), fg_c=3); row += 1
        _fill(out, row, 9)
        out += _line(10, ' ' + '-' * 38, fg_c=7)
        if forecasts:
            out += _line(11, t('meteo.ext', t=_v(ext.get('temp')), h=_v(ext.get('hum'))),
                         fg_c=3)
        else:
            out += _line(11, t('meteo.inside'), fg_c=0, bg_c=7)
        out += _line(12, t('meteo.rooms'), fg_c=7)
        row = 13
        for room in meteo_data.get('rooms', [])[:10]:
            out += _line(row,
                         f'  {_safe(room.get("name", "?"))[:14]:<14} '
                         f'{_v(room.get("temp"), "--"):>6}C  '
                         f'{_v(room.get("hum"), "--"):>5}%', fg_c=3)
            row += 1
        _fill(out, row, 23)
        out += _line(24, t('meteo.footer'), fg_c=0, bg_c=7)
    return _page(rows)


# ------------------------------------------------------------------ scenes

def build_scenes(scenes, scripts, buf='', flash_msg=''):
    def rows(out):
        _header(out, t('scenes.title'), t('scenes.count', s=len(scenes), c=len(scripts)))
        row, n = 4, 1
        for label, items in ((t('scenes.scenes'), scenes), (t('scenes.scripts'), scripts)):
            if not items or row > 20:
                continue
            out += _line(row, label, fg_c=0, bg_c=7)
            row += 1
            for sc in items:
                if row > 22:
                    break
                sel = buf == str(n)
                out += _line(row, f' {n}. {_safe(sc["name"])[:35]}',
                             fg_c=0 if sel else 7, bg_c=7 if sel else 0)
                row += 1
                n += 1
        _fill(out, row, 22)
        out += _line(23, f' {flash_msg}' if flash_msg else '', fg_c=3, blink=bool(flash_msg))
        out += _line(24, t('scenes.footer'), fg_c=0, bg_c=7)
    return _page(rows)


# ------------------------------------------------------------------ journal

JOURNAL_LPP = 19


def journal_pages(entries):
    return max(1, -(-len(entries) // JOURNAL_LPP))


def build_journal(entries, page=0):
    entries = list(reversed(list(entries)))
    total   = journal_pages(entries)
    page    = max(0, min(page, total - 1))
    shown   = entries[page * JOURNAL_LPP:(page + 1) * JOURNAL_LPP]

    def rows(out):
        _header(out, t('journal.title'),
                t('journal.count', n=len(entries), p=page + 1, t=total))
        row = 4
        for e in shown:
            ok = e.get('ok')
            out += _line(row,
                         f' {journal.short_ts(e.get("ts")):<5} '
                         f'{_safe(e.get("name", "?"))[:26]:<26} '
                         f'[{"OK" if ok else "ERR"}]',
                         fg_c=2 if ok else 1)
            row += 1
        _fill(out, row, 23)
        out += _line(24, t('journal.footer'), fg_c=0, bg_c=7)
    return _page(rows)


# ------------------------------------------------------------------ assistant

ASSIST_MAX = 35   # longueur max d'une question saisie sur le Minitel


def build_assist_input_line(buf, flash=''):
    if flash:
        out = (_goto(23, 1) + _bg(0) + _fg(3) + _blink_on()
               + _vt(_safe(flash)[:40].ljust(40)) + _blink_off())
    elif buf:
        out = (_goto(23, 1) + _bg(0) + _fg(7)
               + _vt(f' > {_safe(buf)[:ASSIST_MAX]}_'.ljust(40)))
    else:
        out = _goto(23, 1) + _bg(0) + _fg(7) + _vt(t('assist.prompt').ljust(40))
    return bytes(out + _goto(23, min(4 + len(buf), 39)))


def build_assistant(history, agents, cur_agent_idx=0, buf='', flash_msg=''):
    if agents and 0 <= cur_agent_idx < len(agents):
        agent_name = _safe(agents[cur_agent_idx].get('name', 'Agent'))
    else:
        agent_name = 'Assistant HA'
    lines = []
    for entry in history:
        q = _safe(entry.get('q', ''))
        r = _safe(entry.get('r', ''))
        while q:
            lines.append(('q', f'> {q[:37]}')); q = q[37:]
        while r:
            lines.append(('r', f'  {r[:38]}')); r = r[38:]
    out = bytearray(b'\x0c\x14')
    _header(out, t('assist.title'), t('assist.agent', name=agent_name[:30]))
    row, max_row = 4, 21
    for typ, txt in lines[-(max_row - row + 1):]:
        out += _line(row, txt, fg_c=7 if typ == 'q' else 3)
        row += 1
    _fill(out, row, max_row)
    out += _line(22, ' ' + '-' * 38, fg_c=7)
    out += _line(24, t('assist.footer', agent=t('assist.footer_agent') if len(agents) > 1
                       else ' ' * len(t('assist.footer_agent'))), fg_c=0, bg_c=7)
    out += build_assist_input_line(buf, flash_msg)
    return bytes(out + b'\x11')


# ------------------------------------------------------------------ archives

ARCH_PAGE = 9


def build_archives(files, idx=0, flash='', folder='static/archives/'):
    if not files:
        def rows_empty(out):
            _header(out, t('arch.title'), t('arch.none'), fg_sub=1)
            out += _line(4, '')
            out += _line(5, t('arch.drop1'), fg_c=7)
            out += _line(6, t('arch.drop2', folder=folder), fg_c=3)
            _fill(out, 7, 23)
            out += _line(24, t('arch.footer_empty'), fg_c=0, bg_c=7)
        return _page(rows_empty)
    idx         = max(0, min(idx, len(files) - 1))
    total_pages = max(1, -(-len(files) // ARCH_PAGE))
    start       = (idx // ARCH_PAGE) * ARCH_PAGE

    def rows(out):
        _header(out, t('arch.title'),
                t('arch.count', n=len(files), p=idx // ARCH_PAGE + 1, t=total_pages))
        out += _line(4, t('arch.list'), fg_c=0, bg_c=7)
        row = 5
        for i, f in enumerate(files[start:start + ARCH_PAGE]):
            sel = start + i == idx
            out += _line(row,
                         f' {">" if sel else " "}{i + 1}. '
                         f'{_safe(f.get("name", "?"))[:30]} ({f.get("size", 0) // 1024}k)',
                         fg_c=0 if sel else 7, bg_c=7 if sel else 0)
            row += 1
        _fill(out, row, 22)
        if flash:
            out += _line(23, f' {_safe(flash)[:38]}', fg_c=3, blink=True)
        else:
            out += _line(23, t('arch.sel', name=_safe(files[idx].get('name', '?'))[:26]), fg_c=3)
        out += _line(24, t('arch.footer'), fg_c=0, bg_c=7)
    return _page(rows)


# ------------------------------------------------------------------ aide

def help_pages():
    return t('aide.general')


def build_aide(current_mode='domotique', aide_page=0, general=False):
    def rows(out):
        if general:
            pages = help_pages()
            idx   = max(0, min(aide_page, len(pages) - 1))
            title, lines = pages[idx]
            _header(out, t('aide.title_gen'), t('aide.page', p=idx + 1, t=len(pages)))
            out += _line(4, title, fg_c=0, bg_c=7)
            row, footer = 5, t('aide.footer_gen')
        else:
            lines = t('aide.ctx').get(current_mode, t('aide.ctx_default'))
            modes = {m for _, m in MENU}
            name = t('mode.' + current_mode)[0] if current_mode in modes else current_mode
            _header(out, t('aide.title'), t('aide.mode', m=_safe(name).upper()[:28]))
            row, footer = 4, t('aide.footer')
        for line in lines:
            if row > 23:
                break
            out += _line(row, line, fg_c=7)
            row += 1
        _fill(out, row, 23)
        out += _line(24, footer, fg_c=0, bg_c=7)
    return _page(rows)
