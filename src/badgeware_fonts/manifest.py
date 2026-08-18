"""fonts.toml: the [[font]] entries, and the variants each one expands into.

An entry is one font or one family; a variant is one output font. Weight, style, width and cap
each take a singular or a plural. The plural expands to a variant per value, suffixing its
name.
"""

import collections
import itertools
import pathlib
import tomllib

from . import charsets, corpus
from .af import ManifestError, units_per_em_for, wide_for
from .grid import DEFAULT_QUALITY, ICON_SIZE_RATIO, QUALITY_NAMES

TYPES = ("text", "icons", "merge")
STYLES = ("normal", "italic")
COLLISION_MODES = ("error", "first", "last")

# Percentages on the `wdth` axis under the names CSS font-stretch gives them, which a manifest
# may use either way round. `normal` is the 100 that `WIDTH_NAMES` maps to no suffix.
WIDTHS = {"ultra-condensed": 50, "extra-condensed": 62.5, "condensed": 75, "semi-condensed": 87.5, "normal": 100, "semi-expanded": 112.5, "expanded": 125, "extra-expanded": 150, "ultra-expanded": 200}
WIDTH_NAMES = {value: name for name, value in WIDTHS.items()} | {100: ""}

# The axes a merge matches its parts on. Cap is left out, `pick_parts` checking it on its own.
MATCH_AXES = {"weight", "style", "width"}

# Keys with no value to check, only whether the type takes them. `KEYS` adds the `FIELDS` keys.
COMMON_KEYS = {"name", "type", "output"}
SOURCE_KEYS = {"source", "licence", "member", "axes", "release", "asset", "ref", "path"}
# What a [charsets.<name>] table takes, the same three ways an entry names its codepoints.
CHARSET_KEYS = ("charset", "chars", "ranges")
PLAIN_KEYS = {
    "text": COMMON_KEYS | SOURCE_KEYS | set(CHARSET_KEYS) | {"cap_from"},
    "icons": COMMON_KEYS | SOURCE_KEYS | set(CHARSET_KEYS) | {"corpus", "glyphs", "web"},
    "merge": COMMON_KEYS | {"parts"},
}


def a_number(low, high):
    """A whole number in range."""

    def read(given, name, where):
        # bool before int: TOML `true` is an int in Python, and a weight of true is a typo.
        if isinstance(given, bool) or not isinstance(given, int) or not low <= given <= high:
            raise ManifestError(f"{where}: {name} {given!r} is not a number from {low} to {high}")
        return given

    return read


def a_choice(allowed):
    """One of a fixed set of names."""

    def read(given, name, where):
        if given not in allowed:
            raise ManifestError(f"{where}: {name} must be one of {', '.join(allowed)}, not {given!r}")
        return given

    return read


def a_width(given, name, where):
    """A percentage on the `wdth` axis, from a number or one of the nine font-stretch keywords.

    `wdth` is continuous, so any percentage in range resolves, named or not.
    """
    if isinstance(given, str):
        if given not in WIDTHS:
            raise ManifestError(f"{where}: {name} {given!r} is not one of " + ", ".join(f"{keyword} ({value:g})" for keyword, value in WIDTHS.items()) + ", or a percentage on the wdth axis")
        return WIDTHS[given]
    if isinstance(given, bool) or not isinstance(given, int | float) or not 25 <= given <= 200:
        raise ManifestError(f"{where}: {name} {given!r} is not a percentage on the wdth axis, from 25 to 200")
    return float(given)


def a_quality(given, name, where):
    """A pixel height, from a number or one of the named levels in `grid`."""
    if isinstance(given, str):
        if given not in QUALITY_NAMES:
            raise ManifestError(f"{where}: {name} {given!r} is not one of " + ", ".join(f"{level} ({value})" for level, value in QUALITY_NAMES.items()) + ", or a pixel height")
        return QUALITY_NAMES[given]
    if isinstance(given, bool) or not isinstance(given, int | float) or not 4 <= given <= 4096:
        raise ManifestError(f"{where}: {name} {given!r} is not a pixel height from 4 to 4096. It is the size the outlines stay crisp to, so higher is finer")
    return float(given)


def drop_default(default):
    """A suffix for every value but the default, which names nothing."""

    def suffix(value):
        return "" if value == default else str(value)

    return suffix


def width_suffix(value):
    """`condensed` for 75, the number for a percentage with no keyword, nothing for 100."""
    named = WIDTH_NAMES.get(value)
    return named if named is not None else f"{value:g}"


# One key an entry can set: how to read a value, what it adds to a variant's name, and the
# entry types that take it. A `plural` takes either form and expands to several variants.
Field = collections.namedtuple("Field", "name read plural default types suffix", defaults=(None, None, TYPES, str))


def field_keys(field):
    """Both forms of a field's key, or the one form where it has no plural."""
    return (field.name,) if field.plural is None else (field.name, field.plural)


def read_values(field, given, where):
    """Every value `given` holds for this field, whichever form it used."""
    if field.plural and field.plural in given:
        listed = given[field.plural]
        if not isinstance(listed, list) or not listed:
            raise ManifestError(f"{where}: {field.plural} takes a non-empty list, not {listed!r}")
        return [field.read(one, field.name, where) for one in listed]
    if field.name in given:
        return [field.read(given[field.name], field.name, where)]
    return [field.default]


TYPE = Field("type", a_choice(TYPES), default="text")
# Every key with a value to check. Axis order is variant-name order: weight comes first.
FIELDS = (
    Field("weight", a_number(1, 1000), plural="weights", default=400),
    Field("style", a_choice(STYLES), plural="styles", default="normal", suffix=drop_default("normal")),
    Field("width", a_width, plural="widths", suffix=width_suffix),
    Field("cap", a_number(1, 4096), plural="caps", default=81),
    Field("quality", a_quality, default=DEFAULT_QUALITY, types=("text", "icons")),
    Field("size", a_number(1, 4096), types=("icons",)),
    Field("codepoints", a_choice(corpus.MODES), default="remap", types=("icons",)),
    Field("on_collision", a_choice(COLLISION_MODES), default="error", types=("merge",)),
)
AXIS_FIELDS = tuple(field for field in FIELDS if field.plural)
SETTING_FIELDS = tuple(field for field in FIELDS if not field.plural)
KEYS = {entry_type: plain | {key for field in FIELDS if entry_type in field.types for key in field_keys(field)} for entry_type, plain in PLAIN_KEYS.items()}


class Entry:
    """One [[font]] entry, checked, with an attribute per key.

    An axis lands under its plural name whichever form the entry used: `weights` holds one
    value for `weight = 400`. `plurals` is which axes suffix a variant's name, `declared`
    which the entry named at all, for a merge to match a part by.

    A setting the type does not take is None.
    """

    def __init__(self, given, where):
        self.where = where
        self.name = given["name"]
        self.type = TYPE.read(given.get(TYPE.name, TYPE.default), TYPE.name, where)
        reject_unknown(given, self.type, where)

        self.plurals = {field.name for field in AXIS_FIELDS if field.plural in given}
        self.declared = {field.name for field in AXIS_FIELDS if any(key in given for key in field_keys(field))}
        for field in AXIS_FIELDS:
            setattr(self, field.plural, read_values(field, given, where))
        for field in SETTING_FIELDS:
            setattr(self, field.name, read_values(field, given, where)[0] if self.type in field.types else None)

        self.output = given.get("output")
        self.source = given.get("source")
        self.licence = given.get("licence")
        self.member = given.get("member")
        self.release = given.get("release")
        self.asset = given.get("asset")
        self.ref = given.get("ref")
        self.path = given.get("path")
        # The `axes` table, variation coordinates by tag. Not the axes an entry expands over.
        self.variations = given.get("axes")
        self.charset = given.get("charset")
        self.chars = given.get("chars")
        self.ranges = given.get("ranges")
        self.cap_from = given.get("cap_from", "H")
        self.corpus = given.get("corpus")
        self.glyphs = given.get("glyphs")
        self.web = bool(given.get("web"))
        self.parts = given.get("parts")

        check_entry(self, given)

    def __repr__(self):
        return f"<Entry {self.name} {self.type}>"


def reject_unknown(given, entry_type, where):
    """A key this type does not take, or both forms of one axis."""
    unknown = set(given) - KEYS[entry_type]
    if unknown:
        raise ManifestError(f"{where}: {entry_type} entries take no {', '.join(sorted(unknown))}. Known keys: {', '.join(sorted(KEYS[entry_type]))}")
    for field in AXIS_FIELDS:
        if field.name in given and field.plural in given:
            raise ManifestError(f"{where}: give {field.name} or {field.plural}, not both")


def check_entry(entry, given):
    """The rules spanning more than one key, which need the read values in place.

    `given` is consulted for what the entry named for itself, which a read value cannot be
    told from a default.
    """
    where = entry.where
    if entry.type == "merge":
        if not isinstance(entry.parts, list) or len(entry.parts) < 2:
            raise ManifestError(f'{where}: merge takes parts = ["a", "b"], two entries or more')
    elif not entry.source:
        raise ManifestError(f'{where}: needs a source, such as "google:Lexend"')

    if entry.type == "icons":
        named = [key for key in ("corpus", "glyphs", *CHARSET_KEYS) if getattr(entry, key)]
        if not named:
            raise ManifestError(f"{where}: needs corpus, glyphs, or a charset to take codepoints from")
        if len(named) > 1:
            raise ManifestError(f"{where}: give one of corpus, glyphs or a charset, not {', '.join(named)}")
        if named[0] not in ("corpus", "glyphs"):
            # A charset carries no names and no remaps: those glyphs keep their codepoints.
            if "codepoints" in given and entry.codepoints != "preserve":
                raise ManifestError(f"{where}: codepoints = {entry.codepoints!r} needs a corpus to read the remaps from")
            entry.codepoints = "preserve"

    if entry.variations is not None and not isinstance(entry.variations, dict):
        raise ManifestError(f"{where}: axes takes a table of tag = value, such as {{ FILL = 1 }}")


class Variant:
    """One output font: an entry with its axes pinned, ready to build."""

    def __init__(self, entry, weight, style, width, cap, suffix):
        self.entry = entry
        self.name = entry.name
        self.type = entry.type
        self.weight = weight
        self.style = style
        self.width = width
        self.cap = cap
        # `output` renames the stem; the suffix still separates the variants of a family.
        self.id = (entry.output or self.name) + suffix
        self.wide = wide_for(cap)
        self.units_per_em = units_per_em_for(cap)
        self.codepoints = ()
        self.glyphs = ()
        self.parts = ()

    @property
    def filename(self):
        return f"{self.id}.af"

    def axes(self):
        """The variation coordinates to set on the face, weight and width included."""
        wanted = {"wght": float(self.weight)}
        if self.width is not None:
            wanted["wdth"] = float(self.width)
        if self.style == "italic":
            wanted["ital"] = 1
        wanted.update(self.entry.variations or {})
        return wanted

    def size(self):
        """The box an icon fills, in the same units as the cap."""
        given = self.entry.size
        return int(given) if given is not None else round(self.cap * ICON_SIZE_RATIO)

    def quality(self):
        """The pixel height the outlines are kept crisp to."""
        return self.entry.quality

    def extent(self):
        """What the glyphs are built to, and what a tolerance is measured against."""
        return self.size() if self.type == "icons" else self.cap

    def key(self):
        """The axes a merge matches its parts on, as a tuple to compare."""
        return (self.weight, self.style, self.width)

    def __repr__(self):
        return f"<Variant {self.id} {self.type} cap {self.cap}>"


class Manifest:
    def __init__(self, path, data):
        self.path = pathlib.Path(path)
        self.root = self.path.parent
        self.charsets = read_charsets(data.get("charsets") or {}, str(path))
        self.entries = read_entries(data, str(path))
        self.variants = expand(self.entries, self.charsets, self.root)
        self.by_id = {variant.id: variant for variant in self.variants}

    def select(self, names):
        """The variants `names` picks out, by entry name or by variant id.

        Every variant if `names` is empty, as a bare `build` leaves it.
        """
        if not names:
            return list(self.variants)
        chosen, unknown = [], []
        for name in names:
            found = [variant for variant in self.variants if name in (variant.id, variant.name)]
            if not found:
                unknown.append(name)
            chosen += found
        if unknown:
            raise ManifestError(f"no font called {', '.join(unknown)} in {self.path}. " f"Known: {', '.join(sorted({v.name for v in self.variants}))}")
        return list(dict.fromkeys(chosen))


def read(path):
    path = pathlib.Path(path)
    if not path.exists():
        raise ManifestError(f"no manifest at {path}")
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError as exc:
        raise ManifestError(f"{path} is not valid TOML: {exc}") from None
    return Manifest(path, data)


def read_charsets(table, where):
    """The charsets a manifest defines for itself. One shadowing a built-in is refused."""
    made = {}
    for name, spec in table.items():
        if name in charsets.BUILTIN:
            raise ManifestError(f"{where}: [charsets.{name}] shadows a built-in set")
        if not isinstance(spec, dict):
            raise ManifestError(f"{where}: [charsets.{name}] takes charset, chars or ranges")
        unknown = set(spec) - set(CHARSET_KEYS)
        if unknown:
            raise ManifestError(f"{where}: [charsets.{name}] takes no {', '.join(sorted(unknown))}. Known keys: {', '.join(sorted(CHARSET_KEYS))}")
        found = charsets.resolve(spec.get("charset"), spec.get("chars"), spec.get("ranges"), made, f"{where} [charsets.{name}]")
        made[name] = set(found)
    return made


def read_entries(data, where):
    """The [[font]] entries as checked `Entry` objects, filled in from [defaults].

    A key an entry sets for itself stands; [defaults] reaches only what it left alone.
    """
    common, per_type = split_defaults(data.get("defaults") or {}, where)
    listed = data.get("font")
    if not listed:
        raise ManifestError(f"{where} has no [[font]] entries")

    entries, seen = [], set()
    for index, given in enumerate(listed, 1):
        if not isinstance(given, dict):
            raise ManifestError(f"{where}: [[font]] {index} is not a table")
        entry_type = given.get("type", "text")
        filled = merge_defaults(given, {**common, **per_type.get(entry_type, {})})
        name = filled.get("name")
        if not name or not isinstance(name, str):
            raise ManifestError(f"{where}: [[font]] {index} has no name")
        if name in seen:
            raise ManifestError(f"{where}: two entries are called {name!r}")
        seen.add(name)
        entries.append(Entry(filled, f"{where} [{name}]"))

    for entry in entries:
        if entry.type != "merge":
            continue
        for part in entry.parts:
            if part not in seen:
                raise ManifestError(f"{entry.where}: no entry called {part!r} to merge")
            if part == entry.name:
                raise ManifestError(f"{entry.where}: cannot merge with itself")
    return entries


def split_defaults(table, where):
    """[defaults] applies to every entry, [defaults.<type>] to one type of entry."""
    reject_both_forms(table, "[defaults]", where, ", so no entry can take either")
    per_type = {}
    for entry_type in TYPES:
        given = table.get(entry_type)
        if given is None:
            continue
        if not isinstance(given, dict):
            raise ManifestError(f"{where}: [defaults.{entry_type}] takes a table of settings")
        reject_both_forms(given, f"[defaults.{entry_type}]", where, "")
        per_type[entry_type] = given
    return {key: value for key, value in table.items() if key not in TYPES}, per_type


def reject_both_forms(table, which, where, tail):
    """Both forms of one axis in a defaults table, which no entry could then override."""
    for field in AXIS_FIELDS:
        if field.name in table and field.plural in table:
            raise ManifestError(f"{where}: {which} gives {field.name} and {field.plural}{tail}")


def merge_defaults(given, defaults):
    """[defaults] under an entry, where an entry's plural key replaces a default's singular.

    A default cap must not land beside an entry's caps: both forms of one axis is refused.
    """
    entry = dict(given)
    axis_keys = {key for field in AXIS_FIELDS for key in field_keys(field)}
    for field in AXIS_FIELDS:
        keys = field_keys(field)
        if any(key in entry for key in keys):
            continue
        for key in keys:
            if key in defaults:
                entry[key] = defaults[key]
    for key, value in defaults.items():
        if key not in entry and key not in axis_keys:
            entry[key] = value
    return entry


def suffixes(entry):
    """The variants an entry expands into, each as its axis values and the name they add.

    The product of the axes, in `AXIS_FIELDS` order, which is the order a name reads in. Only
    a plural adds to the name: `weight = 400` and `weights = [400]` differ by the suffix.
    """
    made = []
    for combination in itertools.product(*(getattr(entry, field.plural) for field in AXIS_FIELDS)):
        parts = [field.suffix(value) for field, value in zip(AXIS_FIELDS, combination, strict=True) if field.name in entry.plurals]
        made.append((*combination, "".join(f"-{part}" for part in parts if part)))
    return made


def expand(entries, extra_charsets, root):
    """Every entry as its variants, with charsets resolved and corpora read."""
    variants, by_name = [], {}
    for entry in entries:
        made = []
        for weight, style, width, cap, suffix in suffixes(entry):
            variant = Variant(entry, weight, style, width, cap, suffix)
            if entry.type == "text":
                variant.codepoints = entry_charset(entry, extra_charsets)
            elif entry.type == "icons":
                variant.glyphs = read_glyphs(entry, root, extra_charsets)
            made.append(variant)
        by_name[entry.name] = made
        variants += made

    for variant in variants:
        if variant.type == "merge":
            variant.parts = pick_parts(variant, by_name)
    counts = collections.Counter(variant.id for variant in variants)
    duplicate = sorted(name for name, count in counts.items() if count > 1)
    if duplicate:
        raise ManifestError("two variants would be written to the same file: " + ", ".join(duplicate) + ". Give one of them an output name")
    return variants


def entry_charset(entry, extra_charsets):
    """The codepoints an entry names, whichever of the three ways it named them."""
    return charsets.resolve(entry.charset, entry.chars, entry.ranges, extra_charsets, entry.where)


def read_glyphs(entry, root, extra_charsets=None):
    """The glyphs an icon entry packs, from a corpus, an inline list, or a charset.

    A charset gives codepoints and no third field, which `check_entry` pins to `preserve`.
    """
    if entry.corpus:
        wanted = corpus.read(root / entry.corpus)
    elif entry.glyphs:
        wanted = corpus.parse(entry.glyphs, f"{entry.where} glyphs")
    else:
        wanted = [corpus.Wanted(f"U+{point:04X}", point) for point in entry_charset(entry, extra_charsets)]
    problems = corpus.check(wanted, entry.codepoints)
    if problems:
        raise ManifestError(f"{entry.where}: " + "; ".join(problems))
    return wanted


def pick_parts(variant, by_name):
    """Which variant of each part `variant` takes its glyphs from.

    A part that expands to one variant goes into every variant of the merge, which is how a
    single icon set reaches each weight of a family. A part that expands to several is matched
    on weight, style and width. The merge has to declare those axes itself: left at the default
    of 400, a merge over a family built at 400 and 700 would quietly cover only one weight.
    """
    declared = bool(variant.entry.declared & MATCH_AXES)
    chosen = []
    for name in variant.entry.parts:
        candidates = by_name[name]
        if len(candidates) == 1:
            chosen.append(candidates[0])
            continue
        if not declared:
            raise ManifestError(
                f"[{variant.name}]: {name} expands to {len(candidates)} variants, and this merge "
                "declares no weight, style or width to match one by. Add weights = [...] to it. "
                f"{name} has " + ", ".join(other.id for other in candidates)
            )
        match = [other for other in candidates if other.key() == variant.key()]
        if not match:
            raise ManifestError(f"[{variant.name}] {variant.id}: {name} has no {variant.style} variant at " f"weight {variant.weight}. It has " + ", ".join(other.id for other in candidates))
        chosen.append(match[0])
    grids = {(other.wide, other.units_per_em) for other in chosen}
    if len(grids) > 1:
        raise ManifestError(
            f"[{variant.name}] {variant.id}: the parts are built to different "
            "grids, so they cannot share a file. Give them the same cap: " + ", ".join(f"{other.id} at {other.cap}" for other in chosen)
        )
    if chosen[0].cap != variant.cap:
        raise ManifestError(f"[{variant.name}] {variant.id}: cap {variant.cap} is not the " f"{chosen[0].cap} its parts are built to")
    return chosen
