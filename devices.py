"""Comportement par type d'entite HA.

Pour chaque appareil : libelle d'etat (8 caracteres max), action de la
touche ENVOI et reglage par SUITE / RETOUR. Une action est un dict
{domain, service, data, confirm} pret pour ha_client.call_service.
"""
from i18n import t

UNAVAILABLE = ('unavailable', 'unknown', '?', '', None)


def domain(dev):
    return dev['entity'].split('.')[0]


def _attrs(dev):
    return dev.get('attrs') or {}


def is_available(dev):
    return dev.get('state') not in UNAVAILABLE


def is_active(dev):
    """Allume / ouvert / en marche (compte ON dans les statistiques)."""
    s, dom = dev.get('state'), domain(dev)
    if not is_available(dev):
        return False
    if dom == 'cover':
        return s in ('open', 'opening', 'closing')
    if dom == 'lock':
        return s in ('unlocked', 'open', 'opening')
    if dom == 'climate':
        return s != 'off'
    if dom == 'media_player':
        return s not in ('off', 'standby')
    return s == 'on'


def _num(v):
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return int(f) if f == int(f) else round(f, 1)


def label(dev):
    s, dom, a = dev.get('state'), domain(dev), _attrs(dev)
    if not is_available(dev):
        return t('st.na')
    if dom == 'light':
        if s == 'on' and a.get('brightness') is not None:
            return f'{round(a["brightness"] / 2.55)}%'
        return t('st.on') if s == 'on' else t('st.off')
    if dom == 'cover':
        if a.get('current_position') is not None and s != 'closed':
            return f'{a["current_position"]}%'
        if s in ('opening', 'closing'):
            return '...'
        return t('st.open') if s == 'open' else t('st.closed')
    if dom == 'climate':
        target = _num(a.get('temperature'))
        if s == 'off' or target is None:
            return t('st.off') if s == 'off' else s[:8].upper()
        return f'{target}°C'
    if dom == 'media_player':
        return {'playing': t('st.play'), 'paused': t('st.pause'),
                'off': t('st.off'), 'standby': t('st.off')}.get(s, t('st.on'))
    if dom == 'lock':
        if s == 'locked':
            return t('st.locked')
        if s == 'unlocked':
            return t('st.unlocked')
        return s[:8].upper()
    if dom in ('scene', 'script', 'button', 'input_button'):
        return t('st.on') if s == 'on' else t('st.run')
    if s in ('on', 'off'):
        return t('st.' + s)
    return str(s)[:8].upper()


def _act(dom, service, dev, confirm=False, **data):
    return {'domain': dom, 'service': service, 'confirm': confirm,
            'data': {'entity_id': dev['entity'], **data}}


def action(dev):
    """Action de la touche ENVOI."""
    dom, s = domain(dev), dev.get('state')
    if dom in ('light', 'switch', 'fan', 'input_boolean', 'automation', 'cover'):
        return _act(dom, 'toggle', dev)
    if dom == 'media_player':
        if s in ('playing', 'paused'):
            return _act(dom, 'media_play_pause', dev)
        return _act(dom, 'toggle', dev)
    if dom == 'climate':
        return _act(dom, 'turn_off' if is_active(dev) else 'turn_on', dev)
    if dom == 'lock':
        # Deverrouiller une porte depuis le Minitel demande une confirmation
        if s == 'locked':
            return _act(dom, 'unlock', dev, confirm=True)
        return _act(dom, 'lock', dev)
    if dom in ('scene', 'script'):
        return _act(dom, 'turn_on', dev)
    if dom in ('button', 'input_button'):
        return _act(dom, 'press', dev)
    return _act('homeassistant', 'toggle', dev)


def adjustable(dev):
    return domain(dev) in ('light', 'cover', 'climate', 'fan', 'media_player')


def adjust(dev, step):
    """Reglage +/- (step = +1 ou -1) ; None si non reglable."""
    dom, a = domain(dev), _attrs(dev)
    if dom == 'light':
        return _act(dom, 'turn_on', dev, brightness_step_pct=10 * step)
    if dom == 'cover':
        pos = a.get('current_position')
        if pos is None:
            return _act(dom, 'open_cover' if step > 0 else 'close_cover', dev)
        return _act(dom, 'set_cover_position', dev,
                    position=max(0, min(100, int(pos) + 10 * step)))
    if dom == 'climate':
        target = _num(a.get('temperature'))
        if target is None:
            return None
        inc = _num(a.get('target_temp_step')) or 0.5
        new = round(target + inc * step, 1)
        lo, hi = _num(a.get('min_temp')), _num(a.get('max_temp'))
        if lo is not None:
            new = max(lo, new)
        if hi is not None:
            new = min(hi, new)
        return _act(dom, 'set_temperature', dev, temperature=new)
    if dom == 'fan':
        return _act(dom, 'increase_speed' if step > 0 else 'decrease_speed', dev)
    if dom == 'media_player':
        return _act(dom, 'volume_up' if step > 0 else 'volume_down', dev)
    return None


def sensor_value(sen):
    """Valeur affichee d'un capteur : nombre arrondi ou texte court."""
    if sen.get('state') in UNAVAILABLE:
        return t('st.na')
    n = _num(sen['state'])
    return str(n) if n is not None else str(sen['state'])[:8]
