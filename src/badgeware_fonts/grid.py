"""The grid a glyph is built to, and what `quality` means against it.

Not the container format, which is `af`: these are the choices this repository makes about
how big a glyph is and how finely it is cut. Kept apart from `glyphs`, which a manifest
resolves without.
"""

from .af import REFERENCE_CAP

# An icon stands a little taller than the text beside it: 100 units against an 81 cap.
ICON_SIZE_RATIO = 100 / 81

# How much of its ink an advance must cover before it reads as a units mix-up. A mix-up
# leaves a ratio near 0.03, where an accent legitimately reaches 0.5.
MIN_ADVANCE_RATIO = 0.1

# The sub-pixel error simplification is allowed to reach at `quality` pixels tall.
CRISP_ERROR = 0.5
# The reference cap, at which the default tolerance comes out at half a unit.
DEFAULT_QUALITY = float(REFERENCE_CAP)
QUALITY_NAMES = {"low": 24.0, "medium": 48.0, "high": DEFAULT_QUALITY, "max": 240.0}


def tolerance_for(quality, extent):
    """Output units a point may move, for outlines crisp to `quality` pixels.

    Simplification moves a point by at most `tolerance`, which renders as
    tolerance * pixels / extent, reaching half a pixel of error at
    extent / (2 * tolerance) pixels tall. Turned round for a wanted size the extent cancels,
    leaving one quality the same crispness at any cap.

    `extent` is what the glyphs were built to: the cap for text, the box for an icon.
    """
    return CRISP_ERROR * extent / quality
