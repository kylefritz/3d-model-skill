# Model: from numbers to a house

The model is a clean, editable house built from measured numbers. It isn't the scan:
scans are lumpy and stop where the phone stopped. The scan is the evidence the
numbers answer to.

```
scans + tape + drawings -> model/house.yaml (numbers + sources)
  -> model/build.py -> site/model/house.glb + site/options/*.glb + site/controls.json
  -> model/check.py -> the viewer
```

## Write numbers the way you measured them

`model/house.yaml` is in feet and inches, like a tape sketch: `9' 6"`, `5 1/2"`, `-2'`.
`build.py` converts to inches once on read and to meters once on export. Convert at
those two boundaries and nowhere else, and never rescale anything by eye.

Every group says where its numbers came from:

```yaml
wing:
  source: scan             # read off the LiDAR scan, good to about 1"
  width: 11'
```

Sources are `tape`, `scan`, `drawing`, `spec` (a manufacturer's sheet) or `estimate`.
`check.py` fails a group without one. Estimates are fine. The problem is an estimate
nobody labeled.

## Actual sizes, not nominal

A 6x6 post is 5 1/2". A 2x12 is 1 1/2" x 11 1/4". An LVL is 1 3/4" wide. Brick is 7 5/8" x
2 1/4" with a 3/8" joint, 3 courses to 8" ([BIA Tech Note 10](https://gobrick.com/media/file/10-dimensioning-and-estimating-brick-masonry.pdf)).
Old houses are worse: a 100-year-old joist is whatever it measures, often 2 1/2" x 6 1/2"
of old-growth that no modern size matches. Tape it, write it down, and never "round"
an old member to a 2x size. Where old and new meet (a sister on an old joist), model both.

## Generators, not hand-modeling

`build.py` is a small kit: `box`, a `Wall` with openings in its own (u, z, t)
coordinates, and generators that write onto a wall. Cladding, trim and windows are
written once in wall coordinates and work on any wall:

```python
def clad_lap(part, wall, spec):
    board, exposure, thick = 8.25, 7.0, 5 / 16        # HardiePlank 8 1/4" at 7" exposure
    z = wall.z0 + 1
    while z < wall.z1 - 0.5:
        for a, b in wall.free(5.5, wall.length - 5.5, z, z + exposure):   # skip the windows
            part.add("paint.body", wall.solid(a, b, z, z + exposure, 0, thick * 2, taper=thick))
        z += exposure
```

Real specs where there are real specs: lap siding exposure from
[James Hardie's table](https://pages.jameshardie.com/rs/966-NNK-991/images/RS23624_HS2412_National_Product_Catalog_1024.pdf),
2 1/2" battens from the [HardieTrim spec](https://www.buildsite.com/pdf/jameshardie/HardiePanel-Vertical-Siding-Guide-Specifications-2197443.pdf),
shingle exposure inside the [Cedar Bureau's](https://www.cedarbureau.org/wp-content/uploads/2020/05/page-16-Sidewall-Application-Guidelines.pdf)
limits, the door from each maker's sheet (`model/doors.yaml`).

Material names are the hooks for parameters: `paint.body`, `paint.trim`, `porch.floor`.
Name them for the paint they wear, not the object (see [parameters.md](parameters.md)).

The real project this came from uses Blender as the editable master, with Python
generators writing into the `.blend` and an exporter writing GLBs. The idea is the
same. Plain Python + [trimesh](https://trimesh.org) is here because it runs in CI with no
installs, and it's enough for a house made of boxes.

## Where on Earth

`site:` in `house.yaml` places the model: an `anchor` latitude/longitude for the origin, a
`y_bearing` (the compass bearing of +Y, front wall toward the yard) and a `lot_depth`. The
viewer uses them for the compass, the real sun and the lot lines. The example's anchor is
NYC City Hall, deliberately not a real house. For your own, take the bearing from a map
(the angle of the party wall) and check it against a shadow photo with a known time.

## Existing and proposed

`existing:` in `options.yaml` is the house as measured: the old window instead of the
slider, the porch as built. Everything else is proposed. Model the existing condition
first, and date it.

## Close the loop

Don't trust a render, and don't trust yourself reading one. Every link has a check:

| Link | Check | Fails when |
| --- | --- | --- |
| Numbers to sources | `make check` | A group has no source |
| Spec sheet to model | `make check` | A door doesn't fit its rough opening, or the opening doesn't fit the wall |
| Code basics | `make check` | A riser over 7 3/4", a tread under 10", a baluster gap of 4" or more, a guard under 36" |
| Options to files | `make check` | Some combination of choices has no GLB |
| Phone budget | `make check` | First load over 6 MB |
| Scan to model | `make demo-scan` / `tools/register_scan.py` | Residuals over what you said the scan is good for |
| Model to eye | `make shots` | Nothing fails. Look at them |

The loop: change the YAML, `make check`, refresh, look. Don't apply a scan reading
blind, because it might be a cabinet or a set of blinds. After three rounds on one surface, stop
and call it an estimate. Tuning a measured wall until it agrees is the failure to avoid.

## The bar

1. **True.** Every dimension has a source and the checks pass.
2. **Oriented.** One origin, fixed, written down.
3. **Opening by opening.** Every window and door has a frame, sash, sill and head, in place.
4. **Materials from photos.** No default gray. Painted stays painted.
5. **Estimates look like estimates.** Labeled in the YAML.
6. **Viewer.** Loads on a phone, every control works with a thumb, and the URL reopens the same look.

Keep level of detail and accuracy apart: a beautifully detailed window can still be 3" off.
