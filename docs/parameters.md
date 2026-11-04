# Parameters: one contract, four tricks

The useful part of a house model is "what would it look like if". Change the siding,
paint it, put in a different door. You want that in a browser, on a phone, instantly,
without Blender.

The trick is a **contract**. `model/options.yaml` lists the parameters. `build.py`
builds the geometry for them *and* writes `site/controls.json`. The viewer only reads the
contract. It knows nothing about houses, so a new parameter rarely touches `app.js`.

There are four kinds of parameter, from cheapest to most expensive:

## 1. Color: recolor a material by name

```yaml
- id: body
  kind: color
  label: Body
  default: sw6244
  palette: [sw7005, sw6204, sw7036, sw6187, sw6244, sw2802, sw7069, sw6258]
  materials: [paint.body]
```

Every mesh that wears body paint uses a material named `paint.body`. Lap siding,
battens, shingles and painted brick all do. The viewer sets that material's color. No
new geometry, no download.

Name materials for the paint, not the part. `porch.trim` covers posts, rails, balusters,
the beam and the fascia, because in real life they're one can of paint.

Paint chips are real [Sherwin-Williams](https://www.sherwin-williams.com/sherwinwilliams/SW6244-naval)
colors at their published hex values. A screen still isn't a paint chip.

Rules between parameters stay small and live in the contract. Natural brick ignores the
body paint unless "Paint the brick" is on:

```yaml
brick_color: {paint_toggle: paint_brick, paint_field: body}
```

## 2. Swap: pre-build every shape, pick one in the browser

Anything that changes shape is built once per value at build time:

```yaml
slots:
  cladding: "options/cladding-{cladding}.glb"
  rear: "options/rear-{door}-{cladding}.glb"
  door: "options/door-{door}.glb"
```

A slot's file name is a template over the settings. The viewer reloads a slot only when
its resolved name changes, and caches every file it has loaded, so switching back is
free.

The `rear` slot is the interesting one. The rear wing's back wall needs a different hole
for each door (doors aren't the same size), and a different skin for each cladding. So
it's built as the **cross product**: 4 doors x 4 claddings = 16 small files. That's fine.
A product of three 5-way choices is 125 files, so keep the walls that depend on two
choices small, and put everything else in single-choice slots.

`check.py` walks every combination and fails if a file is missing.

## 3. Range: move a named node

```yaml
- id: door_open
  kind: range
  label: Open
  min: 0
  max: 100
  node: door.operable
```

The door generator puts the operable panel in its own node, `door.operable`, and writes
how far that panel travels *for that product* into the contract:

```json
"travel_by": {"door": {"none": 0.0, "andersen200": 0.8255, "marvin": 0.8318, "pella": 0.835}}
```

The viewer moves the node. How far it goes comes from the spec sheet, through the
generator, not from a number someone typed into JavaScript.

## 4. Steps: a slider over shapes

Porch depth, roof pitch and guard height change real geometry: posts move, balusters get
longer, the roof tilts. You could stretch things in the browser, but then the drawings
and the cut list would describe a different porch than the one on screen. So a `steps`
slider has a few stops, and each stop is built ahead of time, like a swap:

```yaml
- id: rail_height
  kind: steps
  label: Guard height
  values: [36, 38, 40, 42]
  unit: '"'
  note: 36" is the residential minimum (IRC R312); 42" is the commercial one.
```

```yaml
slots:
  porch: "options/porch-{porch_pitch}-{rail_height}-{porch_depth}.glb"   # 4 x 4 x 3 = 48 small files
```

A section can name its drawings the same way, and the viewer links to the set for exactly
what's on screen:

```yaml
- name: Front porch
  drawings: "drawings/porch-{rail_height}-{porch_depth}/"
```

Pick the stops from real limits, and `check.py` holds you to them: guards at 36" or more,
roof pitch at 1/2 in 12 or more for metal. Pitch doesn't change the railing drawings, so
the drawing sets are only guard height x depth (12), not all 48.

## Tours

A tour is keyframes in the same model inches as the viewpoints: an eye, a target and a
time. Keys can also set parameters, so a tour can show options changing: a range eases
between keys (the door slides open as you walk up), anything else switches at its key.

```yaml
tours:
  - name: Front to back
    keys:
      - {at: 0, eye: [150, -560, 70], target: [96, 0, 110], set: {door_open: 0}}
      - {at: 23, eye: [143, 720, 64], target: [143, 552, 50], set: {door_open: 0}}
      - {at: 25.5, eye: [143, 620, 64], target: [143, 500, 58], set: {door_open: 100}}
```

The viewer plays it with Catmull-Rom through the keys (Tour button). The picture
depends only on t, so `tools/record_tour.py` stops the render loop, poses each frame and
captures it: smooth video however slow the machine. Check a new path with `--every 1`
and read the contact sheet. Keep the target on the subject when the camera swings
around: a camera that passes over its own target flips.

Two lessons from the example:

- Walk through the open half of a slider, not the middle: the meeting stiles are there.
- Fly around the side, not over the roof. Over the top, the camera passes its own target
  and spins.

## Options that depend on options

Each door maker has its own color list. The frame color field takes its options from
the selected door:

```yaml
- id: door_color
  kind: color
  options_by: door
```

When you switch doors, the viewer keeps your color if the new door offers it and falls
back to that door's first color if not. Every value stays legal.

## Shareable links

Every non-default setting goes in the query string (`?cladding=lap&body=sw6204&view=street`).
The Share button copies it, and opening it restores the same look. The README screenshots
are made from those same links (`tools/screenshots.py`), so any image can be reproduced
from its query string.

## Adding a parameter

1. Add the field to `model/options.yaml`.
2. Color: name the material in the generator. Swap: build one GLB per value and add a
   slot. Range: put the moving part in a named node and write its travel to the contract.
3. `make check`, then look.
