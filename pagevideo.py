from datetime    import datetime
from collections import OrderedDict

VERSION   = "1.0"
PAGE_SIZE = 9

CFG = {
    'title':          "  MINITEL-HA  DOMOTIQUE  -- MrT0t0  ",
    'page_size':      9,
    'date_format':    '%H:%M',
    'show_sensors':   True,
    'splash_seconds': 5,
}

_JOURS_FR = ['LUNDI','MARDI','MERCREDI','JEUDI','VENDREDI','SAMEDI','DIMANCHE']

def _goto(r, c): return bytes([0x1f, 0x40 + r, 0x40 + c])
def _fg(c):      return bytes([0x1b, 0x40 + c])
def _bg(c):      return bytes([0x1b, 0x50 + c])
def _blink_on():  return bytes([0x1b, 0x48])
def _blink_off(): return bytes([0x1b, 0x49])

def _center(text, width=40):
    return text.center(width)[:width]

def _line(row, text, fg_c=7, bg_c=0, blink=False):
    out  = _goto(row, 1) + _bg(bg_c) + _fg(fg_c)
    if blink: out += _blink_on()
    out += text[:40].ljust(40).encode('latin-1', 'replace')
    if blink: out += _blink_off()
    return out

_TRANSLIT = str.maketrans({
    '\u2019': "'",  '\u2018': "'",  '\u201c': '"',  '\u201d': '"',
    '\u2013': '-',  '\u2014': '-',  '\u2026': '...','\u00b7': '.',
    '\u2022': '*',  '\u00a0': ' ',  '\u00ab': '"',  '\u00bb': '"',
    '\u2018': "'",  '\u2039': '<',  '\u203a': '>',  '\u00ad': '-',
    '\u2212': '-',  '\u00d7': 'x',  '\u00f7': '/',  '\u00b0': ' ',
    '\u00b2': '2',  '\u00b3': '3',  '\u00b9': '1',  '\u20ac': 'E',
    '\u00a3': 'L',  '\u00a7': 'S',  '\u00b5': 'u',  '\u00bc': '1/4',
    '\u00bd': '1/2','\u00be': '3/4',
})

_LATIN1_OK = set(chr(i) for i in range(0x20, 0x100)
                 if i not in (0x7f, 0x80, 0x81, 0x82, 0x83, 0x84, 0x85,
                              0x86, 0x87, 0x88, 0x89, 0x8a, 0x8b, 0x8c, 0x8d,
                              0x8e, 0x8f, 0x90, 0x91, 0x92, 0x93, 0x94, 0x95,
                              0x96, 0x97, 0x98, 0x99, 0x9a, 0x9b, 0x9c, 0x9d,
                              0x9e, 0x9f))

def _safe(t):
    t = t.translate(_TRANSLIT)
    result = []
    for ch in t:
        if ch in _LATIN1_OK:
            result.append(ch)
        else:
            try:
                ch.encode('latin-1')
                result.append(ch)
            except UnicodeEncodeError:
                result.append('?')
    return ''.join(result)

def _clean(t):
    t = t.translate(_TRANSLIT)
    return t.translate(str.maketrans(
        'àâäéèêëîïôöùûüçÀÂÄÉÈÊËÎÏÔÖÙÛÜÇœæŒÆ',
        'aaaeeeeiioouuucAAAEEEEIIOOUUUCoaOA'))

def build_input_line(buf, page=0, total_pages=1):
    if buf:
        out  = _goto(24, 1) + _bg(4) + _fg(3)
        text = f" > {buf.upper()}_  (+ENVOI=valider  DEL=annuler)"
    else:
        out  = _goto(24, 1) + _bg(7) + _fg(0)
        text = " Chiffre+ENVOI=toggle  *=eteindre tout "
    out += text[:40].ljust(40).encode('latin-1', 'replace')
    out += b'\x11'
    return bytes(out)

def build_assist_input_line(buf, flash=""):
    if flash:
        out  = _goto(23, 1) + _bg(0) + _fg(3) + _blink_on()
        out += _safe(flash)[:40].ljust(40).encode('latin-1', 'replace')
        out += _blink_off()
    elif buf:
        out  = _goto(23, 1) + _bg(0) + _fg(7)
        out += f" > {_clean(buf)[:35]}_".ljust(40).encode('latin-1', 'replace')
    else:
        out  = _goto(23, 1) + _bg(0) + _fg(7)
        out += " Tapez votre question puis ENVOI   ".encode('latin-1', 'replace')
    col = min(4 + len(buf), 39)
    out += _goto(23, col)
    return bytes(out)

def group_by_area(devices, area_order=None):
    areas = OrderedDict()
    if area_order:
        for a in area_order: areas[a] = []
    for d in devices: areas.setdefault(d.get('area', 'Autres'), []).append(d)
    return [(a, devs) for a, devs in areas.items() if devs]

def paginate(items, page):
    device_items = [i for i in items if i['type'] == 'device']
    total_pages  = max(1, -(-len(device_items) // CFG['page_size']))
    page         = max(0, min(page, total_pages - 1))
    start        = page * CFG['page_size']
    page_dev_set = {id(d['device']) for d in device_items[start:start + CFG['page_size']]}
    result, n, in_page, last_area = [], 1, False, None
    for item in items:
        if item['type'] == 'device':
            if id(item['device']) in page_dev_set:
                in_page = True
                area = item['device'].get('area', 'Autres')
                if area != last_area:
                    result.append({'type': 'header', 'area': area})
                    last_area = area
                result.append({'type': 'device', 'local_num': n, 'device': item['device']})
                n += 1
            elif in_page: break
    return result, total_pages

def build_display_items(devices, area_order=None):
    items = []
    for area, devs in group_by_area(devices, area_order):
        items.append({'type': 'header', 'area': area})
        for d in devs: items.append({'type': 'device', 'device': d})
    return items

def build_splash():
    now  = datetime.now()
    jour = _JOURS_FR[now.weekday()]
    date_str = f"{jour} {now.day:02d}/{now.month:02d}/{now.year}   {now.strftime('%H:%M')}"

    out = bytearray(b'\x0c\x14')
    for r in range(1, 4): out += _line(r, "")
    out += _line(4,  _center("* MINITEL-HA *"), fg_c=7)
    out += _line(5,  "")
    out += _line(6,  _center("Domotique Home Assistant"), fg_c=3)
    out += _line(7,  "")
    out += _line(8,  _center(f"Version {VERSION}"), fg_c=7)
    out += _line(9,  "")
    out += _line(10, _center("3615 MAISON - Minitel-HA - MrT0t0"), fg_c=3)
    out += _line(11, "")
    out += _line(12, _center(date_str), fg_c=3)
    for r in range(13, 23): out += _line(r, "")
    dur = CFG.get('splash_seconds', 7)
    out += _line(23, _center(f"Chargement en {dur}s..."), fg_c=7)
    out += _line(24, _center("Connexion etablie"), fg_c=0, bg_c=7)
    return bytes(out)

def build_loading():
    out  = bytearray(_goto(24, 1)) + _bg(4) + _fg(3)
    out += b' Chargement...                          '
    return bytes(out)

def build_time_update():
    now = datetime.now().strftime(CFG['date_format'])
    out = bytearray(_goto(2, 33)) + _fg(3)
    out += now.encode('latin-1', 'replace')
    return bytes(out)

def build_menu(stats, selected=""):
    MODES = [
        ('D', 'Domotique',  'Controle appareils    ', True),
        ('M', 'Meteo',      'Temperatures/Previsions', True),
        ('S', 'Scenes',     'Scenes et scripts     ', True),
        ('J', 'Journal',    'Historique des actions', True),
        ('A', 'Assistant',  'IA Home Assistant     ', True),
        ('R', 'aRchives',   'Pages Videotex static ', True),
        ('H', 'Aide',       'Guide utilisation     ', True),
    ]
    out  = bytearray(b'\x0c\x14')
    out += _line(1, "   MINITEL-HA   MENU PRINCIPAL  ", fg_c=0, bg_c=7)
    now  = datetime.now().strftime(CFG['date_format'])
    out += _line(2, f" ON:{stats['on']:2d} OFF:{stats['off']:2d}/{stats['total']:2d}   {now}", fg_c=3)
    out += _line(3, " " + "=" * 38, fg_c=7)
    row = 4
    for letter, name, desc, available in MODES:
        sel = selected.upper() == letter
        out += _line(row, f" {'>' if sel else ' '}[{letter}] {name:<12} {desc}",
                     fg_c=0 if sel else 7, bg_c=7 if sel else 0)
        row += 1
    while row <= 23: out += _line(row, ""); row += 1
    out += _line(24, " Lettre + ENVOI = acceder service   ", fg_c=0, bg_c=7)
    out += b'\x11' + _goto(24, 40)
    return bytes(out)

def build(devices, sensors, stats, page=0, buf="", area_order=None, flash_msg=""):
    items, total_pages = paginate(build_display_items(devices, area_order), page)
    out  = bytearray(b'\x0c\x14')
    out += _line(1, _clean(CFG['title'])[:40], fg_c=0, bg_c=7)
    now  = datetime.now().strftime(CFG['date_format'])
    out += _line(2, f" ON:{stats['on']:2d} OFF:{stats['off']:2d}/{stats['total']:2d}   {now}", fg_c=3)
    out += _line(3, " " + "=" * 38, fg_c=7)
    row = 4
    for item in items:
        if row > 21: break
        if item['type'] == 'header':
            out += _line(row, f" {_clean(item['area'].upper())}", fg_c=0, bg_c=7); row += 1
        elif item['type'] == 'device':
            d = item['device']; n = item['local_num']; is_on = d['state'] == 'on'
            out += _line(row, f" {n}. {_clean(d['name'])[:29]:<29}{' ON ' if is_on else ' OFF'}",
                         fg_c=2 if is_on else 1); row += 1
    while row <= 21: out += _line(row, ""); row += 1
    out += _line(22, f" Page {page+1}/{total_pages}  SUITE> <RETOUR  SOMMAIRE", fg_c=7)
    out += _line(23, f" {_clean(flash_msg)}" if flash_msg else "", fg_c=3, blink=bool(flash_msg))
    out += build_input_line(buf, page, total_pages)
    return bytes(out)

def build_meteo(meteo_data):
    out  = bytearray(b'\x0c\x14')
    out += _line(1, "   MINITEL-HA   METEO           ", fg_c=0, bg_c=7)
    now  = datetime.now().strftime("%d/%m  %H:%M")
    out += _line(2, f" Releve : {now}", fg_c=3)
    out += _line(3, " " + "=" * 38, fg_c=7)
    forecasts = meteo_data.get('forecast', [])
    ext       = meteo_data.get('ext', {})
    if forecasts:
        out += _line(4, " PREVISIONS METEO", fg_c=0, bg_c=7)
        out += _line(5, "  Date     Condition  Temp  Pluie", fg_c=7)
        row  = 6
        for f in forecasts[:4]:
            if row > 9: break
            label  = str(f.get('label',  '?'))[:8]
            cond   = str(f.get('cond',   '?'))[:10]
            temp   = str(f.get('temp',   '?'))
            tlow   = str(f.get('tlow',   ''))
            precip = str(f.get('precip', '--'))
            temp_s = f"{tlow}>{temp}" if tlow else temp
            out += _line(row, f"  {label:<8} {cond:<10} {temp_s:>5}C {precip:>4}", fg_c=3)
            row += 1
        while row <= 9: out += _line(row, ""); row += 1
    else:
        out += _line(4, " EXTERIEUR", fg_c=0, bg_c=7)
        out += _line(5, f"  Temperature : {str(ext.get('temp','?')):>6} C      ", fg_c=3)
        out += _line(6, f"  Humidite    : {str(ext.get('hum', '?')):>6} %       ", fg_c=3)
        for r in range(7, 10): out += _line(r, "")
    out += _line(10, " " + "-" * 38, fg_c=7)
    if forecasts:
        t = str(ext.get('temp','?')); h = str(ext.get('hum','?'))
        out += _line(11, f" Ext: {t}C  {h}%   PIECES", fg_c=3)
        out += _line(12, "  Piece              Temp    Hum  ", fg_c=7)
        row  = 13
    else:
        out += _line(11, " INTERIEUR PAR PIECE", fg_c=0, bg_c=7)
        out += _line(12, "  Piece              Temp    Hum  ", fg_c=7)
        row  = 13
    for room in meteo_data.get('rooms', [])[:8]:
        if row > 22: break
        name = _clean(room.get('name', '?'))[:14]
        out += _line(row, f"  {name:<14} {str(room.get('temp','N/A')):>6}C  {str(room.get('hum','N/A')):>5}% ", fg_c=3)
        row += 1
    while row <= 22: out += _line(row, ""); row += 1
    out += _line(23, "")
    out += _line(24, " SOMMAIRE=menu  D+ENVOI=Domotique   ", fg_c=0, bg_c=7)
    out += b'\x11' + _goto(24, 40)
    return bytes(out)

def build_scenes(scenes, scripts, buf="", flash_msg=""):
    out  = bytearray(b'\x0c\x14')
    out += _line(1, "   MINITEL-HA   SCENES          ", fg_c=0, bg_c=7)
    out += _line(2, f" {len(scenes)} scene(s)   {len(scripts)} script(s)     ", fg_c=3)
    out += _line(3, " " + "=" * 38, fg_c=7)
    row = 4; n = 1
    if scenes:
        out += _line(row, " SCENES", fg_c=0, bg_c=7); row += 1
        for sc in scenes:
            if row > 20: break
            sel = buf == str(n)
            out += _line(row, f" {n}. {_clean(sc['name'])[:35]}", fg_c=0 if sel else 7, bg_c=7 if sel else 0)
            row += 1; n += 1
    if scripts and row <= 20:
        out += _line(row, " SCRIPTS", fg_c=0, bg_c=7); row += 1
        for sc in scripts:
            if row > 20: break
            sel = buf == str(n)
            out += _line(row, f" {n}. {_clean(sc['name'])[:35]}", fg_c=0 if sel else 7, bg_c=7 if sel else 0)
            row += 1; n += 1
    while row <= 22: out += _line(row, ""); row += 1
    out += _line(23, f" {_clean(flash_msg)}" if flash_msg else "", fg_c=3, blink=bool(flash_msg))
    out += _line(24, " Num+ENVOI=activer  SOMMAIRE=menu   ", fg_c=0, bg_c=7)
    out += b'\x11' + _goto(24, 40)
    return bytes(out)

def build_journal(journal, page=0):
    LINES_PER_PAGE = 17
    entries = list(reversed(list(journal)))
    total   = max(1, -(-len(entries) // LINES_PER_PAGE))
    page    = max(0, min(page, total - 1))
    shown   = entries[page * LINES_PER_PAGE:(page + 1) * LINES_PER_PAGE]
    out  = bytearray(b'\x0c\x14')
    out += _line(1, "   MINITEL-HA   JOURNAL         ", fg_c=0, bg_c=7)
    out += _line(2, f" {len(entries)} actions  Page {page+1}/{total}          ", fg_c=3)
    out += _line(3, " " + "=" * 38, fg_c=7)
    row = 4
    for e in shown:
        if row > 22: break
        name = _clean(e.get('name', '?'))[:22]
        out += _line(row, f" {e['ts']} {name:<22} [{'OK' if e.get('ok') else 'ERR'}]",
                     fg_c=2 if e.get('ok') else 1); row += 1
    while row <= 22: out += _line(row, ""); row += 1
    out += _line(23, "")
    out += _line(24, " SUITE=page suiv  SOMMAIRE=menu     ", fg_c=0, bg_c=7)
    out += b'\x11' + _goto(24, 40)
    return bytes(out)

def build_assistant(history, agents, cur_agent_idx=0, buf="", flash_msg=""):
    if agents and 0 <= cur_agent_idx < len(agents):
        agent_name = _clean(agents[cur_agent_idx].get('name', 'Agent'))
    else:
        agent_name = 'Assistant HA'
    out  = bytearray(b'\x0c\x14')
    out += _line(1, "   MINITEL-HA   ASSISTANT IA    ", fg_c=0, bg_c=7)
    out += _line(2, f" Agent: {agent_name[:30]}", fg_c=3)
    out += _line(3, " " + "=" * 38, fg_c=7)
    row = 4; max_row = 21; disp_lines = []
    for entry in history:
        q = _clean(entry.get('q', ''))
        r = _safe(entry.get('r', ''))
        while q: disp_lines.append(('q', f"> {q[:37]}")); q = q[37:]
        while r: disp_lines.append(('r', f"  {r[:38]}")); r = r[38:]
    visible = disp_lines[-(max_row - row + 1):]
    for typ, txt in visible:
        if row > max_row: break
        out += _line(row, txt, fg_c=7 if typ == 'q' else 3); row += 1
    while row <= max_row: out += _line(row, ""); row += 1
    out += _line(22, " " + "-" * 38, fg_c=7)
    out += build_assist_input_line(buf, flash_msg)
    out += _line(24, f" ENVOI=envoyer {'SUITE=agent' if len(agents)>1 else '          '} SOMM=menu ", fg_c=0, bg_c=7)
    out += b'\x11'
    return bytes(out)

def build_archives(files, idx=0, flash=""):
    out  = bytearray(b'\x0c\x14')
    out += _line(1, "   MINITEL-HA   ARCHIVES .VDT   ", fg_c=0, bg_c=7)
    if not files:
        out += _line(2, " Aucun fichier .vdt disponible  ", fg_c=1)
        out += _line(3, " " + "=" * 38, fg_c=7)
        out += _line(5, " Deposer des fichiers .vdt dans ", fg_c=7)
        out += _line(6, " le dossier static/archives/    ", fg_c=3)
        for r in range(7, 23): out += _line(r, "")
        out += _line(24, " SOMMAIRE=menu                      ", fg_c=0, bg_c=7)
        out += b'\x11' + _goto(24, 40)
        return bytes(out)
    total = len(files)
    PAGE  = 9
    file_page   = idx // PAGE
    total_pages = max(1, -(-total // PAGE))
    start = file_page * PAGE
    shown = files[start:start + PAGE]
    out += _line(2, f" {total} fichier(s)   Page {file_page+1}/{total_pages}        ", fg_c=3)
    out += _line(3, " " + "=" * 38, fg_c=7)
    out += _line(4, " FICHIERS VIDEOTEX DISPONIBLES  ", fg_c=0, bg_c=7)
    row = 5
    for i, f in enumerate(shown):
        local_n = start + i; sel = local_n == idx
        name    = _clean(f.get('name', '?'))[:32]
        size_k  = f.get('size', 0) // 1024
        out += _line(row, f" {'>' if sel else ' '}{local_n+1:2d}. {name} ({size_k}k)",
                     fg_c=0 if sel else 7, bg_c=7 if sel else 0)
        row += 1
    while row <= 22: out += _line(row, ""); row += 1
    if flash:
        out += _line(23, f" {_clean(flash)[:38]}", fg_c=3, blink=True)
    else:
        sel_name = _clean(files[idx].get('name', '?'))[:24] if files else ''
        out += _line(23, f" Selection: {sel_name}", fg_c=3)
    out += _line(24, " ENVOI=ouvrir  SUITE/RET=nav  SOMM ", fg_c=0, bg_c=7)
    out += b'\x11' + _goto(24, 40)
    return bytes(out)

_AIDE_GENERAL_PAGES = [
    {'title': " AIDE GENERALE — NAVIGATION",
     'lines': [
        " SOMMAIRE  : Menu principal",
        " GUIDE     : Aide contextuelle du mode",
        "   + GUIDE : Aide generale (cette page)",
        " SUITE  >  : Page / fichier suivant",
        " RETOUR <  : Page / fichier precedent",
        " ANNULATION: Annuler / retour",
        " CORRECTION: Effacer la saisie",
        " Lettre+ENVOI : Changer de mode",
        "   D M S J A R H",
    ]},
    {'title': " AIDE — MODE DOMOTIQUE [D]",
     'lines': [
        " 1 a 9     : Selectionner un appareil",
        " ENVOI     : Basculer ON/OFF",
        " SUITE     : Page suivante",
        " RETOUR    : Page precedente",
        " *         : Tout eteindre",
        " 0         : Journal des actions",
    ]},
    {'title': " AIDE — MODE METEO [M]",
     'lines': [
        " Previsions J/J+1/J+2… + temp pieces",
        " Configurer dans config.yaml :",
        "   meteo.weather_entity: weather.xxx",
    ]},
    {'title': " AIDE — MODE SCENES [S]",
     'lines': [
        " Chiffre + ENVOI : Activer scene",
        " Configurer : [scenes] et [scripts]",
        " dans config.yaml",
    ]},
    {'title': " AIDE — MODE ASSISTANT [A]",
     'lines': [
        " Saisir votre question + ENVOI",
        " SUITE     : Changer d'agent IA",
        " ANNUL/DEL : Effacer la saisie",
        " Ex: Allume la lumiere du salon",
        "     Quel temps fait-il ?",
    ]},
    {'title': " AIDE — MODE ARCHIVES [R]",
     'lines': [
        " Pages Videotex statiques (.vdt)",
        " Dossier : static/archives/",
        " SUITE / RETOUR : Naviguer la liste",
        " Chiffre + ENVOI : Ouvrir et lire",
        " ANNULATION : Retour a la liste",
    ]},
    {'title': " AIDE — MODE JOURNAL [J]",
     'lines': [
        " Historique des 50 dernieres actions.",
        " SUITE / RETOUR : Changer de page",
        " SOMMAIRE       : Menu principal",
    ]},
]

def build_aide(current_mode="domotique", aide_page=0, general=False):
    out = bytearray(b'\x0c\x14')
    if general:
        total = len(_AIDE_GENERAL_PAGES)
        idx   = max(0, min(aide_page, total - 1))
        pg    = _AIDE_GENERAL_PAGES[idx]
        out  += _line(1, "   MINITEL-HA   AIDE GENERALE   ", fg_c=0, bg_c=7)
        out  += _line(2, f" Page {idx+1}/{total}  SUITE=suivante          ", fg_c=3)
        out  += _line(3, " " + "=" * 38, fg_c=7)
        out  += _line(4, _clean(pg['title']), fg_c=0, bg_c=7)
        row   = 5
        for line in pg['lines']:
            if row > 22: break
            out += _line(row, _clean(line), fg_c=7); row += 1
        while row <= 22: out += _line(row, ""); row += 1
        out += _line(23, "")
        out += _line(24, " SUITE=suivante  SOMM=fermer        ", fg_c=0, bg_c=7)
    else:
        _CTX = {
            'domotique': [" 1-9+ENVOI=toggle  SUITE/RET=pages",
                          " *=tout eteindre  0=journal",
                          " Lettre+ENVOI=mode  GUIDE=aide gen"],
            'meteo':     [" Previsions + temp/hum par piece",
                          " Config: meteo.weather_entity",
                          " GUIDE=aide generale"],
            'scenes':    [" Chiffre+ENVOI=activer",
                          " GUIDE=aide generale"],
            'assistant': [" Saisir+ENVOI=envoyer  SUITE=agent",
                          " ANNUL/DEL=effacer  GUIDE=aide gen"],
            'archives':  [" SUITE/RETOUR=naviguer  ENVOI=ouvrir",
                          " ANNUL=retour liste  GUIDE=aide gen"],
            'journal':   [" SUITE/RETOUR=pages  GUIDE=aide gen"],
        }
        lines = _CTX.get(current_mode, [" GUIDE = aide generale"])
        out += _line(1, "   MINITEL-HA   AIDE            ", fg_c=0, bg_c=7)
        out += _line(2, f" Mode : {_clean(current_mode.upper())[:28]}", fg_c=3)
        out += _line(3, " " + "=" * 38, fg_c=7)
        row = 4
        for line in lines:
            if row > 22: break
            out += _line(row, _clean(line), fg_c=7); row += 1
        while row <= 22: out += _line(row, ""); row += 1
        out += _line(23, "")
        out += _line(24, " GUIDE=aide-gen  SOMMAIRE=fermer    ", fg_c=0, bg_c=7)
    out += b'\x11' + _goto(24, 40)
    return bytes(out)
