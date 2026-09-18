"""Everything that is specific to one machine, one footage library or one brand.

The pipeline itself is generic; these are the values that are not. All of them
read from the environment so a checkout runs somewhere else without an edit, and
all of them have a default that keeps the repo working out of the box.

    VSP_PROXIES    footage proxies, one subfolder per pool      (default: ./footage/proxies)
    VSP_ORIGINALS  full-resolution originals, same naming        (default: ./footage/originals)
    VSP_OVERLAYS   logo and music bed                            (default: ./overlays)
    VSP_FONT       a .ttf for captions                           (default: DejaVuSans-Bold)
    VSP_BRAND      end-card and caption-rule colour, 0xRRGGBB    (default: 0x1f6feb)
    VSP_CLOSING    end-card closing line                         (default: a placeholder)

Fonts are the one genuinely awkward value. ffmpeg's `drawtext` parses its
argument inside a filter string, so a Windows drive colon has to be escaped
there and must NOT be escaped anywhere else — `font_drawtext()` is the escaped
form and `FONT` is the plain one. Getting this wrong fails at render, not at
import, which is why they are two names rather than one.
"""
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _path(var, *default):
    v = os.environ.get(var)
    return v if v else os.path.join(ROOT, *default)


PROXIES = _path("VSP_PROXIES", "footage", "proxies")
ORIGINALS = _path("VSP_ORIGINALS", "footage", "originals")
OVERLAYS = _path("VSP_OVERLAYS", "overlays")

# Leading slate digit -> the proxy subfolder it lives in. A slate code is
# "<pool><roll> <take> <cam>", e.g. "1K 02 A". Override to match your own
# library; the only requirement is that the leading character selects a folder.
POOLS = {
    "1": "pool-1",
    "2": "pool-2",
    "3": "pool-3",
    "4": "pool-4",
}

# Same idea for the originals, which are usually filed by location rather than
# by pool. Empty string means "directly in ORIGINALS".
ORIGIN_DIRS = {k: v for k, v in POOLS.items()}

LOGO = os.path.join(OVERLAYS, "logo.png")
MUSIC = os.path.join(OVERLAYS, "bed.mp3")

FONT = os.environ.get("VSP_FONT", "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf")

BRAND = os.environ.get("VSP_BRAND", "0x1f6feb")
CLOSING = os.environ.get("VSP_CLOSING", "YOUR CLOSING LINE HERE")


def font_drawtext():
    """FONT in the form ffmpeg's drawtext wants inside a filter string.

    A drive colon separates filter arguments, so `C:/x.ttf` has to become
    `C\\:/x.ttf`. A POSIX path needs no escaping and is returned unchanged.
    """
    if len(FONT) > 1 and FONT[1] == ":":
        return FONT[0] + "\\:" + FONT[2:].replace("\\", "/")
    return FONT
