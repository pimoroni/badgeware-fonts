"""The command line: build, list, inspect."""

import argparse
import pathlib
import sys

from . import build as builder
from . import charsets, manifest, package, report
from .af import AfError

DEFAULT_MANIFEST = "fonts.toml"
DEFAULT_OUT = "out"


def build_command(args):
    found = manifest.read(args.manifest)
    variants = found.select(args.fonts)
    out = pathlib.Path(args.out)
    cache = pathlib.Path(args.cache) if args.cache else None

    print(f"{len(variants)} of {len(found.variants)} fonts from {found.path}" if args.fonts else f"{len(variants)} fonts from {found.path}")

    def show(built):
        for line in builder.summary(built):
            print(line)

    builds = builder.build_all(found, variants, cache, after=show)

    faulty = builder.faulty(builds)
    if faulty:
        print(f"\n{len(faulty)} of {len(builds)} fonts will not draw correctly, " "so none were written:")
        for built in faulty:
            count = len(built.faults)
            print(f"  {built.variant.id}: {count} glyph{'s' if count > 1 else ''}")
        return 1

    if args.list:
        return 0

    if args.loose:
        for built in builds:
            print(f"  wrote {package.write_loose(built, out)}")
        return 0

    for family in package.families(builds).values():
        extra = []
        for built in family:
            if not built.variant.entry.web:
                continue
            woff = out / "web" / f"{built.variant.id}.woff2"
            made = builder.write_web(built, woff, cache, found)
            if made is None:
                print(f"  no woff2 for {built.variant.id}, which needs fonttools: uv sync --extra web")
                continue
            extra.append(made)
        target = package.family_zip(family, out, extra)
        fonts = "font" if len(family) == 1 else "fonts"
        print(f"  wrote {target}, {len(family)} {fonts}")

    if not args.fonts:
        print(f"  wrote {package.bundle_zip(builds, out)}, {len(builds)} fonts")
    return 0


def list_command(args):
    found = manifest.read(args.manifest)
    for variant in found.select(args.fonts):
        grid = "wide" if variant.wide else "narrow"
        if variant.type == "text":
            detail = f"{len(variant.codepoints)} chars, " f"{charsets.describe(variant.codepoints)}"
        elif variant.type == "icons":
            detail = f"{len(variant.glyphs)} glyphs in a {variant.size()} box, " f"codepoints {variant.entry.codepoints}"
        else:
            detail = "merges " + " + ".join(part.id for part in variant.parts)
        width = f"wdth {variant.width:g}" if variant.width is not None else ""
        print(f"{variant.filename:<34} {variant.type:<6} {grid:<7} cap {variant.cap:<5} " f"weight {variant.weight:<4} {variant.style:<7} {width:<9} {detail}")
    return 0


def inspect_command(args):
    for path in args.fonts:
        for line in report.describe(path, args.chars, args.all):
            print(line)
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(prog="badgeware-fonts", description="Build .af fonts for Badgeware from a manifest.")
    parser.add_argument("--manifest", default=DEFAULT_MANIFEST, help=f"the font manifest (default: {DEFAULT_MANIFEST})")
    commands = parser.add_subparsers(dest="command")

    build_parser = commands.add_parser("build", help="build fonts into zipped artefacts")
    build_parser.add_argument("fonts", nargs="*", help="entry names or variant ids. Everything, given none")
    build_parser.add_argument("--out", default=DEFAULT_OUT, help=f"where the artefacts go (default: {DEFAULT_OUT})")
    build_parser.add_argument("--cache", help="where source fonts are downloaded " "(default: build/sources)")
    build_parser.add_argument("--loose", action="store_true", help="write bare .af files instead of zips, for a checkout " "that vendors one")
    build_parser.add_argument("--list", action="store_true", help="build and report, and write nothing")
    build_parser.set_defaults(run=build_command)

    list_parser = commands.add_parser("list", help="what the manifest expands into")
    list_parser.add_argument("fonts", nargs="*")
    list_parser.set_defaults(run=list_command)

    inspect_parser = commands.add_parser("inspect", help="report what is in an .af")
    inspect_parser.add_argument("fonts", nargs="+")
    inspect_parser.add_argument("--chars", default=report.DETAIL_CHARS, help="which glyphs to show in detail")
    inspect_parser.add_argument("--all", action="store_true", help="show every glyph")
    inspect_parser.set_defaults(run=inspect_command)

    args = parser.parse_args(argv)
    if not args.command:
        parser.print_help()
        return 2
    try:
        return args.run(args)
    except AfError as exc:
        print(f"badgeware-fonts: {exc}", file=sys.stderr)
        return 1
