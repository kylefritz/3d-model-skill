# /// script
# requires-python = ">=3.11"
# dependencies = ["trimesh>=4.4", "numpy>=1.26", "pyyaml>=6"]
# ///
"""Check the spec and the built site. Run after build.py; CI runs both.

    uv run model/check.py

Fails loudly on: a dimension group with no source, a door that doesn't fit its
rough opening or its wall, a porch that breaks the basic code numbers, a slot file
that's missing for some combination of choices, or a site too big to load on a phone.
"""

import itertools
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import build  # noqa: E402

problems = []


def frac_in(x):
    sys.path.insert(0, str(Path(__file__).parent))
    import drawings
    return drawings.frac(x)


def check(ok, msg):
    if not ok:
        problems.append(msg)


# the tape-sketch parser
for text, want in {"16'": 192, "9' 6\"": 114, "5 1/2\"": 5.5, "-2'": -24, "5' 10 1/2\"": 70.5, "4 9/16\"": 4.5625, 12: 12}.items():
    check(abs(build.inches(text) - want) < 1e-9, f"inches({text!r}) should be {want}, got {build.inches(text)}")

spec = build.resolve(build.load("house.yaml"))
doors = build.resolve(build.load("doors.yaml"))
opts = build.load("options.yaml")
p = build.plan(spec)

# every group of numbers says where it came from
for group, values in spec.items():
    check(isinstance(values, dict) and values.get("source") in {"tape", "scan", "drawing", "spec", "estimate"},
          f"house.yaml: {group} needs a source (tape, scan, drawing, spec or estimate)")

# doors: unit fits the rough opening, the opening fits the wall
wall_len = p["wx1"] - p["wx0"]
for k, d in doors.items():
    if not d.get("unit"):
        continue
    check(d.get("source") == "spec" and d.get("url", "").startswith("https://"), f"doors.yaml: {k} needs source: spec and a spec sheet url")
    u, ro = d["unit"], d["rough_opening"]
    for dim in ("width", "height"):
        gap = ro[dim] - u[dim]
        check(0 <= gap <= 1.5, f"{k}: rough opening {dim} {ro[dim]}\" vs unit {u[dim]}\" leaves {gap}\" (want 0 to 1 1/2\")")
    side = (wall_len - ro["width"]) / 2
    check(side >= 12, f"{k}: only {side:.1f}\" of masonry each side of the opening (want 12\"+ for the lintel bearing)")
    check(ro["height"] + 8 < p["f1"] - spec["main"]["floor_depth"], f"{k}: no room for a lintel under the second floor")
    check(d["stile"] * 2 < u["width"] / 2, f"{k}: stiles wider than the panel")
    check(len(d["colors"]) >= 2, f"{k}: list the maker's real frame colors")

# porch: the numbers an inspector checks first (IRC R311.7, R312)
pc = spec["porch"]
rise = (-pc["floor_below_threshold"] - p["grade"]) / pc["stair"]["risers"]
check(rise <= 7.75, f"porch stair riser {rise:.2f}\" exceeds 7 3/4\"")
check(pc["stair"]["tread"] >= 10, f"porch tread {pc['stair']['tread']}\" under 10\"")
check(pc["baluster_gap"] < 4, "baluster gap must pass the 4\" sphere")
check(pc["rail_height"] >= 36, "guard under 36\"")

# every combination of swap choices has its file, and the contract lists it
contract = json.loads((build.SITE / "controls.json").read_text())
fields = {f["id"]: f for s in contract["sections"] for f in s["fields"]}
swaps = {k: list(f["options"]) for k, f in fields.items() if f["kind"] == "swap"}
swaps.update({k: [str(v) for v in f["values"]] for k, f in fields.items() if f["kind"] == "steps"})

# slider steps stay inside what the code and the roofing allow
for v in fields["rail_height"]["values"]:
    check(v >= 36, f"guard height step {v}\" is under the 36\" minimum")
for v in fields["porch_pitch"]["values"]:
    check(v >= 0.5, f"roof pitch step {v} in 12 is under 1/2 in 12, too flat for metal roofing")
for slot, template in contract["slots"].items():
    keys = [k for k in swaps if "{" + k + "}" in template]
    for combo in itertools.product(*(swaps[k] for k in keys)):
        rel = template.format(**dict(zip(keys, combo)))
        check((build.SITE / rel).exists(), f"slot {slot}: {rel} missing (rebuild)")
        check(rel in contract["assets"], f"slot {slot}: {rel} not in controls.json assets")

# color fields only point at real palettes, and the defaults exist
for f in fields.values():
    if f["kind"] == "color" and "options" in f:
        check(f["default"] in [o[0] for o in f["options"]], f"{f['id']}: default {f['default']} not in its palette")

# a phone on a so-so connection: keep the first load small
first = contract["assets"]["model/house.glb"]["bytes"] + sum(
    contract["assets"][t.format(**{k: fields[k]["default"] for k in swaps})]["bytes"] for t in contract["slots"].values())
check(first < 6e6, f"first load is {first / 1e6:.1f} MB (budget 6 MB)")
total = sum(a["bytes"] for a in contract["assets"].values())

# drawings and takeoff (run model/drawings.py first): drawn = cut = bought
takeoff_path = build.SITE / "drawings/takeoff.json"
check(takeoff_path.exists(), "no drawings: run model/drawings.py")
if takeoff_path.exists():
    takeoff = json.loads(takeoff_path.read_text())
    for slug, t in takeoff.items():
        cut = {}
        for pc in t["pieces"]:
            cut.setdefault(pc["profile"], []).extend([round(pc["length"], 4)] * pc["qty"])
        for b in t["bought"]:
            got = sorted(round(x, 4) for board in b["boards"] for x in board)
            check(got == sorted(cut.get(b["profile"], [])), f"{slug}: {b['profile']} boards don't hold exactly the cut list")
            for board in b["boards"]:
                check(board, f"{slug}: a {b['profile']} board bought for nothing")
                used = sum(board) + 0.125 * (len(board) - 1)
                check(used <= b["stock_ft"] * 12, f"{slug}: {b['profile']} board over-cut ({used:.2f}\" from {b['stock_ft']}')")
        for prof in cut:
            if prof in ("2x2", "2x3", "2x4", "6x6", "PT 2x8"):
                check(any(b["profile"] == prof for b in t["bought"]), f"{slug}: {prof} is cut but never bought")
        page_html = (build.SITE / "drawings" / slug / "index.html").read_text()
        if "balusters_drawn" in t:
            on_plan = page_html.count('class="baluster"')
            check(t["balusters_drawn"] == t["balusters_cut"] == on_plan,
                  f"{slug}: balusters drawn {t['balusters_drawn']}, on the plan {on_plan}, cut {t['balusters_cut']}")
        if slug.startswith("door-"):
            m0, m1 = t["mo"][0], t["mo"][1]
            wall = p["wx1"] - p["wx0"]
            bearing = spec["rear_door_install"]["lintel_bearing"]
            check(m0 >= bearing + 4 and wall - m1 >= bearing + 4, f"{slug}: lintel needs {bearing}\" bearing plus 4\" of brick past it each side")
            for k in ("unit", "ro", "mo"):
                check(frac_in(t[k][1] - t[k][0]) in page_html, f"{slug}: the {k} width isn't on the drawings")

# the site was built from today's sources
from fingerprint import fingerprint  # noqa: E402
check(contract.get("source_sha256") == fingerprint(), "controls.json is from older sources: run model/build.py")

# drawings against the GLB, and the GLB against the coverage table
import numpy as np  # noqa: E402
import trimesh  # noqa: E402


def glb_meshes(rel):
    sc = trimesh.load(build.SITE / rel, force="scene")
    for node in sc.graph.nodes_geometry:
        T, name = sc.graph[node]
        yield name, sc.geometry[name].copy().apply_transform(T)


if takeoff_path.exists():
    IN = build.IN
    for slug, t in takeoff.items():
        mats = {name.split(".", 2)[-1] if name.startswith("door.operable.") else name for rel in t["glbs"] for name, _ in glb_meshes(rel)}
        for m in sorted(mats - set(t["coverage"])):
            check(False, f"{slug}: the model has {m} but drawings.yaml coverage doesn't say where it goes")
        if slug.startswith("door-"):
            # cut the rear wall's brick 3' up; the gap between the two pieces is the masonry opening
            brick = trimesh.util.concatenate([g for n, g in glb_meshes(t["glbs"][1]) if n == "cladding.brick"])
            segs = trimesh.intersections.mesh_plane(brick, [0, 1, 0], [0, 36 * IN, 0])
            face = segs[np.abs(segs[:, :, 2] + p["wy1"] * IN).max(1) < 0.01]          # on the wall's outside face
            runs = sorted((min(sg[:, 0]) / IN, max(sg[:, 0]) / IN) for sg in face)
            merged = []
            for a0, a1 in runs:   # merge touching pieces into runs of brick
                if merged and a0 <= merged[-1][1] + 0.01:
                    merged[-1][1] = max(merged[-1][1], a1)
                else:
                    merged.append([a0, a1])
            gaps = [round(b[0] - a[1], 3) for a, b in zip(merged, merged[1:])]   # holes between runs
            drawn = t["mo"][1] - t["mo"][0]
            check(len(gaps) == 1 and abs(gaps[0] - drawn) < 0.13, f"{slug}: masonry opening in the GLB is {gaps}\", drawings say {drawn}\"")
        if "balusters_cut" in t:
            # cut the guard 18" above the porch floor; every baluster is a 1 1/2" square there
            trim = trimesh.util.concatenate([g for n, g in glb_meshes(t["glbs"][0]) if n == "porch.trim"])
            segs = trimesh.intersections.mesh_plane(trim, [0, 1, 0], [0, (18 - spec["porch"]["floor_below_threshold"]) * IN, 0])
            # a cut splits each side at the triangle seams, so count by perimeter: at this height
            # only posts (4 x 5 1/2") and balusters (4 x 1 1/2") are cut
            perimeter = np.linalg.norm(segs[:, 0] - segs[:, 1], axis=1).sum() / IN
            posts = len(spec["porch"]["posts_x"]) * 4 * spec["porch"]["post"]
            in_glb = (perimeter - posts) / (4 * spec["porch"]["baluster"])
            in_glb = int(round(in_glb)) if abs(in_glb - round(in_glb)) < 0.01 else in_glb
            check(in_glb == t["balusters_cut"], f"{slug}: {in_glb} balusters in the GLB, {t['balusters_cut']} on the cut list")

if problems:
    print("\n".join("FAIL " + x for x in problems))
    sys.exit(1)
print(f"ok: {len(contract['assets'])} GLBs, first load {first / 1e6:.2f} MB, all {total / 1e6:.2f} MB")
