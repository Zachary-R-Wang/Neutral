"""The corner pattern.

A flat plane with the deep green breaking into it from the bottom-right: solid at the
very corner, then dissolving into separate blocks as it reaches inward, until it is gone.

Two details decide whether it reads as a texture or as noise:

**The blocks share edges.** They sit on a fixed grid with no gap and no outline, so
neighbours merge into one body. Near the corner almost every cell is filled and the body
is unbroken; further in, gaps open and it comes apart into pieces.

**It is generated once, not per request.** A seeded pattern means the page looks the same
every time it loads. A pattern that rearranged itself on every navigation would be the
first thing anyone noticed.

The output is three <path> elements rather than a few thousand <rect>s - one per opacity
band - which is the difference between about 4KB of markup and about 90KB.
"""

from __future__ import annotations

import random

BLOCK = 10
WIDTH = 520
HEIGHT = 440

# How far in the pattern reaches, as a fraction of the diagonal. Past this it is gone.
REACH = 0.54

# Opacity bands, densest first. The range is deliberately narrow: the fade is carried by
# how many blocks there are, not by how faint they are.
BANDS = (1.0, 0.975, 0.95)


def _density(x: float, y: float) -> float:
    """How likely a cell is to be filled, given how far it is from the corner.

    Measured as a normalised distance so the front advances as an arc rather than a
    diagonal line, then raised to a power so the solid part stays tight to the corner and
    the dissolve occupies most of the area.
    """
    dx = (WIDTH - x) / WIDTH
    dy = (HEIGHT - y) / HEIGHT
    distance = (dx * dx + dy * dy) ** 0.5
    if distance >= REACH:
        return 0.0
    # Scaled past 1 so the first stretch saturates: the corner itself is an unbroken body
    # rather than a very dense scatter with the odd hole in it. The exponent keeps the
    # dissolve short - a slow falloff spreads blocks across the whole page and reads as
    # noise rather than as something anchored to the corner.
    return max(0.0, min(1.0, (1.0 - (distance / REACH) ** 1.7) * 1.2))


def build(seed: int = 20260924) -> str:
    """The pattern as an SVG fragment, sized to WIDTH x HEIGHT."""
    rng = random.Random(seed)
    paths: dict[float, list[str]] = {band: [] for band in BANDS}

    for row in range(HEIGHT // BLOCK + 1):
        for column in range(WIDTH // BLOCK + 1):
            x, y = column * BLOCK, row * BLOCK
            chance = _density(x + BLOCK / 2, y + BLOCK / 2)
            if chance <= 0 or rng.random() > chance:
                continue

            # Denser cells take the opaque band; the sparse fringe is fractionally
            # lighter, which softens the last few blocks without making them look faded.
            if chance > 0.62:
                band = BANDS[0]
            elif chance > 0.3:
                band = BANDS[1]
            else:
                band = BANDS[2]
            paths[band].append(f"M{x} {y}h{BLOCK}v{BLOCK}h-{BLOCK}z")

    fragments = [
        f'<path fill="var(--corner)" fill-opacity="{band}" d="{"".join(d)}"/>'
        for band, d in paths.items()
        if d
    ]
    return (
        f'<svg class="corner" viewBox="0 0 {WIDTH} {HEIGHT}" '
        f'preserveAspectRatio="xMaxYMax slice" aria-hidden="true" focusable="false">'
        + "".join(fragments)
        + "</svg>"
    )
