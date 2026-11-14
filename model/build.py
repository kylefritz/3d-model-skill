# /// script
# requires-python = ">=3.11"
# dependencies = ["trimesh>=4.4", "numpy>=1.26", "pyyaml>=6"]
# ///
"""Build the example house from model/*.yaml into site/.

    uv run model/build.py

Writes site/model/house.glb (everything every option shares), one GLB per value of
each swap slot under site/options/, and site/controls.json, the contract the viewer
reads. Same inputs, same bytes: nothing here is random except seeded shingle widths.
"""

from __future__ import annotations

import hashlib
import itertools
import json
import random
import re
import sys
from fractions import Fraction
from pathlib import Path

import numpy as np
import trimesh
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))   # run as a script: find fingerprint.py next to it
from fingerprint import fingerprint  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
SITE = ROOT / "site"
IN = 0.0254  # the one inches-to-meters conversion, applied at export

# ---------------------------------------------------------------- reading the spec

def inches(v) -> float:
    """16' -> 192, 9' 6" -> 114, 5 1/2" -> 5.5, -2' -> -24, plain numbers are inches."""
    if isinstance(v, (int, float)):
        return float(v)
    s = str(v).strip()
    neg = s.startswith("-")
    s = s.lstrip("-").strip()
    m = re.fullmatch(r"""(?:(\d+(?:\.\d+)?)\s*')?\s*-?\s*(?:(\d+(?:\.\d+)?)?\s*(\d+/\d+)?\s*")?""", s)
    if not m or not any(m.groups()):
        raise ValueError(f"can't read a length from {v!r}")
    feet, whole, frac = m.groups()
    total = float(feet or 0) * 12 + float(whole or 0) + float(Fraction(frac) if frac else 0)
    return -total if neg else total


def load(name):
    return yaml.safe_load((ROOT / "model" / name).read_text())


def resolve(node):
    """Turn every length string in a spec tree into inches. Leaves sources and names alone."""
    if isinstance(node, dict):
        return {k: (v if k in ("source", "side", "name", "label", "url", "note", "lintel_angle", "inner_lintel", "glass", "model", "maker") else resolve(v)) for k, v in node.items()}
    if isinstance(node, list):
        return [resolve(v) for v in node]
    if isinstance(node, str):
        try:
            return inches(node)
        except ValueError:
            return node
    return node


# ---------------------------------------------------------------- geometry kit

class Part:
    """Meshes grouped by material name. A material name is the parameter hook: the
    viewer recolors `paint.body` without knowing what geometry wears it."""

    def __init__(self):
        self.meshes: dict[str, list[trimesh.Trimesh]] = {}
        self.nodes: dict[str, "Part"] = {}

    def add(self, material, mesh):
        if mesh is not None:
            self.meshes.setdefault(material, []).append(mesh)

    def node(self, name) -> "Part":
        """A named child the viewer can move (door.operable)."""
        return self.nodes.setdefault(name, Part())


def hexa(corners):
    """A six-sided solid from 8 corners, indexed like trimesh's unit box: corner[i]
    sits where box vertex i has signs (x, y, z). Covers boxes, wedges and tapers."""
    unit = trimesh.creation.box(extents=(1, 1, 1))
    verts = np.array([corners[tuple(int(c > 0) for c in v)] for v in unit.vertices], float)
    return trimesh.Trimesh(verts, unit.faces.copy(), process=False)


def box(x0, x1, y0, y1, z0, z1):
    x0, x1 = sorted((x0, x1)); y0, y1 = sorted((y0, y1)); z0, z1 = sorted((z0, z1))
    if x1 - x0 < 1e-6 or y1 - y0 < 1e-6 or z1 - z0 < 1e-6:
        return None
    return hexa({(i, j, k): ((x0, x1)[i], (y0, y1)[j], (z0, z1)[k]) for i in (0, 1) for j in (0, 1) for k in (0, 1)})


class Wall:
    """One exterior wall face. Local coordinates: u along the wall from `origin`,
    z up, t outward from the outside face (t < 0 is inside the masonry). Cladding,
    trim and windows are all written in (u, z, t) so they work on any wall."""

    def __init__(self, origin, u_dir, out_dir, length, z0, z1, openings=()):
        self.o = np.array(origin, float)
        self.u = np.array(u_dir, float)
        self.n = np.array(out_dir, float)
        self.length, self.z0, self.z1 = length, z0, z1
        self.openings = list(openings)  # (u0, u1, zb, zt)

    def point(self, u, z, t):
        return self.o + self.u * u + self.n * t + np.array([0, 0, z])

    def solid(self, u0, u1, z0, z1, t0, t1, taper=None):
        """Box in wall coordinates. taper=(t_top) makes a wedge: full t1 at the bottom,
        thinning to t_top at the top, like a lap board or a shingle."""
        if u1 - u0 < 1e-6 or z1 - z0 < 1e-6:
            return None
        c = {}
        for i, j, k in itertools.product((0, 1), repeat=3):
            u = (u0, u1)[i]; z = (z0, z1)[k]
            t = (t0, t1)[j]
            if taper is not None and j == 1 and k == 1:
                t = taper
            c[(i, j, k)] = self.point(u, z, t)
        m = hexa(c)
        if np.linalg.det(np.array([self.u, self.n, [0, 0, 1]])) < 0:
            m.invert()  # a mirrored frame turns the faces inside out
        return m

    def cells(self, z0=None, z1=None):
        """The wall area minus its openings, as rectangles (u0, u1, z0, z1)."""
        z0 = self.z0 if z0 is None else z0
        z1 = self.z1 if z1 is None else z1
        us = sorted({0, self.length, *[c for o in self.openings for c in o[:2]]})
        zs = sorted({z0, z1, *[c for o in self.openings for c in o[2:] if z0 < c < z1]})
        for (ua, ub), (za, zb) in itertools.product(zip(us, us[1:]), zip(zs, zs[1:])):
            uc, zc = (ua + ub) / 2, (za + zb) / 2
            if not any(o[0] < uc < o[1] and o[2] < zc < o[3] for o in self.openings):
                yield ua, ub, za, zb

    def free(self, u0, u1, za, zb):
        """Spans of [u0, u1] not blocked by an opening that overlaps the band za..zb."""
        spans = [(u0, u1)]
        for o in self.openings:
            if o[2] < zb and o[3] > za:
                spans = [s for a, b in spans for s in ((a, min(b, o[0])), (max(a, o[1]), b)) if s[1] - s[0] > 0.01]
        return spans

    def free_z(self, u0, u1, za, zb):
        """Spans of [za, zb] not blocked by an opening that overlaps the strip u0..u1."""
        spans = [(za, zb)]
        for o in self.openings:
            if o[0] < u1 and o[1] > u0:
                spans = [s for a, b in spans for s in ((a, min(b, o[2])), (max(a, o[3]), b)) if s[1] - s[0] > 0.01]
        return spans


def masonry(part, wall, depth, brick_from=0.0, inner_from=0.0):
    """Outer 4" wythe is face brick (`cladding.brick`, recolorable, paintable);
    the rest is the inside of the wall, plaster on the room side.

    brick_from / inner_from start a layer partway along the wall, so two walls that
    meet at a corner never share a volume: faces in one plane z-fight, and here
    one of them would be plaster white."""
    for u0, u1, z0, z1 in wall.cells():
        part.add("cladding.brick", wall.solid(max(u0, brick_from), u1, z0, z1, -4, 0))
        part.add("interior.wall", wall.solid(max(u0, inner_from), u1, z0, z1, -depth, -4))
    return part


# ---------------------------------------------------------------- cladding generators
# Each writes over a wall's outside face (t >= 0) and around its openings.

def clad_brick(part, wall, spec):
    for u0, u1, zb, zt in wall.openings:
        if zb > wall.z0 + 1:  # a sill under windows, not doors
            part.add("concrete", wall.solid(u0 - 2, u1 + 2, zb - 2.5, zb, -4, 1.5))
        bearing = spec["rear_door_install"]["lintel_bearing"]
        part.add("concrete", wall.solid(u0 - bearing, u1 + bearing, zt, zt + 7.5, -4, 0.25))  # lintel, as on the drawings


def casings(part, wall, proud):
    for u0, u1, zb, zt in wall.openings:
        w = 3.5
        part.add("paint.trim", wall.solid(u0 - w, u0, zb, zt + w, 0, proud))
        part.add("paint.trim", wall.solid(u1, u1 + w, zb, zt + w, 0, proud))
        part.add("paint.trim", wall.solid(u0, u1, zt, zt + w, 0, proud))
        if zb > wall.z0 + 1:
            part.add("paint.trim", wall.solid(u0 - w - 1, u1 + w + 1, zb - 1.5, zb, 0, proud + 1))
    for u in (0, wall.length):  # corner boards
        part.add("paint.trim", wall.solid(max(0, u - 5.5) if u else 0, min(wall.length, 5.5) if not u else u, wall.z0, wall.z1, 0, proud))


def clad_lap(part, wall, spec):
    board, exposure, thick = 8.25, 7.0, 5 / 16
    z = wall.z0 + 1
    while z < wall.z1 - 0.5:
        top = min(z + exposure, wall.z1)
        for a, b in wall.free(5.5, wall.length - 5.5, z, top):
            # each course sits on the one below: thick at its drip edge, thin where it laps
            part.add("paint.body", wall.solid(a, b, z, top, 0, thick * 2 + 0.05, taper=thick))
        z += exposure
    casings(part, wall, proud=1.0)


def clad_batten(part, wall, spec):
    panel, batten_w, batten_t, oc = 5 / 16, 2.5, 0.75, 16.0
    for c in wall.cells():
        part.add("paint.body", wall.solid(*c, 0, panel))
    u = oc
    while u < wall.length - 6:
        for za, zb in wall.free_z(u - batten_w / 2, u + batten_w / 2, wall.z0, wall.z1):
            part.add("paint.body", wall.solid(u - batten_w / 2, u + batten_w / 2, za, zb, panel, panel + batten_t))
        u += oc
    casings(part, wall, proud=panel + 1.0)


def clad_shingle(part, wall, spec, seed):
    rng = random.Random(seed)
    exposure, butt, tip = 5.0, 0.45, 0.12
    z, row = wall.z0 + 1, 0
    while z < wall.z1 - 0.5:
        top = min(z + exposure, wall.z1)
        for a, b in wall.free(5.5, wall.length - 5.5, z, top):
            u = a - rng.uniform(0, 6) if row % 2 else a
            while u < b:
                w = rng.choice((4, 5, 6, 7, 8, 9, 10))
                s0, s1 = max(u, a), min(u + w - 0.25, b)
                drop = rng.uniform(0, 0.35)  # butts don't line up perfectly
                part.add("paint.body", wall.solid(s0, s1, z - drop, top, 0, butt, taper=tip))
                u += w
        z += exposure
        row += 1
    casings(part, wall, proud=1.0)


CLADDING = {
    "brick": lambda part, wall, spec, seed: clad_brick(part, wall, spec),
    "lap": lambda part, wall, spec, seed: clad_lap(part, wall, spec),
    "batten": lambda part, wall, spec, seed: clad_batten(part, wall, spec),
    "shingle": clad_shingle,
}


# ---------------------------------------------------------------- windows and doors

def window(part, wall, opening, recess=4.0, frame=2.25):
    u0, u1, zb, zt = opening
    t0, t1 = -recess - 2, -recess
    part.add("window.frame", wall.solid(u0, u1, zt - frame, zt, t0, t1))
    part.add("window.frame", wall.solid(u0, u1, zb, zb + frame, t0, t1))
    part.add("window.frame", wall.solid(u0, u0 + frame, zb, zt, t0, t1))
    part.add("window.frame", wall.solid(u1 - frame, u1, zb, zt, t0, t1))
    mid = (zb + zt) / 2  # meeting rail of a double-hung
    part.add("window.frame", wall.solid(u0, u1, mid - 0.75, mid + 0.75, t0 - 0.5, t1 + 0.5))
    part.add("glass", wall.solid(u0 + frame, u1 - frame, zb + frame, zt - frame, t0 + 0.9, t0 + 1.1))


def front_door(part, wall, opening, transom):
    u0, u1, zb, zt = opening
    door_top = zt - transom
    part.add("paint.trim", wall.solid(u0, u1, door_top - 1.5, door_top, -6, -2))
    part.add("glass", wall.solid(u0 + 2, u1 - 2, door_top, zt - 2, -5, -4.8))
    part.add("paint.trim", wall.solid(u0, u1, zt - 2, zt, -6, -2))
    leaf = wall.solid(u0 + 1, u1 - 1, zb, door_top - 1.5, -5.75, -4)
    part.add("door.front", leaf)
    for za, zc in ((zb + 8, zb + 36), (zb + 44, door_top - 9)):  # two raised panels
        for ua, ub in ((u0 + 5, (u0 + u1) / 2 - 2), ((u0 + u1) / 2 + 2, u1 - 5)):
            part.add("door.front", wall.solid(ua, ub, za, zc, -4, -3.4))
    part.add("hardware", wall.solid(u1 - 5, u1 - 3.5, zb + 36, zb + 38, -3.4, -1.4))


def slider(part, wall, center, door, t_out=-1.0):
    """A two-panel sliding patio door built from its spec sheet: unit size, jamb
    depth, panel stiles and rails. The operable (exterior-side) panel is its own
    node so the viewer can slide it; travel is written to the contract."""
    W, H = door["unit"]["width"], door["unit"]["height"]
    D = door["jamb_depth"]
    stile, top, bottom = door["stile"], door["top_rail"], door["bottom_rail"]
    frame = door.get("frame", 1.75)
    u0, u1 = center - W / 2, center + W / 2
    t_in = t_out - D
    for c in ((u0, u0 + frame, 0, H), (u1 - frame, u1, 0, H), (u0, u1, H - frame, H), (u0, u1, 0, 0.9)):
        part.add("door.frame", wall.solid(c[0], c[1], c[2], c[3], t_in, t_out))
    overlap = door.get("interlock", 2.0)
    pw = (W - 2 * frame + overlap) / 2
    ph = H - frame - 0.9
    track = D / 2
    # fixed panel on the left (inside track), operable on the right (outside track)
    fixed = (u0 + frame, u0 + frame + pw)
    mov = (u1 - frame - pw, u1 - frame)
    for (a, b), node, t in ((fixed, part, t_in + track * 0.25), (mov, part.node("door.operable"), t_out - track * 0.75)):
        th = 1.75
        z0, z1 = 0.9, 0.9 + ph
        for c in ((a, a + stile, z0, z1), (b - stile, b, z0, z1), (a, b, z1 - top, z1), (a, b, z0, z0 + bottom)):
            node.add("door.frame", wall.solid(c[0], c[1], c[2], c[3], t - th / 2, t + th / 2))
        node.add("glass", wall.solid(a + stile, b - stile, z0 + bottom, z1 - top, t - 0.4, t + 0.4))
        if node is not part:
            node.add("hardware", wall.solid(b - stile - 0.4, b - stile + 0.6, z0 + 34, z0 + 42, t + th / 2, t + th / 2 + 1))
    return (u0, u1, 0, H), pw - overlap  # rough opening face, travel in inches


# ---------------------------------------------------------------- shared layouts
# The 3D model, the drawings and the cut list all call these, so they can't disagree.

def rear_opening(spec, p, door):
    """The rear door, from the spec sheet out: unit inside rough opening inside a PT
    buck inside the masonry opening. All in the rear wall's u (along) and z (up)."""
    L = p["wx1"] - p["wx0"]
    c = L / 2
    if not door.get("unit"):
        e = spec["rear"]["existing_rear_window"]
        o = (c - e["width"] / 2, c + e["width"] / 2, e["sill"], e["sill"] + e["height"])
        return {"wall": L, "center": c, "mo": o, "window": o}
    ins = spec["rear_door_install"]
    b = ins["buck"]
    uw, uh = door["unit"]["width"], door["unit"]["height"]
    rw, rh = door["rough_opening"]["width"], door["rough_opening"]["height"]
    return {
        "wall": L, "center": c, "buck": b,
        "unit": (c - uw / 2, c + uw / 2, 0.0, uh),
        "ro": (c - rw / 2, c + rw / 2, 0.0, rh),
        "mo": (c - rw / 2 - b, c + rw / 2 + b, 0.0, rh + b),
        "setback": ins["door_setback"],
        "bearing": ins["lintel_bearing"],
    }


def rail_runs(spec, p):
    """Guard runs on the porch: between posts across the front (skipping the stair
    bay) and down both sides to the house. Each is ((x0, y0), (x1, y1)) in inches."""
    pc = spec["porch"]
    post, d = pc["post"], pc["depth"]
    edge = -d + post / 2 + 0.75
    st = pc["stair"]
    gap = (st["x"] - 2, st["x"] + st["width"] + 2)
    posts = pc["posts_x"]
    runs = [((a + post / 2, edge), (b - post / 2, edge)) for a, b in zip(posts, posts[1:]) if not (a < gap[1] and b > gap[0])]
    runs += [((posts[0], edge + post / 2), (posts[0], -12)), ((posts[-1], edge + post / 2), (posts[-1], -12))]
    return runs


def baluster_layout(length, pc):
    """How many balusters fit a run with every gap under the 4" sphere, and where
    they go: evenly spaced, with the leftover split between the two ends."""
    pitch = pc["baluster"] + pc["baluster_gap"]
    n = int((length - pc["baluster_gap"]) // pitch)
    start = (length - (n * pitch - pc["baluster_gap"])) / 2
    return n, start, pitch


RAIL = {"cap": (3.5, 1.5), "bottom": (2.5, 1.5), "bottom_gap": 3.0}  # 2x4 cap flat, 2x3 bottom rail, 3" off the floor


def porch_part(spec, p, fields):
    part = Part()
    porch(part, porch_variant(spec, *(fields[k]["default"] for k in ("porch_pitch", "rail_height", "porch_depth"))), p)
    return part


def porch_variant(spec, pitch, rail, depth):
    """The spec with one slider position applied. Sliders that change shape are
    built at every step, so the model and the drawings always match."""
    v = json.loads(json.dumps(spec))
    v["porch"].update(roof_pitch=float(pitch), rail_height=float(rail), depth=float(depth) * 12)
    return v


# ---------------------------------------------------------------- the house

def plan(spec):
    m, w = spec["main"], spec["wing"]
    W, D, T = m["width"], m["depth"], m["wall"]
    f1, f2 = m["first_floor"], m["second_floor"]
    roof = f1 + f2
    wing_roof = roof - w["roof_drop"]
    wx0 = W - w["width"] if w["side"] == "east" else 0
    wx1 = wx0 + w["width"]
    wy1 = D + w["depth"]
    return dict(W=W, D=D, T=T, f1=f1, f2=f2, roof=roof, wing_roof=wing_roof, wx0=wx0, wx1=wx1, wy1=wy1, grade=m["grade"])


def walls(spec, p):
    """Every exposed exterior wall, with its openings. The rear wing's back wall is
    left out: its opening depends on the door, so it lives in the rear slot."""
    f, r = spec["front"], spec["rear"]
    W, D, roof, grade = p["W"], p["D"], p["roof"], p["grade"]
    top_front = roof + spec["main"]["parapet"]
    ops = [(f["door"]["x"], f["door"]["x"] + f["door"]["width"], 0, f["door"]["height"] + f["door"]["transom"])]
    for win in f["windows_first"]:
        ops.append((win["x"], win["x"] + win["width"], f["sill_first"], f["sill_first"] + f["window_height"]))
    for win in f["windows_second"]:
        z = p["f1"] + f["sill_second"]
        ops.append((win["x"], win["x"] + win["width"], z, z + f["window_height"]))
    # The front faces -Y. Walk it from the east end so u runs left to right as you face it.
    front = Wall((W, 0, 0), (-1, 0, 0), (0, -1, 0), W, grade, top_front, [(W - b, W - a, zb, zt) for a, b, zb, zt in ops])
    front.facing = "front"
    mw = r["main_window"]
    rear_ops = [(mw["x"], mw["x"] + mw["width"], mw["sill"], mw["sill"] + mw["height"]),
                (mw["x"], mw["x"] + mw["width"], p["f1"] + mw["sill"], p["f1"] + mw["sill"] + mw["height"])]
    rear_main = Wall((0, D, 0), (1, 0, 0), (0, 1, 0), p["wx0"], grade, roof, rear_ops)
    wing_ops = []
    for win in r["wing_windows"]:
        for z in (r["main_window"]["sill"], p["f1"] + r["main_window"]["sill"]):
            wing_ops.append((win["y"], win["y"] + win["width"], z, z + r["wing_window_height"]))
    wing_west = Wall((p["wx0"], p["wy1"], 0), (0, -1, 0), (-1, 0, 0), p["wy1"] - D, grade, p["wing_roof"], [(p["wy1"] - D - b, p["wy1"] - D - a, zb, zt) for a, b, zb, zt in wing_ops])
    return front, rear_main, wing_west


def rear_wall(spec, p, opening):
    return Wall((p["wx0"], p["wy1"], 0), (1, 0, 0), (0, 1, 0), p["wx1"] - p["wx0"], p["grade"], p["wing_roof"], [opening] + [
        (p["wx1"] - p["wx0"] - 48 - 30, p["wx1"] - p["wx0"] - 48, p["f1"] + 30, p["f1"] + 90)])  # bedroom window above


def shell(spec, p) -> Part:
    """Everything every option shares: structure, roof, floors, windows, porch, site."""
    part = Part()
    W, D, T, f1, roof, grade = p["W"], p["D"], p["T"], p["f1"], p["roof"], p["grade"]
    fd = spec["main"]["floor_depth"]
    front, rear_main, wing_west = walls(spec, p)
    masonry(part, front, T)
    masonry(part, rear_main, T)
    # the wing's west wall owns the outside corner's brick; the rear wall owns the plaster behind it
    masonry(part, wing_west, T, inner_from=T)
    f = spec["front"]
    for o in front.openings[1:]:
        window(part, front, o)
    front_door(part, front, front.openings[0], f["door"]["transom"])
    for o in rear_main.openings + wing_west.openings:
        window(part, rear_main if o in rear_main.openings else wing_west, o)
    # party walls (interior faces only show) and the wing's east wall against the neighbor's wing
    part.add("interior.wall", box(0, T, T, D, grade, roof))   # from behind the front wall: a shared face z-fights
    part.add("interior.wall", box(W - T, W, T, D, grade, roof))
    part.add("interior.wall", box(W - T, W, D, p["wy1"] - T, grade, p["wing_roof"]))  # stops where the rear wall starts
    # rear wall of the main block behind the wing: only the doorway between them
    part.add("interior.wall", box(p["wx0"], W - T, D - T, D, f1 - fd, roof))
    # floors: a finish layer on top, ceiling below
    for z in (0, f1):
        for x0, x1, y0, y1 in ((T, W - T, T, D - T), (p["wx0"] + T, W - T, D - T, p["wy1"] - T)):
            part.add("interior.floor", box(x0, x1, y0, y1, z - 1, z))
            part.add("interior.wall", box(x0, x1, y0, y1, z - fd, z - 1))
    # roofs: main and wing, with a parapet coping
    part.add("roof", box(0, W, 0, D, roof, roof + 3))
    part.add("roof", box(p["wx0"], p["wx1"], D, p["wy1"], p["wing_roof"], p["wing_roof"] + 3))
    part.add("concrete", box(0, W, -1, T, roof + spec["main"]["parapet"], roof + spec["main"]["parapet"] + 2))
    for x in (0, W - 2):
        part.add("concrete", box(x, x + 2, 0, D, roof + 3, roof + 6))
    # cornice: frieze, bed, crown box and brackets
    c = f["cornice"]
    top = roof + spec["main"]["parapet"] - 2
    part.add("paint.trim", box(0, W, -c["projection"], 0, top - 4, top))
    part.add("paint.trim", box(0, W, -c["projection"] * 0.55, 0, top - c["height"], top - 4))
    for x in np.linspace(2, W - 7, 5):
        part.add("paint.trim", box(x, x + 5, -c["projection"] * 0.9, 0, top - c["height"] - 4, top - 4))
    site(part, spec, p)
    return part


def porch(part, spec, p):
    pc, W = spec["porch"], p["W"]
    fl = -pc["floor_below_threshold"]
    d, post = pc["depth"], pc["post"]
    grade = p["grade"]
    part.add("porch.floor", box(0, W, -d, 0, fl - 1, fl))
    part.add("porch.trim", box(0, W, -d, -d + 1.5, grade, fl - 1))  # skirt
    for x in (0.0, W - 1.5):
        part.add("porch.trim", box(x, x + 1.5, -d, 0, grade, fl - 1))
    ceiling = fl + pc["ceiling"]
    edge = -d + post / 2 + 0.75
    for x in pc["posts_x"]:
        part.add("porch.trim", box(x - post / 2, x + post / 2, edge - post / 2, edge + post / 2, fl, ceiling))
        part.add("porch.trim", box(x - post / 2 - 1, x + post / 2 + 1, edge - post / 2 - 1, edge + post / 2 + 1, fl, fl + 6))  # plinth
    # beam, ceiling and a shed roof that drops toward the street
    part.add("porch.trim", box(0, W, -d, -d + 7, ceiling, ceiling + 9))
    part.add("porch.ceiling", box(0, W, -d + 7, 0, ceiling, ceiling + 0.75))
    street_end = ceiling + 9
    wall_end = street_end + pc["roof_pitch"] * (d + 6) / 12   # pitch is inches of fall per foot
    for x0 in np.arange(0, W, 24):  # roof as standing-seam strips
        x1 = min(W, x0 + 24)
        part.add("roof.metal", hexa({(i, j, k): ((x0, x1)[i], (-d - 6, 0)[j], ((street_end, wall_end)[j]) + (0, 1)[k]) for i in (0, 1) for j in (0, 1) for k in (0, 1)}))
        part.add("roof.metal", box(x1 - 0.5, x1, -d - 6, 0, street_end + 1, street_end + 2.2))
    part.add("porch.trim", box(0, W, -d - 6.5, -d - 5.5, street_end - 6, street_end + 1))  # fascia
    for a, b in rail_runs(spec, p):
        rail(part, a, b, fl, pc)
    # stairs down to the sidewalk
    st = pc["stair"]
    rise = (fl - grade) / st["risers"]
    # n risers, n - 1 treads: the last step down lands on the walk
    for i in range(st["risers"] - 1):
        z = fl - rise * (i + 1)
        y = -d - st["tread"] * (i + 1)
        part.add("porch.floor", box(st["x"], st["x"] + st["width"], y, y + st["tread"] + 1, z - 1, z))
        part.add("porch.trim", box(st["x"], st["x"] + st["width"], y + st["tread"], y + st["tread"] + 0.75, z, z + rise - 1))
        part.add("porch.trim", box(st["x"], st["x"] + st["width"], y, y + st["tread"], grade, z - 1))
    bottom = -d - st["tread"] * (st["risers"] - 1)
    part.add("porch.trim", box(st["x"], st["x"] + st["width"], bottom, bottom + 0.75, grade, grade + rise - 1))  # last riser
    # walk from the bottom step to the sidewalk, whatever the porch depth
    part.add("concrete", box(st["x"] - 6, st["x"] + st["width"] + 6, spec["site"]["front_line"], bottom, grade - 1, grade))


def rail(part, a, b, fl, pc):
    ax, ay = a; bx, by = b
    length = abs(bx - ax) + abs(by - ay)
    along_x = abs(bx - ax) > abs(by - ay)
    def seg(s0, s1, z0, z1, w):
        if along_x:
            x0, x1 = min(ax, bx) + s0, min(ax, bx) + s1
            return box(x0, x1, ay - w / 2, ay + w / 2, z0, z1)
        y0, y1 = min(ay, by) + s0, min(ay, by) + s1
        return box(ax - w / 2, ax + w / 2, y0, y1, z0, z1)
    h = pc["rail_height"]
    (cw, ct), (bw, bt), bg = RAIL["cap"], RAIL["bottom"], RAIL["bottom_gap"]
    part.add("porch.trim", seg(0, length, fl + h - ct, fl + h, cw))       # cap
    part.add("porch.trim", seg(0, length, fl + bg, fl + bg + bt, bw))     # bottom rail
    n, start, pitch = baluster_layout(length, pc)
    for i in range(n):
        s = start + i * pitch
        part.add("porch.trim", seg(s, s + pc["baluster"], fl + bg + bt, fl + h - ct, pc["baluster"]))


def site(part, spec, p):
    s, W, grade = spec["site"], p["W"], p["grade"]
    d = spec["porch"]["depth"]
    front = s["front_line"]
    yard_end = p["wy1"] + s["yard_depth"]
    n = spec["neighbors"]["count_each_side"]
    span = (-W * (n + 1), W * (n + 2))
    part.add("concrete", box(*span, front - s["sidewalk"], front, grade - 6, grade))
    part.add("concrete", box(*span, front - s["sidewalk"] - 6, front - s["sidewalk"], grade - 12, grade))  # curb
    part.add("street", box(*span, front - s["sidewalk"] - s["street"], front - s["sidewalk"] - 6, grade - 13, grade - 6))
    part.add("ground", box(*span, front, yard_end + 240, grade - 8, grade - 0.5))
    # fence around the yard, boards on a 2x4 frame
    fh = s["fence_height"]
    runs = [((0, p["D"]), (0, yard_end)), ((W, p["wy1"]), (W, yard_end)), ((0, yard_end), (W, yard_end))]
    for (ax, ay), (bx, by) in runs:
        if ax == bx:
            for y in np.arange(ay, by, 5.75):
                part.add("fence", box(ax - 0.4, ax + 0.4, y, min(by, y + 5.5), grade, grade + fh))
        else:
            for x in np.arange(ax, bx, 5.75):
                part.add("fence", box(x, min(bx, x + 5.5), ay - 0.4, ay + 0.4, grade, grade + fh))
    # neighbors: the same rowhouse massed as plain blocks, wings mirrored in pairs
    for k in range(1, n + 1):
        for side in (-1, 1):
            x0 = W * k if side > 0 else -W * k
            part.add("context", box(x0, x0 + W, 0, p["D"], grade, p["roof"] + spec["main"]["parapet"]))
            # wings pair up across a shared wall, so the next house over mirrors ours
            wx0 = x0 if k % 2 else x0 + W - spec["wing"]["width"]
            part.add("context", box(wx0, wx0 + spec["wing"]["width"], p["D"], p["wy1"], grade, p["wing_roof"]))
            part.add("context.trim", box(x0, x0 + W, -14, 0, p["roof"] + 2, p["roof"] + spec["main"]["parapet"] - 2))
    # rear landing and steps at the slider
    x0, x1 = p["wx0"] + 18, p["wx1"] - 18
    part.add("concrete", box(x0, x1, p["wy1"], p["wy1"] + 48, grade, -1.5))
    rise = (-1.5 - grade) / 3
    for i in range(3):
        y = p["wy1"] + 48 + 11 * i
        part.add("concrete", box(x0, x1, y, y + 11, grade, -1.5 - rise * (i + 1)))


def rear(spec, p, door, cladding, seed):
    """The rear wing's back wall, masonry and skin, opened for one door."""
    part = Part()
    o = rear_opening(spec, p, door)
    wall = rear_wall(spec, p, o["mo"])
    masonry(part, wall, p["T"], brick_from=4, inner_from=4)  # starts inside the west wall's brick
    window(part, wall, wall.openings[1])
    if "ro" in o:  # the PT buck between masonry and rough opening, cased like trim
        (m0, m1, _, mh), (r0, r1, _, rh) = o["mo"], o["ro"]
        for a, b in ((m0, r0), (r1, m1)):
            part.add("paint.trim", wall.solid(a, b, 0, rh, -p["T"], -o["setback"]))
        part.add("paint.trim", wall.solid(m0, m1, rh, mh, -p["T"], -o["setback"]))
    CLADDING[cladding](part, wall, spec, seed)
    return part, wall


def door_part(spec, p, door, wall):
    part = Part()
    o = rear_opening(spec, p, door)
    if door.get("unit"):
        _, travel = slider(part, wall, o["center"], door, t_out=-o["setback"])
        return part, travel
    window(part, wall, wall.openings[0])
    return part, 0.0


# ---------------------------------------------------------------- export

Z_UP_TO_Y_UP = np.array([[1, 0, 0, 0], [0, 0, 1, 0], [0, -1, 0, 0], [0, 0, 0, 1]], float)


def to_scene(part: Part, colors: dict, prefix="") -> trimesh.Scene:
    scene = trimesh.Scene()
    S = np.diag([IN, IN, IN, 1.0]) @ Z_UP_TO_Y_UP

    def emit(p: Part, name: str):
        for mat, meshes in sorted(p.meshes.items()):
            mesh = trimesh.util.concatenate(meshes)
            mesh.apply_transform(S)
            mesh.unmerge_vertices()  # flat faces: each face gets its own vertices...
            mesh.vertex_normals = np.repeat(mesh.face_normals, 3, axis=0)   # ...and its face normal (no scipy needed)
            rgba = colors.get(mat, "#cccccc")
            mesh.visual = trimesh.visual.TextureVisuals(material=trimesh.visual.material.PBRMaterial(
                name=mat,
                baseColorFactor=[*(int(rgba[i:i + 2], 16) for i in (1, 3, 5)), 90 if mat == "glass" else 255],
                metallicFactor=0.6 if mat in ("hardware", "roof.metal") else 0.0,
                roughnessFactor=0.15 if mat == "glass" else 0.8,
                alphaMode="BLEND" if mat == "glass" else None,
            ))
            node = f"{name}.{mat}" if name else mat
            scene.add_geometry(mesh, node_name=node, geom_name=node)
        for child, cp in sorted(p.nodes.items()):
            emit(cp, child)

    emit(part, prefix)
    return scene


def write_glb(scene, path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    data = scene.export(file_type="glb", include_normals=True)   # three needs normals for shadows; without them it flat-shades and skips them
    path.write_bytes(data)
    faces = sum(len(g.faces) for g in scene.geometry.values())
    return {"faces": faces, "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()[:16]}


BASE_COLORS = {
    "interior.wall": "#F2EFE8", "interior.floor": "#A9825A", "roof": "#5B5E60", "roof.metal": "#6E7376",
    "concrete": "#BDB8AE", "street": "#4A4C4E", "ground": "#7E9460", "fence": "#9C7B55",
    "context": "#CFC9C0", "context.trim": "#E6E2DA", "glass": "#A9C7D6", "hardware": "#2B2B2B",
    "cladding.brick": "#8C4A36",
}


def main():
    spec = resolve(load("house.yaml"))
    opts = load("options.yaml")
    doors = resolve(load("doors.yaml"))
    p = plan(spec)
    paints = opts["paints"]

    fields = {f["id"]: f for s in opts["sections"] for f in s["fields"]}
    colors = dict(BASE_COLORS)
    for f in fields.values():
        if f["kind"] == "color" and "default" in f:
            for mat in f["materials"]:
                colors[mat] = paints[f["default"]]["hex"]
    colors["door.frame"] = next(iter(doors[fields["door"]["default"]]["colors"].values()))["hex"]

    assets = {}
    assets["model/house.glb"] = write_glb(to_scene(shell(spec, p), colors), SITE / "model/house.glb")

    claddings = list(fields["cladding"]["options"])
    front, rear_main, wing_west = walls(spec, p)
    for i, c in enumerate(claddings):
        part = Part()
        for j, wall in enumerate((front, rear_main, wing_west)):
            CLADDING[c](part, wall, spec, seed=i * 10 + j)
        assets[f"options/cladding-{c}.glb"] = write_glb(to_scene(part, colors), SITE / f"options/cladding-{c}.glb")

    steps = {k: [str(v) for v in fields[k]["values"]] for k in ("porch_pitch", "rail_height", "porch_depth")}
    for pitch, rail, depth in itertools.product(*steps.values()):
        part = Part()
        porch(part, porch_variant(spec, pitch, rail, depth), p)
        rel = f"options/porch-{pitch}-{rail}-{depth}.glb"
        assets[rel] = write_glb(to_scene(part, colors), SITE / rel)

    travel = {}
    for d_id, door in doors.items():
        for i, c in enumerate(claddings):
            part, wall = rear(spec, p, door, c, seed=100 + i)
            assets[f"options/rear-{d_id}-{c}.glb"] = write_glb(to_scene(part, colors), SITE / f"options/rear-{d_id}-{c}.glb")
        part, t = door_part(spec, p, door, wall)
        travel[d_id] = round(t * IN, 4)
        assets[f"options/door-{d_id}.glb"] = write_glb(to_scene(part, colors), SITE / f"options/door-{d_id}.glb")

    # stand-in scan points for the evidence layer (default options, as a phone would see it)
    base = [shell(spec, p), porch_part(spec, p, fields)]
    clad = Part()
    for j, wall in enumerate((front, rear_main, wing_west)):
        CLADDING[fields["cladding"]["default"]](clad, wall, spec, seed=j)
    rp, rw = rear(spec, p, doors[fields["door"]["default"]], fields["cladding"]["default"], seed=100)
    scan = demo_scan(base + [clad, rp])
    (SITE / "scan").mkdir(parents=True, exist_ok=True)
    data = trimesh.Scene(scan).export(file_type="glb")
    (SITE / "scan/points.glb").write_bytes(data)

    contract = contract_for(opts, doors, travel, spec, p)
    contract["assets"] = assets
    contract["scan"] = {"url": "scan/points.glb", "points": len(scan.vertices), "bytes": len(data),
                        "note": "Simulated scan for the demo: points sampled off the model with 1 cm of noise."}
    contract["source_sha256"] = fingerprint()   # see fingerprint.py
    (SITE / "controls.json").write_text(json.dumps(contract, indent=1) + "\n")
    total = sum(a["bytes"] for a in assets.values())
    print(f"wrote {len(assets)} GLBs, {total / 1e6:.2f} MB, {sum(a['faces'] for a in assets.values())} faces")
    write_stats([*assets, "scan/points.glb"])


def write_stats(rels):
    """site/stats.json: what each GLB weighs (raw, gzip, brotli when the CLI is there) and its counts,
    plus model/worklog.yml priced, if there is one. The viewer's "Model details" reads it."""
    sys.path.insert(0, str(ROOT / "tools"))
    import glb_stats        # noqa: E402  stdlib only
    import session_tokens   # noqa: E402  needs pyyaml, which this script has
    out = {"files": glb_stats.site_stats(SITE, rels)}
    worklog = session_tokens.priced()
    if worklog:
        out["worklog"] = worklog
    (SITE / "stats.json").write_text(json.dumps(out, indent=1) + "\n")
    raw =sum(out["files"][r]["bytes"] for r in rels)
    gz = sum(out["files"][r]["gz_bytes"] for r in rels)
    print(f"wrote site/stats.json: {len(rels)} GLBs, {raw / 1e6:.2f} MB raw, {gz / 1e6:.2f} MB gzipped"
          + (f", work log of {len(worklog['sessions'])} sessions" if worklog else ""))


def web(v):
    x, y, z = (inches(c) for c in v)
    return [round(x * IN, 3), round(z * IN, 3), round(-y * IN, 3)]


def contract_for(opts, doors, travel, spec, p):
    paints = opts["paints"]
    sections = []
    for s in opts["sections"]:
        out = []
        for f in s["fields"]:
            g = {k: v for k, v in f.items() if k not in ("palette", "products")}
            if f["kind"] == "color" and "palette" in f:
                g["options"] = [[k, paints[k]["name"], paints[k]["hex"]] for k in f["palette"]]
            if f.get("products"):
                g["options"] = {k: {"label": d["label"], **({"maker": d["maker"], "model": d["model"], "url": d["url"], "note": d.get("note", "")} if d.get("unit") else {"note": d.get("note", "")})} for k, d in doors.items()}
            if f.get("options_by") == "door":
                g["options_by_value"] = {k: [[c, v["name"], v["hex"]] for c, v in d["colors"].items()] for k, d in doors.items()}
            if f["kind"] == "range" and f.get("node") == "door.operable":
                g["travel_by"] = {"door": travel}
            out.append(g)
        sections.append({"name": s["name"], "fields": out, **({"drawings": s["drawings"]} if s.get("drawings") else {})})
    specs = {}
    for k, d in doors.items():
        if d.get("unit"):
            specs[k] = {"unit": f"{fmt(d['unit']['width'])} W x {fmt(d['unit']['height'])} H",
                        "rough_opening": f"{fmt(d['rough_opening']['width'])} x {fmt(d['rough_opening']['height'])}" if d.get("rough_opening") else None,
                        "jamb": fmt(d["jamb_depth"]), "glass": d.get("glass")}
    return {
        "version": 1,
        "name": opts["name"],   # what comments are filed under (worker/index.js MODELS)
        "units": "meters, glTF Y-up",
        "sections": sections,
        "slots": opts["slots"],
        "brick": {"natural": opts["natural_brick"], **opts["brick_color"]},
        "door_specs": specs,
        "views": [{"name": v["name"], "eye": web(v["eye"]), "target": web(v["target"]),
                   **({"section": round(inches(v["section"]) * IN, 3)} if "section" in v else {})} for v in opts["views"]],
        "existing": opts.get("existing", {}),
        "lights": [{"name": l["name"], "at": web(l["at"]), "color": l["color"], "power": l["power"]} for l in opts.get("lights", [])],
        "site": site_contract(spec, p),
        "tours": [{"name": t["name"], "keys": [{"at": k["at"], "eye": web(k["eye"]), "target": web(k["target"]),
                                                  **({"set": k["set"]} if k.get("set") else {})} for k in t["keys"]]}
                  for t in opts.get("tours", [])],
    }


def site_contract(spec, p):
    """Georeference and the lot, for the compass, the sun and the lot lines."""
    s = spec["site"]
    front, W = s["front_line"], p["W"]
    lot = [(0, front), (W, front), (W, front + s["lot_depth"]), (0, front + s["lot_depth"])]
    return {"anchor": s["anchor"], "y_bearing": s["y_bearing"], "ground": round(p["grade"] * IN, 3),
            "lot": [web((x, y, 0))[::2] for x, y in lot]}   # [x, z] pairs in the viewer's frame


def demo_scan(parts, n=90_000, seed=7):
    """A stand-in for a registered phone scan: points sampled off the model's surfaces with
    ~1 cm of noise, skipping roofs (a phone on the ground doesn't see them). A real scan
    goes through tools/register_scan.py and tools/scan_to_points.py instead."""
    meshes = []
    for part in parts:
        for mat, ms in part.meshes.items():
            if not mat.startswith(("roof", "ground", "street", "context")):
                meshes += ms
    mesh = trimesh.util.concatenate(meshes)
    mesh.apply_transform(np.diag([IN, IN, IN, 1.0]) @ Z_UP_TO_Y_UP)
    rng = np.random.default_rng(seed)
    pts, _ = trimesh.sample.sample_surface(mesh, n, seed=seed)
    pts = pts + rng.normal(0, 0.01, pts.shape)
    colors = np.tile(np.array([[40, 170, 150, 255]], np.uint8), (len(pts), 1))
    return trimesh.PointCloud(pts.astype(np.float32), colors=colors)


def fmt(x):
    """79.5 -> 79 1/2". For spec readouts in the viewer."""
    whole = int(x)
    frac = Fraction(x - whole).limit_denominator(16)
    return f'{whole}{" " + str(frac) if frac else ""}"'


if __name__ == "__main__":
    main()
