"""Build artefacts: a zip per family, and one holding every family.

A family's zip carries each weight, style and width it was built at, a meta.json describing
all of them, and the licences of every face behind them. A release page then lists one asset
per family rather than one per font.

meta.json holds what the .af does not: the cap height each font was built to, which a badge
is given in draw.add_font.

Entries are written in sorted order under a fixed timestamp, and one manifest over the same
source fonts rebuilds to identical bytes.
"""

import json
import pathlib
import zipfile

FIXED_TIME = (1980, 1, 1, 0, 0, 0)


def add(bundle, name, data):
    info = zipfile.ZipInfo(name, date_time=FIXED_TIME)
    info.compress_type = zipfile.ZIP_DEFLATED
    info.external_attr = 0o644 << 16
    bundle.writestr(info, data)


def collect_licences(builds, nest):
    """The licence files for a zip, keyed by the name they take inside it.

    Google families ship differing licences under one name, OFL.txt above all, and a name has
    to be free before a file can take it. `nest` puts each under the entry it covers, which
    the bundle needs to tell the families apart and one family does not.

    A merge carries a licence per part, and two can collide even inside one entry. The
    second is numbered rather than dropped: an artefact must ship every licence it is
    covered by.
    """
    files = {}
    for built in builds:
        folder = f"licences/{built.variant.name}" if nest else "licences"
        for licence in built.licences:
            data = pathlib.Path(licence).read_bytes()
            files[free_name(files, f"{folder}/{licence.name}", data)] = data
    return files


def free_name(files, wanted, data):
    """`wanted`, or the lowest numbered variation no file of different content has taken.

    Each file present blocks at most one candidate, leaving one of these always free.
    """
    stem = pathlib.PurePosixPath(wanted)
    numbered = [f"{stem.with_suffix('')}-{index}{stem.suffix}" for index in range(2, len(files) + 3)]
    return next(name for name in [wanted, *numbered] if files.get(name, data) == data)


def families(builds):
    """The builds grouped by the entry they came from, in manifest order."""
    grouped = {}
    for built in builds:
        grouped.setdefault(built.variant.name, []).append(built)
    return grouped


def family_zip(builds, out, extra=()):
    """One family's zip: every variant of it, their metadata, and the licences covering them.

    `builds` all come from one entry. A single-variant entry gets a zip of one font, which
    keeps a family and a one-off the same shape to unpack.
    """
    name = builds[0].variant.name
    out.mkdir(parents=True, exist_ok=True)
    target = out / f"{name}.zip"
    files = {"meta.json": json.dumps({"name": name, "fonts": [built.metadata() for built in builds]}, indent=2).encode() + b"\n"}
    files.update(collect_licences(builds, nest=False))
    for built in builds:
        files[built.variant.filename] = built.blob
    for path in extra:
        files[pathlib.Path(path).name] = pathlib.Path(path).read_bytes()
    with zipfile.ZipFile(target, "w") as bundle:
        for entry in sorted(files):
            add(bundle, entry, files[entry])
    return target


def bundle_zip(builds, out, name="badgeware-fonts.zip"):
    """Every font in one archive, fonts together and licences deduplicated."""
    out.mkdir(parents=True, exist_ok=True)
    target = out / name
    files = collect_licences(builds, nest=True)
    for built in builds:
        files[built.variant.filename] = built.blob
    files["index.json"] = json.dumps({"fonts": [built.metadata() for built in builds]}, indent=2).encode() + b"\n"
    with zipfile.ZipFile(target, "w") as bundle:
        for entry in sorted(files):
            add(bundle, entry, files[entry])
    return target


def write_loose(built, out):
    """The .af alone, for a checkout that vendors one font."""
    out.mkdir(parents=True, exist_ok=True)
    target = out / built.variant.filename
    target.write_bytes(built.blob)
    return target
