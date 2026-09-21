#!/usr/bin/env python3
from pathlib import Path

_HTML_CACHE = None

def load(wb_port: int):
    """Charge static/index.html et injecte le port WS"""
    global _HTML_CACHE
    p = Path(__file__).parent / 'static' / 'index.html'
    if not p.exists():
        _HTML_CACHE = '<h1>❌ static/index.html introuvable</h1>'
        print(f'[ERR] {p} manquant — créez static/index.html')
        return
    _HTML_CACHE = p.read_text(encoding='utf-8').replace('__WB_PORT__', str(wb_port))
    print(f'[HTML] static/index.html charge ({len(_HTML_CACHE)} octets)')

def get() -> str:
    """Retourne le HTML chargé"""
    return _HTML_CACHE or '<h1>❌ pagehtml.load() non appelé</h1>'
