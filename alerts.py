"""Alertes affichees sur la ligne 0 du Minitel (porte ouverte, seuil...).

Une alerte est active quand l'etat de son entite vaut l'un des `states`,
ou depasse `above` / passe sous `below` pour un capteur numerique.
"""

ALERTS = []


def configure(alerts_cfg):
    ALERTS[:] = alerts_cfg or []


def entities():
    return {a['entity'] for a in ALERTS}


def is_active(alert, state):
    if state in (None, 'unavailable', 'unknown'):
        return False
    if alert.get('states') is not None:
        return str(state) in alert['states']
    try:
        v = float(state)
    except (TypeError, ValueError):
        return False
    if alert.get('above') is not None and v > float(alert['above']):
        return True
    if alert.get('below') is not None and v < float(alert['below']):
        return True
    return False


def evaluate(index):
    """Messages des alertes actives, dans l'ordre de la configuration."""
    out = []
    for a in ALERTS:
        e = index.get(a['entity'])
        if e and is_active(a, e.get('state')):
            out.append(a['message'])
    return out
