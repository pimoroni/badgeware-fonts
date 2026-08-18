"""The glyph list an icon font is built from.

`name codepoint [printable]` per line: the format afinate, the alright-fonts encoder, takes,
with a third field added.

    sunny        e81a  s
    thunderstorm ebdb

The third field remaps a glyph onto a printable character, and badge-side code draws it
with an ordinary string: `sunny e81a s` puts the sun at "s".

Codepoints pack as u16, and a Material Symbols glyph above U+FFFF only fits remapped. What the
entry's `codepoints` setting does:

    remap      (default) the third field where a line has one, the glyph's own otherwise
    preserve   the glyph's codepoint always, third fields ignored
    printable  the third field, required on every line
"""

import pathlib

from .af import MAX_CODEPOINT, ManifestError

MODES = ("remap", "preserve", "printable")


class Wanted:
    def __init__(self, name, codepoint, printable=None):
        self.name = name
        self.codepoint = codepoint
        self.printable = printable

    def target(self, mode):
        """The codepoint this glyph is packed at."""
        if mode == "preserve":
            return self.codepoint
        if mode == "printable":
            if self.printable is None:
                raise ManifestError(f"{self.name} has no third field, and this entry is " 'codepoints = "printable"')
            return self.printable
        return self.printable if self.printable is not None else self.codepoint


def parse(lines, where):
    """`name codepoint [printable]` per line. Blank lines and # comments are skipped."""
    found = []
    for number, line in enumerate(lines, 1):
        line = line.split("#", 1)[0].strip()
        if not line:
            continue
        parts = line.split()
        if len(parts) not in (2, 3):
            raise ManifestError(f"{where}:{number}: want 'name codepoint [printable]', " f"got {line!r}")
        try:
            codepoint = int(parts[1], 16)
        except ValueError:
            raise ManifestError(f"{where}:{number}: {parts[1]!r} is not a hex codepoint") from None
        printable = None
        if len(parts) == 3:
            if len(parts[2]) != 1:
                raise ManifestError(f"{where}:{number}: the remap must be one character")
            printable = ord(parts[2])
        found.append(Wanted(parts[0], codepoint, printable))
    if not found:
        raise ManifestError(f"{where} lists no glyphs")
    return found


def read(path):
    path = pathlib.Path(path)
    if not path.exists():
        raise ManifestError(f"no glyph list at {path}")
    return parse(path.read_text(encoding="utf-8").splitlines(), str(path))


def check(wanted, mode):
    """Anything that will not pack: a duplicate target, or a codepoint over a u16."""
    if mode not in MODES:
        raise ManifestError(f"codepoints must be one of {', '.join(MODES)}, not {mode!r}")
    seen, problems = {}, []
    for one in wanted:
        target = one.target(mode)
        if target > MAX_CODEPOINT:
            problems.append(f"{one.name} is {target:x}, over the format's u16. Give it " "a third field, or drop it from the corpus")
            continue
        if target in seen:
            problems.append(f"{one.name} and {seen[target]} both pack at " f"{target:04x}")
            continue
        seen[target] = one.name
    return problems
