"""Chargement et normalisation de config.yaml.

Toutes les valeurs par defaut et les bornes sont appliquees ici : le reste
du code lit un dictionnaire complet et valide.
"""
from pathlib import Path

import yaml

LANGUAGES = ('fr', 'en')


def _sec(cfg, name):
    """Section YAML : une cle presente mais vide vaut None."""
    return cfg.get(name) or {}


def _get(sec, key, default):
    val = sec.get(key, default)
    return default if val is None else val


def _int(sec, key, default, lo, hi):
    try:
        val = int(_get(sec, key, default))
    except (TypeError, ValueError):
        val = default
    return max(lo, min(hi, val))


def _visible(items):
    return [i for i in (items or []) if isinstance(i, dict) and i.get('entity')
            and i.get('visible', True)]


def sort_devices(devices, area_order):
    """Ordre exact de pagevideo.group_by_area : le numero affiche a
    l'ecran doit designer l'appareil commande."""
    if not area_order:
        return sorted(devices, key=lambda d: d.get('area', 'Autres'))
    order = list(area_order)
    for d in devices:
        if d.get('area', 'Autres') not in order:
            order.append(d.get('area', 'Autres'))
    return sorted(devices, key=lambda d: order.index(d.get('area', 'Autres')))


def _alerts(raw):
    out = []
    for a in raw or []:
        if not isinstance(a, dict) or not a.get('entity'):
            continue
        states = a.get('state')
        if states is not None and not isinstance(states, list):
            states = [states]
        out.append({
            'entity':  a['entity'],
            # YAML lit on/off sans guillemets comme des booleens
            'states':  ({_state_str(s) for s in states} if states is not None else None),
            'above':   a.get('above'),
            'below':   a.get('below'),
            'message': str(a.get('message') or a['entity']),
        })
    return out


def _state_str(s):
    if s is True:
        return 'on'
    if s is False:
        return 'off'
    return str(s)


def normalize(cfg, base):
    """Dictionnaire de configuration complet a partir du YAML brut."""
    base = Path(base)
    ha, srv, disp = _sec(cfg, 'homeassistant'), _sec(cfg, 'server'), _sec(cfg, 'display')
    assist, arch = _sec(cfg, 'assistant'), _sec(cfg, 'archives')
    sec, jour = _sec(cfg, 'security'), _sec(cfg, 'journal')

    lang = str(_get(disp, 'language', _get(assist, 'language', 'fr'))).lower()
    if lang not in LANGUAGES:
        lang = 'fr'

    area_order = cfg.get('area_order') or None
    quick_off = cfg.get('quick_off') or None
    if quick_off and not quick_off.get('entity'):
        quick_off = None
    if quick_off:
        quick_off = {'entity': quick_off['entity'],
                     'name': str(quick_off.get('name') or quick_off['entity']),
                     'confirm': bool(quick_off.get('confirm', True))}

    agents = [a for a in (assist.get('agents') or []) if isinstance(a, dict) and a.get('id')]
    if not agents:
        agents = [{'id': 'conversation.home_assistant', 'name': 'Assistant HA'}]

    journal_file = _get(jour, 'file', 'data/journal.json')

    return {
        'base': base,
        'ha': {'url': str(_get(ha, 'url', '')).rstrip('/'),
               'token': str(_get(ha, 'token', ''))},
        'server': {'vt_port': _int(srv, 'vt_port', 3615, 1, 65535),
                   'http_port': _int(srv, 'http_port', 8080, 1, 65535),
                   'trust_ingress': bool(_get(srv, 'trust_ingress', False))},
        'display': {'title': str(_get(disp, 'title', '   MINITEL-HA  DOMOTIQUE')),
                    'page_size': _int(disp, 'page_size', 9, 1, 9),
                    'refresh_auto': _int(disp, 'refresh_auto', 30, 5, 3600),
                    'date_format': str(_get(disp, 'date_format', '%H:%M')),
                    'show_sensors': bool(_get(disp, 'show_sensors', True)),
                    'splash_seconds': _int(disp, 'splash_seconds', 7, 0, 60),
                    'language': lang},
        'area_order': area_order,
        'devices': sort_devices(_visible(cfg.get('devices')), area_order),
        'sensors': sort_devices(_visible(cfg.get('sensors')), area_order),
        'scenes': _visible(cfg.get('scenes')),
        'scripts': _visible(cfg.get('scripts')),
        'quick_off': quick_off,
        'meteo': _sec(cfg, 'meteo'),
        'assistant': {'language': str(_get(assist, 'language', lang)), 'agents': agents},
        'archives': {'folder': (base / str(_get(arch, 'folder', 'static/archives'))).resolve(),
                     'auto_rotate': _int(arch, 'auto_rotate', 30, 0, 3600),
                     'max_upload_kb': _int(arch, 'max_upload_kb', 512, 1, 10240)},
        'alerts': _alerts(cfg.get('alerts')),
        'security': {'access_code': str(_get(sec, 'access_code', '') or '')},
        'journal': {'file': (base / str(journal_file)).resolve(),
                    'size': _int(jour, 'size', 50, 1, 1000)},
    }


def load(path):
    path = Path(path)
    with open(path, encoding='utf-8') as f:
        raw = yaml.safe_load(f) or {}
    return normalize(raw, path.parent)
