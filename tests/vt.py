"""Interprete Videotex minimal pour les tests : rend le texte affiche.

Gere FF, US (positionnement), ESC (attributs ignores), SO/SI (les
caracteres semi-graphiques sont rendus par '#'), SS2 (accents G2), CAN,
et le LF de sortie de la ligne 0 (retour a la position memorisee).
"""
import pagevideo as P

_G2 = {seq: ch for ch, seq in P.G2.items()}


class Screen:
    def __init__(self):
        self.rows = [[' '] * 40 for _ in range(25)]
        self.r, self.c, self.g1 = 1, 0, False
        self.saved = None

    def feed(self, data):
        i = 0
        while i < len(data):
            b = data[i] & 0x7f
            if b == 0x0c:
                for r in range(1, 25):
                    self.rows[r] = [' '] * 40
                self.r, self.c, self.g1 = 1, 0, False
            elif b == 0x1f:
                r, c = data[i + 1] - 0x40, data[i + 2] - 0x40
                if r == 0 and self.r != 0:
                    self.saved = (self.r, self.c)
                self.r, self.c, self.g1 = r, max(0, c - 1), False
                i += 2
            elif b == 0x1b:
                i += 1
            elif b == 0x0e:
                self.g1 = True
            elif b == 0x0f:
                self.g1 = False
            elif b == 0x18:
                for c in range(self.c, 40):
                    self.rows[self.r][c] = ' '
            elif b == 0x0a:
                if self.r == 0 and self.saved:
                    self.r, self.c = self.saved
                else:
                    self.r = min(24, self.r + 1)
            elif b == 0x19:
                n = 3 if data[i + 1] in b'ABCHK' else 2
                self._put(_G2.get(bytes(data[i:i + n]), '?'))
                i += n - 1
            elif b >= 0x20:
                self._put('#' if self.g1 and b != 0x20 else chr(b))
            i += 1

    def _put(self, ch):
        if self.c < 40:
            self.rows[self.r][self.c] = ch
        self.c += 1
        if self.c >= 40:
            self.c = 0
            if self.r:
                self.r = self.r + 1 if self.r < 24 else 1

    def line(self, r):
        return ''.join(self.rows[r]).rstrip()

    def text(self):
        return '\n'.join(f'{r:2d}|{self.line(r)}' for r in range(25))

    def __contains__(self, s):
        return any(s in self.line(r) for r in range(25))
