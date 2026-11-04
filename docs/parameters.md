# Parameters: one contract, three tricks

The useful part of a house model is "what would it look like if". Change the siding,
paint it, put in a different door. You want that in a browser, on a phone, instantly,
without Blender.

The trick is a **contract**. `model/options.yaml` lists the parameters. `build.py`
builds the geometry for them *and* writes `site/controls.json`. The viewer only reads the
contract. It knows nothing about houses, so a new parameter rarely touches `app.js`.

There are three kinds of parameter, from cheapest to most expensive:

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
