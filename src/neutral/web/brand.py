"""The Neutral mark: a balance, two arms level on one fulcrum.

The geometry was measured off the founder's 2000x2000 drawing on 2026-09-26 and is kept
here once, so the mark beside the name and every tab icon are drawn from the same
coordinates. The fulcrum is not quite upright - it leans by a little under a degree - and
that is kept exactly as drawn rather than tidied, because it is his drawing.

Coordinates are in the drawing's own units, cropped to the mark: 1600 wide, 635 tall.
"""

from __future__ import annotations

INK = "#586a60"

WIDTH, HEIGHT = 1600, 635

# The two arms and the beam, as one outline.
BEAM = [(0, 0), (187, 0), (187, 186), (1413, 186), (1413, 0), (1600, 0), (1600, 373), (0, 373)]

# The fulcrum. Its top starts inside the beam so the two never show a hairline seam when
# they are drawn small and anti-aliased.
FULCRUM = [(704.6, 317), (890.6, 317), (895.1, 631.4), (709.1, 634)]

SHAPES = (BEAM, FULCRUM)


def _path(offset_x: float = 0, offset_y: float = 0) -> str:
    parts = []
    for shape in SHAPES:
        points = " L".join(f"{x + offset_x:g} {y + offset_y:g}" for x, y in shape)
        parts.append(f"M{points}Z")
    return "".join(parts)


def mark_svg(height_px: float = 10, css_class: str = "mark") -> str:
    """The mark for use inside a page, sized by height. Decorative next to the word."""
    width_px = round(height_px * WIDTH / HEIGHT, 2)
    return (
        f'<svg class="{css_class}" width="{width_px}" height="{height_px}" '
        f'viewBox="0 0 {WIDTH} {HEIGHT}" aria-hidden="true" focusable="false">'
        f'<path fill="{INK}" d="{_path()}"/></svg>'
    )


# Room around the mark on a square tab icon, in drawing units. Enough that it does not
# touch the edge, little enough that it is still legible at 16 pixels.
ICON_PAD = 40
ICON_SIDE = WIDTH + 2 * ICON_PAD


def icon_offset() -> tuple[float, float]:
    """Where the mark sits inside the square icon, centred."""
    return ICON_PAD, (ICON_SIDE - HEIGHT) / 2


def favicon_svg() -> str:
    """The square tab icon, transparent, as a standalone SVG file."""
    dx, dy = icon_offset()
    return (
        '<svg xmlns="http://www.w3.org/2000/svg" '
        f'viewBox="0 0 {ICON_SIDE} {ICON_SIDE}">'
        f'<path fill="{INK}" d="{_path(dx, dy)}"/></svg>\n'
    )
