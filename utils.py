from datetime import datetime

_COLORS = {
    'INFO': '\033[32m', 'WARN': '\033[33m',
    'ERR':  '\033[31m', 'GIT':  '\033[36m',
    'VT':   '\033[35m', 'BR':   '\033[34m',
    'HA':   '\033[32m',
}
_RESET = '\033[0m'

def log(level, msg):
    ts  = datetime.now().strftime('%H:%M:%S')
    col = _COLORS.get(level, '')
    print(f'[{ts}][{level}] {col}{msg}{_RESET}', flush=True)
