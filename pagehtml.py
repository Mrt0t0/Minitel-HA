"""Page de l'emulateur : static/index.html avec langue et version injectees."""
from pathlib import Path

_HTML_CACHE = None


def load(lang='fr', version=''):
    global _HTML_CACHE
    p = Path(__file__).parent / 'static' / 'index.html'
    if not p.exists():
        _HTML_CACHE = '<h1>static/index.html introuvable</h1>'
        print(f'[ERR] {p} manquant')
        return
    _HTML_CACHE = (p.read_text(encoding='utf-8')
                   .replace('__LANG__', lang).replace('__VERSION__', version))
    print(f'[HTML] static/index.html charge ({len(_HTML_CACHE)} octets)')


def get():
    return _HTML_CACHE or '<h1>pagehtml.load() non appele</h1>'
