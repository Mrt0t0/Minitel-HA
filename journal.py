"""Journal des actions, conserve sur disque entre deux redemarrages."""
import json
import os
from collections import deque
from datetime import datetime
from pathlib import Path

from utils import log

ENTRIES = deque(maxlen=50)
_PATH = None


def configure(path, size=50):
    """Fixe le fichier de sauvegarde et recharge les entrees existantes."""
    global ENTRIES, _PATH
    ENTRIES = deque(maxlen=size)
    _PATH = Path(path) if path else None
    if not _PATH or not _PATH.exists():
        return
    try:
        for e in json.loads(_PATH.read_text(encoding='utf-8')):
            if isinstance(e, dict) and 'ts' in e:
                ENTRIES.append(e)
    except (OSError, ValueError) as e:
        log('ERR', f'journal illisible ({_PATH}): {e}')


def add(name, entity, action, ok):
    ENTRIES.append({
        'ts':     datetime.now().strftime('%Y-%m-%d %H:%M'),
        'name':   name, 'entity': entity,
        'action': action, 'ok': ok,
    })
    _save()


def _save():
    if not _PATH:
        return
    try:
        _PATH.parent.mkdir(parents=True, exist_ok=True)
        tmp = _PATH.with_suffix('.tmp')
        tmp.write_text(json.dumps(list(ENTRIES), ensure_ascii=False), encoding='utf-8')
        os.replace(tmp, _PATH)
    except OSError as e:
        log('ERR', f'journal non sauvegarde: {e}')


def short_ts(ts):
    """'HH:MM' pour aujourd'hui, 'jj/mm' sinon (anciennes entrees : tel quel)."""
    try:
        dt = datetime.strptime(ts, '%Y-%m-%d %H:%M')
    except (TypeError, ValueError):
        return str(ts)[:5]
    if dt.date() == datetime.now().date():
        return dt.strftime('%H:%M')
    return dt.strftime('%d/%m')
