from pathlib import Path

_html = ""

def load(port):
    global _html
    p = Path(__file__).parent / 'static' / 'index.html'
    _html = p.read_text(encoding='utf-8').replace('__WB_PORT__', str(port))

def get():
    return _html
