"""Build alright-fonts (.af) files for Badgeware, from a manifest.

    badgeware-fonts build                 every font in fonts.toml, into out/
    badgeware-fonts build lato            one entry, or one variant by its id
    badgeware-fonts list                  what the manifest expands into
    badgeware-fonts inspect out/lato-400.af

`af` is the container and `grid` the sizes; both are pure Python. Everything that touches an
outline needs freetype and shapely, which are dependencies of this package.
"""
