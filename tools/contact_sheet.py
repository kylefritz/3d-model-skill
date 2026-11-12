# /// script
# requires-python = ">=3.11"
# dependencies = ["pillow>=10"]
# ///
"""Tile several stills into one labelled contact sheet, so an agent reads one small image
instead of several full-size ones.

    uv run tools/contact_sheet.py out/sheet.jpg docs/img/street-dusk.png docs/img/inside.png
    uv run tools/contact_sheet.py out/sheet.jpg --dir docs/img street-dusk inside rear-none

With --dir, a bare name is looked up as <dir>/<name>.png, .jpg or .jpeg. Each tile is
labelled with its file stem. The sheet is at most 1568 px on its long side (about what a
model sees of an image anyway) and never upscales a draft.
"""
import argparse
import math
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

MAX_SIDE = 1568
LABEL_H = 22
GAP = 4


def find(folder, name):
    p = Path(name)
    if p.suffix:
        hit = folder / p
        if hit.exists():
            return hit
    for ext in (".png", ".jpg", ".jpeg"):
        if (folder / f"{name}{ext}").exists():
            return folder / f"{name}{ext}"
    raise SystemExit(f"no still {name!r} in {folder}")


def sheet(paths, out):
    images = [Image.open(p).convert("RGB") for p in paths]
    n = len(images)
    aspect = images[0].width / images[0].height
    # The column count whose sheet comes out closest to square.
    cols = min(range(1, n + 1), key=lambda c: abs(math.log((c * aspect) / (math.ceil(n / c) * (1 + LABEL_H / 400)))))
    rows = math.ceil(n / cols)
    tile_w = min((MAX_SIDE - GAP * (cols + 1)) // cols, images[0].width)
    tile_h = round(tile_w / aspect)
    if rows * (tile_h + LABEL_H + GAP) + GAP > MAX_SIDE:
        tile_h = (MAX_SIDE - GAP) // rows - LABEL_H - GAP
        tile_w = round(tile_h * aspect)
    width, height = cols * (tile_w + GAP) + GAP, rows * (tile_h + LABEL_H + GAP) + GAP
    canvas = Image.new("RGB", (width, height), (24, 24, 24))
    draw = ImageDraw.Draw(canvas)
    try:
        font = ImageFont.load_default(size=14)
    except TypeError:
        font = ImageFont.load_default()
    for i, (path, img) in enumerate(zip(paths, images)):
        x, y = GAP + (i % cols) * (tile_w + GAP), GAP + (i // cols) * (tile_h + LABEL_H + GAP)
        draw.text((x + 3, y + 3), Path(path).stem, fill=(255, 255, 255), font=font)
        # Letterbox a still whose shape differs from the first, rather than stretching it.
        fit = img.copy()
        fit.thumbnail((tile_w, tile_h), Image.LANCZOS)
        canvas.paste(fit, (x + (tile_w - fit.width) // 2, y + LABEL_H + (tile_h - fit.height) // 2))
    Path(out).parent.mkdir(parents=True, exist_ok=True)
    canvas.save(out, quality=85)
    return canvas.size


def main():
    ap = argparse.ArgumentParser(description="One labelled contact sheet from several stills.")
    ap.add_argument("out")
    ap.add_argument("stills", nargs="+")
    ap.add_argument("--dir", type=Path, help="look bare names up in this folder")
    args = ap.parse_args()
    paths = [find(args.dir, s) for s in args.stills] if args.dir else [Path(s) for s in args.stills]
    for p in paths:
        if not p.exists():
            raise SystemExit(f"no such still: {p}")
    w, h = sheet(paths, args.out)
    print(f"wrote {args.out} {w}x{h}")


if __name__ == "__main__":
    main()
