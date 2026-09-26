"""Draw the tab icons from the mark's geometry in neutral/web/brand.py.

Run it again whenever the mark changes:

    uv run --with pillow python tools/make_icons.py

Pillow is used only here, not by Neutral itself, which is why it is passed with --with
rather than added as a dependency.

Each size is drawn eight times larger and shrunk, which is what gives clean edges at 16
pixels. The Apple icon gets the site's background colour, because iOS turns a
transparent background black.
"""

from __future__ import annotations

import sys
from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from neutral.web.brand import ICON_SIDE, INK, SHAPES, favicon_svg, icon_offset  # noqa: E402

OUT = ROOT / "src" / "neutral" / "web" / "static"
PLANE = (242, 248, 245, 255)  # hsl(150 30% 96%), the page background
SUPERSAMPLE = 8


def draw(size: int, background=(0, 0, 0, 0)) -> Image.Image:
    big = size * SUPERSAMPLE
    scale = big / ICON_SIDE
    dx, dy = icon_offset()
    image = Image.new("RGBA", (big, big), background)
    pen = ImageDraw.Draw(image)
    ink = tuple(int(INK[i : i + 2], 16) for i in (1, 3, 5)) + (255,)
    for shape in SHAPES:
        pen.polygon([((x + dx) * scale, (y + dy) * scale) for x, y in shape], fill=ink)
    return image.resize((size, size), Image.LANCZOS)


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "favicon.svg").write_text(favicon_svg())
    draw(32).save(OUT / "favicon-32.png")
    draw(180, PLANE).save(OUT / "apple-touch-icon.png")
    draw(512).save(OUT / "icon-512.png")
    draw(48).save(OUT / "favicon.ico", sizes=[(16, 16), (32, 32), (48, 48)])
    for name in sorted(p.name for p in OUT.iterdir()):
        print(f"  wrote {name}")


if __name__ == "__main__":
    main()
