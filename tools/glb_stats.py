"""What a GLB weighs: bytes, and the counts a viewer pays for. Standard library only.

    python3 tools/glb_stats.py site/model/house.glb site/options/*.glb   a line per file
    python3 tools/glb_stats.py --json <file.glb>...                      the same as JSON

`model/build.py` calls `site_stats()` for every GLB it writes and puts the result in
`site/stats.json`, which the viewer's "Model details" reads. Only the GLB header and JSON
chunk are parsed; no geometry is decoded.

Counts are per node that draws a mesh, so a mesh placed twice counts twice, as the GPU
sees it. A primitive in mode 0 (POINTS) is a scan layer and counts as scan points, not
vertices or a draw call. gzip size is always given (stdlib); brotli size only when the
`brotli` CLI is on the PATH.
"""
import gzip
import json
import shutil
import struct
import subprocess
import sys
from pathlib import Path

POINTS = 0
TRIANGLES = 4


def stats(path):
    data = Path(path).read_bytes()
    magic, _version, _length = struct.unpack_from("<4sII", data, 0)
    if magic != b"glTF":
        raise ValueError(f"{path}: not a GLB")
    json_len, json_type = struct.unpack_from("<II", data, 12)
    if json_type != 0x4E4F534A:
        raise ValueError(f"{path}: first chunk is not JSON")
    doc = json.loads(data[20:20 + json_len])
    accessors = doc.get("accessors", [])
    views = doc.get("bufferViews", [])
    meshes = doc.get("meshes", [])

    out = {
        "bytes": len(data), "json_bytes": json_len, "image_bytes": 0, "images": len(doc.get("images", [])),
        "nodes": len(doc.get("nodes", [])), "meshes": 0, "materials": len(doc.get("materials", [])),
        "triangles": 0, "vertices": 0, "scan_points": 0,
    }
    for image in doc.get("images", []):
        if "bufferView" in image:
            out["image_bytes"] += views[image["bufferView"]].get("byteLength", 0)
    for node in doc.get("nodes", []):
        if "mesh" not in node:
            continue
        for prim in meshes[node["mesh"]].get("primitives", []):
            mode = prim.get("mode", TRIANGLES)
            position = prim.get("attributes", {}).get("POSITION")
            count = accessors[position]["count"] if position is not None else 0
            if mode == POINTS:
                out["scan_points"] += count
                continue
            out["meshes"] += 1
            out["vertices"] += count
            if mode == TRIANGLES:
                out["triangles"] += (accessors[prim["indices"]]["count"] if "indices" in prim else count) // 3
    return out


def gzip_bytes(path):
    """Roughly what a host that gzips sends (GitHub Pages does). mtime=0 keeps it repeatable."""
    return len(gzip.compress(Path(path).read_bytes(), compresslevel=6, mtime=0))


def brotli_bytes(path, quality=9):
    """What `brotli -q 9` makes of it, or None without the CLI."""
    if not shutil.which("brotli"):
        return None
    result = subprocess.run(["brotli", "-c", "-q", str(quality), str(path)], capture_output=True, check=True)
    return len(result.stdout)


def full(path):
    row = stats(path)
    row["gz_bytes"] = gzip_bytes(path)
    br = brotli_bytes(path)
    if br is not None:
        row["br_bytes"] = br
    return row


def site_stats(site, rels):
    """{rel: stats} for each GLB under the site folder, for site/stats.json."""
    return {rel: full(Path(site) / rel) for rel in rels}


def mb(n):
    return f"{n / 1e6:.2f} MB" if n >= 1e6 else f"{n / 1e3:.0f} KB"


def short(n):
    if n >= 1_000_000:
        return f"{n / 1e6:.1f}M"
    if n >= 10_000:
        return f"{round(n / 1000)}k"
    return f"{n:,}"


def summary_line(row):
    wire = f"gzip {mb(row['gz_bytes'])}" + (f", brotli {mb(row['br_bytes'])}" if "br_bytes" in row else "")
    return (f"{mb(row['bytes'])} ({wire}), {short(row['triangles'])} triangles, {short(row['vertices'])} vertices, "
            f"{row['meshes']:,} draw calls, {row['materials']} materials, {row['images']} textures "
            f"({mb(row['image_bytes'])}), {short(row['scan_points'])} scan points")


def main(argv):
    as_json = "--json" in argv
    paths = [a for a in argv if a != "--json"]
    if not paths:
        print("usage: glb_stats.py [--json] <file.glb>...", file=sys.stderr)
        return 2
    rows = [(Path(p), full(p)) for p in paths]
    if as_json:
        json.dump({str(p): row for p, row in rows}, sys.stdout, indent=1)
        print()
        return 0
    width = max(len(p.stem) for p, _ in rows)
    for p, row in rows:
        print(f"{p.stem:<{width}}  {summary_line(row)}")
    if len(rows) > 1:
        total = {k: sum(r.get(k, 0) for _, r in rows) for k in ("bytes", "gz_bytes", "br_bytes")}
        line = f"{'total':<{width}}  {mb(total['bytes'])} (gzip {mb(total['gz_bytes'])}"
        if all("br_bytes" in r for _, r in rows):
            line += f", brotli {mb(total['br_bytes'])}"
        print(line + ")")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
