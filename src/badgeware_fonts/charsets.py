"""Which characters a text font packs.

Every glyph costs flash on a badge: a full Latin set runs to hundreds of glyphs and tens of
KB, where a clock face needs a dozen. An entry picks its set by naming built-in sets,
listing literal characters, or giving codepoint ranges. The three are unioned.

A manifest defines further sets in [charsets], usable by name the same way.
"""

import itertools
import unicodedata

from .af import ManifestError


def _named(low, high, holding=""):
    """Every assigned codepoint in a range, or those whose name holds `holding`."""
    found = set()
    for codepoint in range(low, high + 1):
        try:
            name = unicodedata.name(chr(codepoint))
        except ValueError:
            continue
        if holding in name:
            found.add(codepoint)
    return found


# The codepoints a badge draws in ordinary use: printable ASCII, the degree sign for a
# temperature, and the accented Latin a hostname or an OS string can arrive with.
def _latin():
    wanted = {*range(0x20, 0x7F), 0xB0, 0xD7, 0xF7}
    return wanted | _named(0xC0, 0x17F, "LATIN")


BUILTIN = {
    "ascii": set(range(0x20, 0x7F)),
    # The same set under the name afinate gives it.
    "basic_latin": set(range(0x20, 0x7F)),
    "latin": _latin(),
    "latin1": set(range(0x20, 0x7F)) | _named(0xA0, 0xFF),
    "digits": set(range(0x30, 0x3A)),
    # What a reading is drawn with: digits, a sign, a decimal point and the units.
    "numeric": {ord(c) for c in "0123456789.,:-+/% "},
    "punctuation": {ord(c) for c in " !\"'(),-./:;?"},
}
DEFAULT = "latin"


def parse_codepoint(text, where):
    """`U+00B0`, `0xb0` or `b0`, all the same codepoint. int() takes the 0x form itself."""
    cleaned = text.strip().lower().removeprefix("u+").removeprefix("\\u")
    try:
        return int(cleaned, 16)
    except ValueError:
        raise ManifestError(f"{where}: {text!r} is not a hex codepoint") from None


def parse_range(text, where):
    """One codepoint, or `U+0020-U+007E` inclusive."""
    parts = text.split("-", 1)
    if len(parts) == 1:
        point = parse_codepoint(parts[0], where)
        return range(point, point + 1)
    low = parse_codepoint(parts[0], where)
    high = parse_codepoint(parts[1], where)
    if high < low:
        raise ManifestError(f"{where}: range {text!r} ends below where it starts")
    return range(low, high + 1)


def resolve(charset=None, chars=None, ranges=None, extra=None, where="charset"):
    """The codepoints named by any of the three ways of naming them, unioned and sorted.

    `charset` is a built-in name or a list of them, `chars` literal characters, `ranges` a
    list of codepoints or ranges. `extra` holds the sets the manifest defined; `read_charsets`
    refuses one that clashes with a built-in. Naming none of the three gives the default set.
    """
    sets = {**BUILTIN, **(extra or {})}
    wanted = set()

    names = [charset] if isinstance(charset, str) else charset
    for name in names or ():
        if name not in sets:
            raise ManifestError(f"{where}: no charset called {name!r}. " f"Known: {', '.join(sorted(sets))}")
        wanted |= sets[name]

    if chars is not None:
        if not isinstance(chars, str):
            raise ManifestError(f"{where}: chars takes a string of characters, not {chars!r}")
        wanted |= {ord(c) for c in chars}

    for item in ranges or ():
        wanted |= set(parse_range(str(item), where))

    if not wanted:
        wanted = sets[DEFAULT]
    return sorted(wanted)


def describe(codepoints):
    """Codepoints as the runs they fall into, for a build report."""
    runs = []
    for _, group in itertools.groupby(enumerate(codepoints), lambda pair: pair[1] - pair[0]):
        run = [point for _, point in group]
        runs.append((run[0], run[-1]))
    return ", ".join(f"{low:04x}" if low == high else f"{low:04x}-{high:04x}" for low, high in runs)
