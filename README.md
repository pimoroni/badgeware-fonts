# badgeware-fonts

Builds [alright-fonts](https://github.com/lowfatcode/alright-fonts) `.af` files for Badgeware from a manifest, and publishes them as zipped artefacts.

An `.af` holds glyph outlines as points, rasterised as antialiased polygons by picovector. Text fonts and icon fonts are both supported, either each on their own or packed into one file (with non-overlapping codepoints).

```bash
uv sync
uv run badgeware-fonts list                      # expand fonts.toml into a list of outputs
uv run badgeware-fonts build                     # build and zip everything into out/
uv run badgeware-fonts build lato                # build and zip a single entry
uv run badgeware-fonts build lexend --loose      # build an unzipped .af
uv run badgeware-fonts inspect out/lexend.af
```

Source fonts are fetched on demand into `build/sources`, and kept. Once that holds a manifest's sources the whole build runs offline.

## The manifest

`fonts.toml` holds one `[[font]]` entry per font or family, with three output types to choose from:

| type    | what it packs |
| ------- | ------------- |
| `text`  | glyphs sized by the face, for text |
| `icons` | glyphs fit and centered in a bounding box |
| `merge` | mixed glyphs packed into one file |

```toml
[defaults]
cap = 81

[defaults.text]
quality = 20

[[font]]
name = "lato"
type = "text"
source = "google:Lato"
weights = [400, 700]
charset = "latin"
```

The above builds `lato-400.af` and `lato-700.af`. `[defaults]` applies to every entry, and `[defaults.text]` or `[defaults.icons]` to that specific entry type.

Weight, style, width and cap height each take a singular and a plural form. `weights = [400, 700]` builds both, suffixing each with their weight. `weight = 400` builds a single, unsuffixed font. Give several plurals and the suffixes are their product. `output` overrides the base name a variant is given.

A width is a `wdth` percentage, named after the `font-stretch` keyword for it. `widths = ["condensed", "normal"]` gives `roboto-condensed` and `roboto`. Numbers work too, and the axis interpolates, `73` sits just inside `condensed`.

## Sources

| scheme | resolves to |
| ------ | ----------- |
| `google:Lato` | google/fonts, through the family's `METADATA.pb` |
| `material:outlined` | Material Symbols, `outlined`, `rounded` or `sharp` |
| `github:keshikan/DSEG` | a release asset, or a file in the repository |
| `url:https://.../X.ttf` | any URL |
| `file:src/Roboto.ttf` | a path beside the manifest |

A Google family resolves per weight and style. Google fonts keeps a `METADATA.pb` file alongside each family, listing its faces and axes. A variable family takes the weight as a `wght` coordinate, whereas a static family has a file per weight. `axes = { FILL = 1 }` sets any other variation axis by tag.

`github:` takes `release` and `asset` for a release download, or `ref` and `path` for a file in the tree. A pinned `release` builds the URL directly; `"latest"` picks the latest published release.

Any font built from a source zip needs `member` naming the font inside it. Zip files are searched and the name matched on the end of a path so the manifest need not list a version-stamped directory:

```toml
source = "github:keshikan/DSEG"
release = "v0.46"
asset = "fonts-DSEG_v046.zip"
member = "DSEG7-Classic/DSEG7Classic-Bold.ttf"
licence = "DSEG-LICENSE.txt"
```

The font `licence` is fetched and bundled into the output zip files.

The MIT licence on this repository covers the build tool. Each face a build fetches stays under its own licence, which is why every artefact carries the licences of the fonts inside it.

## Resolution

`cap` is how many units a capital stands in the output, and the only resolution setting. A badge's `draw.add_font` uses that same number.

`.af` has been expanded to support "wide" coordinates over its original byte-sized points. A cap over 127 will be packed with the "wide" bit set, supporting 16-bit point counts for larger text. Use this only for choice glyphs such as clock faces or icons.

For a face with no `H`, such as seven-segment digits, the `cap_from` option picks the character the cap is measured from.

## Quality

`quality` is the pixel height the outlines stay crisp at. Higher is finer, and produces a larger .af file:

| quality | points a glyph | Lexend, 288 chars |
| ------- | -------------- | ----------------- |
| `low` (24) | 34 | 23KB |
| `medium` (48) | 48 | 31KB |
| `high` (81, the default) | 63 | 39KB |
| `max` (240) | 119 | 72KB |
| `400` | 167 | 100KB |

Outlines are simplified within a tolerance. How visible that is depends on how large the glyph is drawn. The tolerance is set such that the error reaches half a pixel at `quality` pixels tall: set `quality` to the largest size a font is intended to be drawn.

## Icons

An `icons` entry fits each glyph to a common bounding box and centers it. `size` sets that box in the same units as the cap, and defaults to a little taller than a capital. Codepoints come either from a corpus of `name codepoint [printable]` lines:

```
sunny        e81a  s
thunderstorm ebdb
```

given as `corpus = "corpus/badge-symbols.txt"`, or inline as `glyphs = ["sunny e81a s"]`.

`.af` stores codepoints as `u16`, and Material Symbols run above `U+FFFF`. What `codepoints` does with that:

| mode | packs at |
| ---- | -------- |
| `remap` | the third field where a line has one, the glyph's codepoint otherwise |
| `preserve` | the glyph's codepoint always |
| `printable` | the third field, required on every line |

Remapping lets badge-side code draw a glyph from an easy to type string, eg: `sunny e81a s` puts the sun at `"s"`. It also makes two icon sets interchangeable: `badge-symbols` and `phosphor-symbols` are different faces using the same eighteen letters, swapping the `.af` swaps the icons.

A charset keeps glyphs at their original codepoints:

```toml
[[font]]
name = "noto-emoji"
type = "icons"
source = "google:Noto Emoji"
ranges = ["U+2190-U+27BF"]
```

Box fitting is also the way to pack a face with no `H` to measure a cap height from.

`web = true` also subsets the same corpus to a `woff2`, for a config UI drawing the same glyphs from the same source. Needs `uv sync --extra web`. Without it the `.af` is written alone, with a note naming the extra.

## Merging

A `merge` entry packs other entries into one file. It takes the glyphs its constituent parts were built with, inheriting their `quality` setting:

```toml
[[font]]
name = "roboto-symbols"
type = "merge"
parts = ["roboto-text", "material-symbols"]
```

The parts must share a grid and a cap. A part with one variant goes into every variant of the merge, which puts one icon set into each weight of a family.

A text font holding `"s"` will not merge with an icon remapped to `"s"`: either preserve the symbol codepoints, as `material-symbols` does, or set `on_collision` to `first` or `last`.

## Artefacts

`fonts.toml` holds the font entries, which are expanded on build into their variants.

`badgeware-fonts build` writes one zip per family into `out/`. Each zip holds every weight, style and width for that family:

```
lato-100.af
lato-100-italic.af
...
lato-900-italic.af
meta.json
licences/OFL.txt
```

Build also outputs a `badgeware-fonts.zip` holding all specified fonts with an `index.json` describing them.

Two things are released from this repository, on tags that keep them apart. A `v1.2.3` tag publishes the build tool to PyPI. A `fonts-v...` tag attaches a zip per family, and `index.json` alongside them, to the release. Each tag fires only its own half.

## Reading a font back

`badgeware-fonts inspect` can be used to debug a font that won't draw.

The `--chars` option picks which glyphs are detailed, and `--all` shows them all:

```
$ uv run badgeware-fonts inspect out/lexend.af --chars Hxp
out/lexend.af: 21628 bytes, 287 glyphs, 9091 points, 75 bytes each
  codepoints 0x20..0x17e, printable ASCII 95/95, degree sign yes
  narrow, 128 units per em
  a capital stands 81
  tallest 'ģ' at 120, furthest point 124 of 127

  char      cp  bbox x    y    w    h  adv  contours
  'H'       72      11    0   65   81   89         1
  'x'      120       2    0   62   61   67         1
  'p'      112       8  -25   60   87   74         2
```

`p` is the only one of those three glyphs with a descender so its `bbox_y` goes negative.

`adv` should be a little wider than `w`, or glyphs will be drawn over the top of each other.

