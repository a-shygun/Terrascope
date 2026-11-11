"""Pseudo-language catalogue for finding layout problems (overflow, untranslated text).

Every message becomes accented text, about 30% longer, wrapped in [ ] so that
clipping and missing translations are easy to see:

    "Terminal too small"  ->  "[Ťéŕmîñàľ ťöö şmàľľ~~~~]"

Placeholders ({name}, %s) and the English key itself stay intact. Messages
without a translation show up as the accented English text.

usage:
    python tools/pseudo_locale.py OUT_DIR
    set terrascope_LOCALE_DIR=OUT_DIR
    terrascope --lang xx

OUT_DIR gets xx/LC_MESSAGES/terrascope.po and .mo. Nothing is written into the
repository.
"""

from __future__ import annotations

import pathlib
import re
import sys

from babel.messages.catalog import Catalog
from babel.messages.mofile import write_mo
from babel.messages.pofile import read_po, write_po
from babel import Locale

ROOT = pathlib.Path(__file__).resolve().parents[1]
POT = ROOT / "src" / "terrascope" / "locale" / "terrascope.pot"

_ACCENTS = {
    "a": "à", "b": "ƀ", "c": "ç", "d": "đ", "e": "é", "f": "ƒ", "g": "ĝ", "h": "ĥ",
    "i": "î", "j": "ĵ", "k": "ķ", "l": "ľ", "m": "ṁ", "n": "ñ", "o": "ö", "p": "þ",
    "q": "q", "r": "ŕ", "s": "š", "t": "ť", "u": "ü", "v": "ṽ", "w": "ŵ", "x": "x",
    "y": "ý", "z": "ž",
    "A": "À", "B": "Ɓ", "C": "Ç", "D": "Đ", "E": "É", "F": "Ƒ", "G": "Ĝ", "H": "Ĥ",
    "I": "Î", "J": "Ĵ", "K": "Ķ", "L": "Ľ", "M": "Ṁ", "N": "Ñ", "O": "Ö", "P": "Þ",
    "Q": "Q", "R": "Ŕ", "S": "Š", "T": "Ť", "U": "Ü", "V": "Ṽ", "W": "Ŵ", "X": "X",
    "Y": "Ý", "Z": "Ž",
}
# Text inside {...} placeholders and %-directives is never accented.
_KEEP = re.compile(r"(\{[^{}]*\}|%[-+ #0]*\d*[sdfr%])")


def pseudo(text: str) -> str:
    if not text:
        return text
    pieces = []
    for index, part in enumerate(_KEEP.split(text)):
        if index % 2:  # a placeholder
            pieces.append(part)
        else:
            pieces.append("".join(_ACCENTS.get(char, char) for char in part))
    accented = "".join(pieces)
    extra = max(2, round(len(text) * 0.3))
    return "[" + accented + "~" * extra + "]"


def build(out_dir: pathlib.Path) -> pathlib.Path:
    template = read_po(open(POT, "rb"))
    # No Locale object: Babel does not know "xx", and the catalogue does not need one.
    catalog = Catalog(project="Terrascope", charset="utf-8", fuzzy=False)
    for message in template:
        if not message.id:
            continue
        if isinstance(message.id, tuple):
            value = (pseudo(message.id[0]), pseudo(message.id[1]))
        else:
            value = pseudo(message.id)
        catalog.add(message.id, string=value, locations=message.locations)
    target = out_dir / "xx" / "LC_MESSAGES"
    target.mkdir(parents=True, exist_ok=True)
    with open(target / "terrascope.po", "wb") as handle:
        write_po(handle, catalog)
    with open(target / "terrascope.mo", "wb") as handle:
        write_mo(handle, catalog)
    return target


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit(__doc__)
    print(build(pathlib.Path(sys.argv[1])))
