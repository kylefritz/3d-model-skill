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

if problems:
    print("\n".join("FAIL " + x for x in problems))
    sys.exit(1)
print(f"ok: {len(contract['assets'])} GLBs, first load {first / 1e6:.2f} MB, all {total / 1e6:.2f} MB")
