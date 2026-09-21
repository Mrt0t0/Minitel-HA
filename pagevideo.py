from datetime import datetime
from collections import OrderedDict

VERSION   = '1.1'
PAGE_SIZE = 9

CFG = {
    'title':          '  MINITEL-HA  DOMOTIQUE  -- MrT0t0  ',
    'page_size':      9,
    'date_format':    '%H:%M',
    'show_sensors':   True,
    'splash_seconds': 7,
}

_JOURS_FR = ['LUNDI', 'MARDI', 'MERCREDI', 'JEUDI',
             'VENDREDI', 'SAMEDI', 'DIMANCHE']

_TRANSLIT = str.maketrans({
    '\u2019': "'", '\u2018': "'", '\u201c': '"', '\u201d': '"',
    '\u2013': '-', '\u2014': '-', '\u2026': '...', '\u2022': '*',
    '\u00a0': ' ', '\u00ab': '"', '\u00bb': '"', '\u2039': '<',
    '\u203a': '>', '\u00ad': '-', '\u2212': '-', '\u00d7': 'x',
    '\u00f7': '/', '\u20ac': 'E', '\u00b2': '2', '\u00b3': '3',
})

_ACCENTS = str.maketrans(
    'àâäéèêëîïôöùûüçÀÂÄÉÈÊËÎÏÔÖÙÛÜÇ',
    'aaaeeeeiioouuucAAAEEEEIIOOUUUC')


def _goto(r, c):  return bytes([0x1f, 0x40 + r, 0x40 + c])
def _fg(c):       return bytes([0x1b, 0x40 + c])
def _bg(c):       return bytes([0x1b, 0x50 + c])
def _blink_on():  return bytes([0x1b, 0x48])
def _blink_off(): return bytes([0x1b, 0x49])


def _center(text, width=40):
    return text.center(width)[:width]


def _safe(t):
    """Prepare une chaine pour l'encodage latin-1 en preservant les accents."""
    t = str(t).translate(_TRANSLIT)
    out = []
    for ch in t:
        try:
            ch.encode('latin-1')
            out.append(ch)
        except UnicodeEncodeError:
            out.append('?')
    return ''.join(out)


def _clean(t):
    """Retire les accents pour les zones ASCII strict."""
    return str(t).translate(_TRANSLIT).translate(_ACCENTS)


def _line(row, text, fg_c=7, bg_c=0, blink=False):
    out = _goto(row, 1) + _bg(bg_c) + _fg(fg_c)
    if blink:
        out += _blink_on()
    out += _safe(text)[:40].ljust(40).encode('latin-1', 'replace')
    if blink:
        out += _blink_off()
    return out


def build_input_line(buf, page=0, total_pages=1):
    if buf:
        out  = _goto(24, 1) + _bg(4) + _fg(3)
        text = f' > {buf.upper()}_  (+ENVOI=valider  DEL=annuler)'
    else:
        out  = _goto(24, 1) + _bg(7) + _fg(0)
        text = ' Chiffre+ENVOI=toggle  *=eteindre tout '
    out += text[:40].ljust(40).encode('latin-1', 'replace')
    return bytes(out + b'\x11')


def build_assist_input_line(buf, flash=''):
    if flash:
        out = (_goto(23, 1) + _bg(0) + _fg(3) + _blink_on()
               + _safe(flash)[:40].ljust(40).encode('latin-1', 'replace')
               + _blink_off())
    elif buf:
        out = (_goto(23, 1) + _bg(0) + _fg(7)
               + f' > {_clean(buf)[:35]}_'.ljust(40).encode('latin-1', 'replace'))
    else:
        out = (_goto(23, 1) + _bg(0) + _fg(7)
               + b' Tapez votre question puis ENVOI        ')
    return bytes(out + _goto(23, min(4 + len(buf), 39)))


def group_by_area(devices, area_order=None):
    areas = OrderedDict()
    if area_order:
        for a in area_order:
            areas[a] = []
    for d in devices:
        areas.setdefault(d.get('area', 'Autres'), []).append(d)
    return [(a, devs) for a, devs in areas.items() if devs]


def build_display_items(devices, area_order=None):
    items = []
    for area, devs in group_by_area(devices, area_order):
        items.append({'type': 'header', 'area': area})
        for d in devs:
            items.append({'type': 'device', 'device': d})
    return items


def paginate(items, page):
    dev_items   = [i for i in items if i['type'] == 'device']
    total_pages = max(1, -(-len(dev_items) // CFG['page_size']))
    page        = max(0, min(page, total_pages - 1))
    start       = page * CFG['page_size']
    in_page     = {id(d['device'])
                   for d in dev_items[start:start + CFG['page_size']]}
    result, n, seen, last_area = [], 1, False, None
    for item in items:
        if item['type'] != 'device':
            continue
        if id(item['device']) in in_page:
            seen = True
            area = item['device'].get('area', 'Autres')
            if area != last_area:
                result.append({'type': 'header', 'area': area})
                last_area = area
            result.append({'type': 'device', 'local_num': n,
                           'device': item['device']})
            n += 1
        elif seen:
            break
    return result, total_pages


def build_splash():
    now  = datetime.now()
    jour = _JOURS_FR[now.weekday()]
    date_str = (f'{jour} {now.day:02d}/{now.month:02d}/{now.year}'
                f'   {now.strftime("%H:%M")}')
    out = bytearray(b'\x0c\x14')
    for r in range(1, 4):
        out += _line(r, '')
    out += _line(4,  _center('* MINITEL-HA *'), fg_c=7)
    out += _line(5,  '')
    out += _line(6,  _center('Domotique Home Assistant'), fg_c=3)
    out += _line(7,  '')
    out += _line(8,  _center(f'Version {VERSION}'), fg_c=7)
    out += _line(9,  '')
    out += _line(10, _center('3615 MAISON'), fg_c=3)
    out += _line(11, '')
    out += _line(12, _center(date_str), fg_c=3)
    for r in range(13, 23):
        out += _line(r, '')
    out += _line(23, _center(f'Chargement en {CFG.get("splash_seconds", 7)}s...'), fg_c=7)
    out += _line(24, _center('Connexion etablie'), fg_c=0, bg_c=7)
    return bytes(out)


def build_loading():
    return bytes(_goto(24, 1) + _bg(4) + _fg(3)
                 + b' Chargement...                          ')


def build_time_update():
    now = datetime.now().strftime(CFG['date_format'])
    return bytes(_goto(2, 33) + _fg(3) + now.encode('latin-1', 'replace'))


def _header(out, title, subtitle, fg_sub=3):
    out += _line(1, _clean(title)[:40], fg_c=0, bg_c=7)
    out += _line(2, subtitle, fg_c=fg_sub)
    out += _line(3, ' ' + '=' * 38, fg_c=7)
    return out


def build_menu(stats, selected=''):
    MODES = [
        ('D', 'Domotique', 'Controle appareils    '),
        ('M', 'Meteo',     'Temperatures/Previsions'),
        ('S', 'Scenes',    'Scenes et scripts     '),
        ('J', 'Journal',   'Historique des actions'),
        ('A', 'Assistant', 'IA Home Assistant     '),
        ('R', 'aRchives',  'Pages Videotex static '),
        ('H', 'Aide',      'Guide utilisation     '),
    ]
    now = datetime.now().strftime(CFG['date_format'])
    out = bytearray(b'\x0c\x14')
    out = _header(out, '   MINITEL-HA   MENU PRINCIPAL  ',
                  f' ON:{stats["on"]:2d} OFF:{stats["off"]:2d}/{stats["total"]:2d}   {now}')
    row = 4
    for letter, name, desc in MODES:
        sel = selected.upper() == letter
        out += _line(row, f' {">" if sel else " "}[{letter}] {name:<12} {desc}',
                     fg_c=0 if sel else 7, bg_c=7 if sel else 0)
        row += 1
    while row <= 23:
        out += _line(row, '')
        row += 1
    out += _line(24, ' Lettre + ENVOI = acceder service   ', fg_c=0, bg_c=7)
    return bytes(out + b'\x11' + _goto(24, 40))


def build(devices, sensors, stats, page=0, buf='', area_order=None, flash_msg=''):
    items, total_pages = paginate(build_display_items(devices, area_order), page)
    now = datetime.now().strftime(CFG['date_format'])
    out = bytearray(b'\x0c\x14')
    out = _header(out, _clean(CFG['title'])[:40],
                  f' ON:{stats["on"]:2d} OFF:{stats["off"]:2d}/{stats["total"]:2d}   {now}')
    row = 4
    for item in items:
        if row > 21:
            break
        if item['type'] == 'header':
            out += _line(row, f' {_clean(item["area"]).upper()}', fg_c=0, bg_c=7)
        else:
            d = item['device']
            is_on = d['state'] == 'on'
            out += _line(row,
                         f' {item["local_num"]}. {_clean(d["name"])[:29]:<29}'
                         f'{" ON " if is_on else " OFF"}',
                         fg_c=2 if is_on else 1)
        row += 1
    while row <= 21:
        out += _line(row, '')
        row += 1
    out += _line(22, f' Page {page+1}/{total_pages}  SUITE> <RETOUR  SOMMAIRE', fg_c=7)
    out += _line(23, f' {_clean(flash_msg)}' if flash_msg else '',
                 fg_c=3, blink=bool(flash_msg))
    out += build_input_line(buf, page, total_pages)
    return bytes(out)


def build_meteo(meteo_data):
    now = datetime.now().strftime('%d/%m  %H:%M')
    out = bytearray(b'\x0c\x14')
    out = _header(out, '   MINITEL-HA   METEO           ', f' Releve : {now}')
    forecasts = meteo_data.get('forecast', [])
    ext       = meteo_data.get('ext', {})
    row = 4
    if forecasts:
        out += _line(row, ' PREVISIONS METEO', fg_c=0, bg_c=7); row += 1
        out += _line(row, '  Date     Condition  Temp  Pluie', fg_c=7); row += 1
        for f in forecasts[:4]:
            if row > 9:
                break
            tlow   = str(f.get('tlow') or '')
            temp   = str(f.get('temp', '?'))
            temp_s = f'{tlow}>{temp}' if tlow else temp
            out += _line(row,
                         f'  {str(f.get("label", "?"))[:8]:<8} '
                         f'{str(f.get("cond", "?"))[:10]:<10} '
                         f'{temp_s:>5}C {str(f.get("precip", "--")):>4}', fg_c=3)
            row += 1
    else:
        out += _line(row, ' EXTERIEUR', fg_c=0, bg_c=7); row += 1
        out += _line(row, f'  Temperature : {str(ext.get("temp", "?")):>6} C', fg_c=3); row += 1
        out += _line(row, f'  Humidite    : {str(ext.get("hum", "?")):>6} %', fg_c=3); row += 1
    while row <= 9:
        out += _line(row, '')
        row += 1
    out += _line(10, ' ' + '-' * 38, fg_c=7)
    if forecasts:
        out += _line(11, f' Ext: {ext.get("temp", "?")}C  {ext.get("hum", "?")}%   PIECES', fg_c=3)
    else:
        out += _line(11, ' INTERIEUR PAR PIECE', fg_c=0, bg_c=7)
    out += _line(12, '  Piece              Temp    Hum  ', fg_c=7)
    row = 13
    for room in meteo_data.get('rooms', [])[:8]:
        if row > 22:
            break
        out += _line(row,
                     f'  {_clean(room.get("name", "?"))[:14]:<14} '
                     f'{str(room.get("temp", "N/A")):>6}C  '
                     f'{str(room.get("hum", "N/A")):>5}%', fg_c=3)
        row += 1
    while row <= 23:
        out += _line(row, '')
        row += 1
    out += _line(24, ' SOMMAIRE=menu  D+ENVOI=Domotique   ', fg_c=0, bg_c=7)
    return bytes(out + b'\x11' + _goto(24, 40))


def build_scenes(scenes, scripts, buf='', flash_msg=''):
    out = bytearray(b'\x0c\x14')
    out = _header(out, '   MINITEL-HA   SCENES          ',
                  f' {len(scenes)} scene(s)   {len(scripts)} script(s)')
    row, n = 4, 1
    for label, items in (('SCENES', scenes), ('SCRIPTS', scripts)):
        if not items or row > 20:
            continue
        out += _line(row, f' {label}', fg_c=0, bg_c=7)
        row += 1
        for sc in items:
            if row > 20:
                break
            sel = buf == str(n)
            out += _line(row, f' {n}. {_clean(sc["name"])[:35]}',
                         fg_c=0 if sel else 7, bg_c=7 if sel else 0)
            row += 1
            n += 1
    while row <= 22:
        out += _line(row, '')
        row += 1
    out += _line(23, f' {_clean(flash_msg)}' if flash_msg else '',
                 fg_c=3, blink=bool(flash_msg))
    out += _line(24, ' Num+ENVOI=activer  SOMMAIRE=menu   ', fg_c=0, bg_c=7)
    return bytes(out + b'\x11' + _goto(24, 40))


def build_journal(journal, page=0):
    LPP     = 17
    entries = list(reversed(list(journal)))
    total   = max(1, -(-len(entries) // LPP))
    page    = max(0, min(page, total - 1))
    shown   = entries[page * LPP:(page + 1) * LPP]
    out = bytearray(b'\x0c\x14')
    out = _header(out, '   MINITEL-HA   JOURNAL         ',
                  f' {len(entries)} actions  Page {page+1}/{total}')
    row = 4
    for e in shown:
        if row > 22:
            break
        out += _line(row,
                     f' {e["ts"]} {_clean(e.get("name", "?"))[:22]:<22} '
                     f'[{"OK" if e.get("ok") else "ERR"}]',
                     fg_c=2 if e.get('ok') else 1)
        row += 1
    while row <= 23:
        out += _line(row, '')
        row += 1
    out += _line(24, ' SUITE=page suiv  SOMMAIRE=menu     ', fg_c=0, bg_c=7)
    return bytes(out + b'\x11' + _goto(24, 40))


def build_assistant(history, agents, cur_agent_idx=0, buf='', flash_msg=''):
    if agents and 0 <= cur_agent_idx < len(agents):
        agent_name = _clean(agents[cur_agent_idx].get('name', 'Agent'))
    else:
        agent_name = 'Assistant HA'
    out = bytearray(b'\x0c\x14')
    out = _header(out, '   MINITEL-HA   ASSISTANT IA    ', f' Agent: {agent_name[:30]}')
    lines = []
    for entry in history:
        q = _clean(entry.get('q', ''))
        r = _safe(entry.get('r', ''))
        while q:
            lines.append(('q', f'> {q[:37]}')); q = q[37:]
        while r:
            lines.append(('r', f'  {r[:38]}')); r = r[38:]
    row, max_row = 4, 21
    for typ, txt in lines[-(max_row - row + 1):]:
        if row > max_row:
            break
        out += _line(row, txt, fg_c=7 if typ == 'q' else 3)
        row += 1
    while row <= max_row:
        out += _line(row, '')
        row += 1
    out += _line(22, ' ' + '-' * 38, fg_c=7)
    out += build_assist_input_line(buf, flash_msg)
    out += _line(24, f' ENVOI=envoyer {"SUITE=agent" if len(agents) > 1 else "           "} SOMM=menu',
                 fg_c=0, bg_c=7)
    return bytes(out + b'\x11')


def build_archives(files, idx=0, flash=''):
    out = bytearray(b'\x0c\x14')
    if not files:
        out = _header(out, '   MINITEL-HA   ARCHIVES .VDT   ',
                      ' Aucun fichier .vdt disponible', fg_sub=1)
        out += _line(5, ' Deposer des fichiers .vdt dans', fg_c=7)
        out += _line(6, ' le dossier static/archives/', fg_c=3)
        for r in range(7, 24):
            out += _line(r, '')
        out += _line(24, ' SOMMAIRE=menu                      ', fg_c=0, bg_c=7)
        return bytes(out + b'\x11' + _goto(24, 40))
    PAGE        = 9
    total       = len(files)
    file_page   = idx // PAGE
    total_pages = max(1, -(-total // PAGE))
    start       = file_page * PAGE
    out = _header(out, '   MINITEL-HA   ARCHIVES .VDT   ',
                  f' {total} fichier(s)   Page {file_page+1}/{total_pages}')
    out += _line(4, ' FICHIERS VIDEOTEX DISPONIBLES  ', fg_c=0, bg_c=7)
    row = 5
    for i, f in enumerate(files[start:start + PAGE]):
        local_n = start + i
        sel     = local_n == idx
        out += _line(row,
                     f' {">" if sel else " "}{local_n+1:2d}. '
                     f'{_clean(f.get("name", "?"))[:32]} ({f.get("size", 0)//1024}k)',
                     fg_c=0 if sel else 7, bg_c=7 if sel else 0)
        row += 1
    while row <= 22:
        out += _line(row, '')
        row += 1
    if flash:
        out += _line(23, f' {_clean(flash)[:38]}', fg_c=3, blink=True)
    else:
        out += _line(23, f' Selection: {_clean(files[idx].get("name", "?"))[:24]}', fg_c=3)
    out += _line(24, ' ENVOI=ouvrir  SUITE/RET=nav  SOMM  ', fg_c=0, bg_c=7)
    return bytes(out + b'\x11' + _goto(24, 40))


_AIDE_GENERAL_PAGES = [
    {'title': ' AIDE GENERALE - NAVIGATION',
     'lines': [' SOMMAIRE  : Menu principal',
               ' GUIDE     : Aide contextuelle du mode',
               '   + GUIDE : Aide generale (cette page)',
               ' SUITE  >  : Page / fichier suivant',
               ' RETOUR <  : Page / fichier precedent',
               ' ANNULATION: Annuler / retour',
               ' CORRECTION: Effacer la saisie',
               ' Lettre+ENVOI : Changer de mode',
               '   D M S J A R H']},
    {'title': ' AIDE - MODE DOMOTIQUE [D]',
     'lines': [' 1 a 9     : Selectionner un appareil',
               ' ENVOI     : Basculer ON/OFF',
               ' SUITE     : Page suivante',
               ' RETOUR    : Page precedente',
               ' *         : Tout eteindre',
               ' 0         : Journal des actions']},
    {'title': ' AIDE - MODE METEO [M]',
     'lines': [' Previsions J/J+1/J+2 + temp pieces',
               ' Configurer dans config.yaml :',
               '   meteo.weather_entity: weather.xxx']},
    {'title': ' AIDE - MODE SCENES [S]',
     'lines': [' Chiffre + ENVOI : Activer scene',
               ' Configurer : [scenes] et [scripts]',
               ' dans config.yaml']},
    {'title': ' AIDE - MODE ASSISTANT [A]',
     'lines': [' Saisir votre question + ENVOI',
               ' SUITE     : Changer d agent IA',
               ' ANNUL/DEL : Effacer la saisie',
               ' Ex: Allume la lumiere du salon',
               '     Quel temps fait-il ?']},
    {'title': ' AIDE - MODE ARCHIVES [R]',
     'lines': [' Pages Videotex statiques (.vdt)',
               ' Dossier : static/archives/',
               ' SUITE / RETOUR : Naviguer la liste',
               ' Chiffre + ENVOI : Ouvrir et lire',
               ' ANNULATION : Retour a la liste']},
    {'title': ' AIDE - MODE JOURNAL [J]',
     'lines': [' Historique des 50 dernieres actions.',
               ' SUITE / RETOUR : Changer de page',
               ' SOMMAIRE       : Menu principal']},
]

_AIDE_CTX = {
    'domotique': [' 1-9+ENVOI=toggle  SUITE/RET=pages',
                  ' *=tout eteindre  0=journal',
                  ' Lettre+ENVOI=mode  GUIDE=aide gen'],
    'meteo':     [' Previsions + temp/hum par piece',
                  ' Config: meteo.weather_entity',
                  ' GUIDE=aide generale'],
    'scenes':    [' Chiffre+ENVOI=activer',
                  ' GUIDE=aide generale'],
    'assistant': [' Saisir+ENVOI=envoyer  SUITE=agent',
                  ' ANNUL/DEL=effacer  GUIDE=aide gen'],
    'archives':  [' SUITE/RETOUR=naviguer  ENVOI=ouvrir',
                  ' ANNUL=retour liste  GUIDE=aide gen'],
    'journal':   [' SUITE/RETOUR=pages  GUIDE=aide gen'],
}


def build_aide(current_mode='domotique', aide_page=0, general=False):
    out = bytearray(b'\x0c\x14')
    if general:
        total = len(_AIDE_GENERAL_PAGES)
        idx   = max(0, min(aide_page, total - 1))
        pg    = _AIDE_GENERAL_PAGES[idx]
        out = _header(out, '   MINITEL-HA   AIDE GENERALE   ',
                      f' Page {idx+1}/{total}  SUITE=suivante')
        out += _line(4, _clean(pg['title']), fg_c=0, bg_c=7)
        row   = 5
        lines = pg['lines']
        footer = ' SUITE=suivante  SOMM=fermer        '
    else:
        lines = _AIDE_CTX.get(current_mode, [' GUIDE = aide generale'])
        out = _header(out, '   MINITEL-HA   AIDE            ',
                      f' Mode : {_clean(current_mode).upper()[:28]}')
        row    = 4
        footer = ' GUIDE=aide-gen  SOMMAIRE=fermer    '
    for line in lines:
        if row > 23:
            break
        out += _line(row, _clean(line), fg_c=7)
        row += 1
    while row <= 23:
        out += _line(row, '')
        row += 1
    out += _line(24, footer, fg_c=0, bg_c=7)
    return bytes(out + b'\x11' + _goto(24, 40))
