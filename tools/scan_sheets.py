# /// script
# requires-python = ">=3.11"
# dependencies = ["trimesh>=4.4", "numpy>=1.26", "pillow>=10", "scipy>=1.11", "shapely>=2", "networkx>=3", "rtree>=1.2"]
# ///
"""Scan-vs-model sheets: the registered scan and the model, cut in the same places.

    uv run tools/scan_sheets.py                                  # the demo's simulated scan
    uv run tools/scan_sheets.py out/rear-deviation.ply --out out/sheets

For each floor, a plan cut at 4' above the floor: scan points in that band, top-down, in
black; the model cut at the same height in red; a 1' grid. Then a long section down the
middle of the house. Each sheet prints how far the scan points in its band are from the
model (median, 90th percentile). Read them: a wall the scan sees 3" from where the model
puts it is either a measurement to fix or furniture to ignore, and only you can tell which.

Points are in the viewer's frame (meters, glTF Y-up), which is what register_scan.py writes.
"""

import argparse
import json
import sys
from pathlib import Path

import numpy as np
import trimesh
from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]
SITE = ROOT / "site"
FT = 0.3048
PX = 60  # pixels per meter


def model_mesh():
    """The shell plus the default slot files: what the viewer shows on first load."""
    contract = json.loads((SITE / "controls.json").read_text())
    fields = {f["id"]: f for s in contract["sections"] for f in s["fields"]}
    files = ["model/house.glb"] + [t.format(**{k: fields[k].get("default") for k in fields}) for t in contract["slots"].values()]
    meshes = []
    for f in files:
        sc = trimesh.load(SITE / f, force="scene")
        for node in sc.graph.nodes_geometry:
            T, name = sc.graph[node]
            if any(k in name for k in ("ground", "street", "context", "glass")):   # not what a scan measures
                continue
            meshes.append(sc.geometry[name].copy().apply_transform(T))
    return trimesh.util.concatenate(meshes), contract


def load_points(path):
    g = trimesh.load(path, force="scene") if Path(path).suffix == ".glb" else trimesh.load(path)
    if isinstance(g, trimesh.Scene):
        g = next(iter(g.geometry.values()))
    return np.asarray(g.vertices)


def grid(draw, w, h, origin, scale, font):
    for i, k in enumerate(np.arange(0, max(w, h) / scale / FT + 1)):
        x = origin[0] + k * FT * scale
        y = origin[1] - k * FT * scale
        c = (215, 215, 215) if k % 5 else (175, 175, 175)
        if x < w:
            draw.line([(x, 0), (x, h)], fill=c)
        if y > 0:
            draw.line([(0, y), (w, y)], fill=c)
        if k % 5 == 0 and k:
            if x < w:
                draw.text((x + 2, h - 14), f"{int(k)}'", fill=(120, 120, 120), font=font)
            if y > 0:
                draw.text((2, y + 2), f"{int(k)}'", fill=(120, 120, 120), font=font)


def sheet(title, pts2, segs2, stats, out, font, big):
    lo = np.minimum(pts2.min(0) if len(pts2) else [0, 0], np.min(segs2.reshape(-1, 2), 0) if len(segs2) else [0, 0]) - 1
    hi = np.maximum(pts2.max(0) if len(pts2) else [1, 1], np.max(segs2.reshape(-1, 2), 0) if len(segs2) else [1, 1]) + 1
    w, h = int((hi[0] - lo[0]) * PX), int((hi[1] - lo[1]) * PX) + 40
    img = Image.new("RGB", (w, h), "white")
    d = ImageDraw.Draw(img)
    to = lambda p: ((p[0] - lo[0]) * PX, h - 40 - (p[1] - lo[1]) * PX)
    grid(d, w, h - 40, to((np.floor(lo[0] / FT) * FT, np.floor(lo[1] / FT) * FT)), PX, font)
    for p in pts2:
        x, y = to(p)
        d.point((x, y), fill=(20, 20, 20))
    for a, b in segs2:
        d.line([to(a), to(b)], fill=(214, 40, 40), width=2)
    d.rectangle([0, h - 40, w, h], fill=(246, 244, 239))
    d.text((8, h - 34), title, fill=(20, 20, 20), font=big)
    d.text((8, h - 16), stats + "   black: scan points   red: model cut   grid: 1'", fill=(90, 90, 90), font=font)
    img.save(out)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("points", nargs="?", default=str(SITE / "scan/points.glb"))
    ap.add_argument("--out", default=str(ROOT / "out/scan-sheets"))
    a = ap.parse_args()
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    mesh, contract = model_mesh()
    pts = load_points(a.points)
    try:
        font = ImageFont.truetype("Helvetica.ttc", 12)
        big = ImageFont.truetype("Helvetica.ttc", 15)
    except OSError:
        font = big = ImageFont.load_default()

    sections = [v for v in contract["views"] if "section" in v]
    written = []
    for v in sections:
        z = v["section"]
        band = pts[np.abs(pts[:, 1] - z) < 0.25]                     # a 20" band around the cut
        # raw cut segments, not stitched paths: stitching separate boxes draws false diagonals
        segs = trimesh.intersections.mesh_plane(mesh, plane_normal=[0, 1, 0], plane_origin=[0, z, 0])
        segs2 = segs[:, :, [0, 2]] * [1, -1]
        stats = residual(mesh, band)
        inch = round(z / 0.0254)
        written.append(sheet(f"{v['name']}: cut {inch // 12}'-{inch % 12}\" above the first floor", band[:, [0, 2]] * [1, -1], segs2, stats,
                             out / f"plan-{v['name'].lower().replace(' ', '-')}.png", font, big))
    # long section down the middle of the house, looking east
    xc = float(np.median(mesh.vertices[:, 0]))
    band = pts[np.abs(pts[:, 0] - xc) < 0.15]
    segs = trimesh.intersections.mesh_plane(mesh, plane_normal=[1, 0, 0], plane_origin=[xc, 0, 0])
    segs2 = np.stack([-segs[:, :, 2], segs[:, :, 1]], axis=-1)
    written.append(sheet("Long section down the middle, front at left", np.c_[-band[:, 2], band[:, 1]], segs2, residual(mesh, band),
                         out / "section-long.png", font, big))
    # an index page, so the sheets can ship with the site (CI writes them to site/scan/sheets/)
    imgs = "".join(f'<figure><img src="{w.name}" alt="{w.stem}"><figcaption>{w.stem.replace("-", " ")}</figcaption></figure>' for w in written)
    (out / "index.html").write_text(
        '<!doctype html><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Scan vs model</title>'
        '<style>body{font:15px/1.5 system-ui,sans-serif;margin:0;padding:16px;max-width:1100px}img{max-width:100%;border:1px solid #ddd}figure{margin:0 0 24px}</style>'
        '<p><a href="../../">&larr; 3D model</a></p><h1>Scan vs model</h1><p>Black: scan points in a band around each cut. Red: the model cut at the same place. '
        'Grid: 1 foot. The demo scan is simulated, so it agrees to about 1 cm; a real one will show you where to look.</p>' + imgs)
    for w in written:
        print(w)


def residual(mesh, pts, n=4000):
    if len(pts) == 0:
        return "no scan points in this band"
    sample = pts[np.random.default_rng(0).choice(len(pts), min(n, len(pts)), replace=False)]
    _, d, _ = trimesh.proximity.closest_point(mesh, sample)
    return f"{len(pts):,} points; to the model: median {np.median(d) * 100:.1f} cm, 90% within {np.percentile(d, 90) * 100:.1f} cm"


if __name__ == "__main__":
    main()
