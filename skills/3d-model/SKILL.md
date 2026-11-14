---
name: 3d-model
description: Build a measured, parametric 3D model of a house from phone LiDAR scans, tape measurements and spec sheets, and publish it as a static web viewer (GitHub Pages or Cloudflare). Use when someone wants to scan a house or room, turn a scan into a clean model, show design options (paint, siding, a new door, porch colors) in a browser, register a scan to a model, make construction drawings, a cut list or a buy list from the model, record an animated walkthrough, publish or fix the viewer (Walk mode, the phone joystick, the Comment button), or read and answer the notes people send from the viewer.
---

# 3d-model

The model is a clean, editable house built from measured numbers. It is not the scan.
Scans are lumpy and stop where the phone stopped. The scan is the evidence the numbers
answer to. The repo this skill ships in is a working example: a made-up rowhouse with
four claddings, eight paints, porch colors and sliders, three real sliding doors,
construction drawings for each, and two animated tours.

```
capture (LiDAR + tape) -> register -> model/house.yaml (numbers + sources)
  -> model/build.py -> site/ (house.glb, options/*.glb, controls.json)
  -> model/drawings.py -> site/drawings/ (sheets, cut list, buy list, PDFs)
  -> model/check.py -> publish (GitHub Pages or Cloudflare)
```

Read the doc for the step you're on: `docs/capture.md`, `docs/model.md`, `docs/viewer.md`,
`docs/parameters.md`, `docs/drawings.md`, `docs/publish.md`, `docs/comments.md`.

## 1. Capture

Ask which phone they have. LiDAR means an iPhone Pro (12 Pro or later) or an iPad Pro.
Recommend Scaniverse (free, on-device, exports GLB mesh and PLY points from one
capture). Give them `docs/capture.md`'s walking rules: short overlapping scans under 5
minutes, slow, about 5 m range, exteriors as a loop in both directions, glass and blinds
lie, tape one dimension per scan.

**Getting the scans off the phone.** Walk them through it one step at a time and wait for
them to confirm each step. Every scan goes out twice, mesh first and then points:

1. In Scaniverse, tap the scan to open it.
2. Tap **Share**.
3. Tap **Export Model**.
4. Pick **GLB** (color images). Send it to the laptop: **AirDrop** is easiest on a Mac;
   otherwise use Files / iCloud Drive or email.
5. Back on the same scan: **Share → Export Model → PLY** (point cloud). Send that too.
6. Repeat for each scan.

When the files land (AirDrop puts them in `~/Downloads`), rename both files of a pair to
the same date and place (`2026-09-11-rear-yard.glb` and `.ply`) and move them into
`captures/`. Check that every GLB has a PLY with the same name. A missing half means a
re-export, not a re-scan.

Without LiDAR: photos plus COLMAP or VGGT get shape but not trustworthy scale. Tape more.

## 2. Register

Fix one origin on a durable feature (outside face of a masonry wall at finished floor)
and never move it. `uv run tools/register_scan.py scan.ply site/model/house.glb --out out/<name>`
levels, aligns (FPFH + RANSAC, then point-to-plane ICP) and writes residuals plus a
deviation cloud. When the automatic coarse step fails, pick 3 matching points by eye
and pass `--seed`. Record the residual with the transform and don't claim better.
Run `make demo-scan` first if anyone doubts the tool.

Then make the scan-vs-model sheets (`uv run tools/scan_sheets.py <registered.ply>`): plan
cuts per floor and a long section, scan in black, model in red, 1' grid, with the
median distance printed. Read every sheet. A mismatch is a measurement to fix or furniture
to ignore, and the sheet can't tell which. Ship the registered points as the viewer's
scan layer (`site/scan/points.glb`) so anyone can ghost the model and check.

## 3. Model

Numbers go in `model/house.yaml` in feet and inches, each group with a `source`
(`tape`, `scan`, `drawing`, `spec`, `estimate`). Use actual lumber sizes, not nominal (a 6x6
is 5 1/2"), and measure old members rather than rounding them to modern sizes.
Geometry comes from generators in `model/build.py`, written in wall coordinates
(u along, z up, t out), so cladding, trim and windows work on any wall.

Products come from the maker's sheet: unit size, rough opening, jamb depth, colors,
and the URL go in YAML with `source: spec`. Mark anything the sheet doesn't publish as
an estimate. Maker colors have names, not hex values. Approximate the hex and say so.

Also set, before anyone looks at it:

- `existing:` in `options.yaml`: the house as measured. The viewer's Existing / Proposed
  switch shows it without losing the design.
- `site:` in `house.yaml`: `anchor` lat/long, `y_bearing` (compass bearing of +Y) and
  `lot_depth`. They drive the real sun, the compass and the lot lines. Take the bearing
  from a map and check it against a dated photo's shadows.
- `lights:` for dusk (porch ceiling, sconces, a lamp per room) and `section` views (a cut
  height in inches) for floor plans.

## 4. Parameters

Four kinds, cheapest first (details in `docs/parameters.md`):

- **color**: recolor every material with a given name (`paint.body`). Name materials for the
  paint, not the part.
- **swap**: build one GLB per value, chosen by a slot template
  (`options/rear-{door}-{cladding}.glb`). Something that depends on two choices is a
  cross product, so keep those parts small.
- **range**: move a named node (`door.operable`) by a distance the generator wrote from
  the spec.
- **steps**: a slider over a few values that change shape (porch depth, roof pitch,
  guard height). Build every stop as its own GLB. Don't stretch geometry in the browser:
  the drawings and cut list have to describe the porch on screen. Pick the stops from
  real limits (36" guard minimum, 1/2 in 12 for metal roofing) and check them.

**Tours** are keyframes (eye, target, time, optional `set`) in `options.yaml`. The viewer
plays them; `tools/record_tour.py` renders them frame by frame to MP4 and GIF. Check a
new path with `--every 1` and read the contact sheet before recording. Keep the target
on the subject when swinging around, because a camera passing over its own target flips.
Walk through the open half of a slider, not the meeting stiles.

Add the field to `model/options.yaml`, build the geometry, `make check`. The viewer
should rarely need a change.

## 5. Check and look

`make check` catches sources, door fit, code basics (riser 7 3/4" max, tread 10" min,
baluster gap under 4", guard 36"), missing option files, the phone weight budget, a stale
build (the `source_sha256` fingerprint), drawings that disagree with the GLBs, and model
materials missing from a drawing set's coverage table.
Then look: `make serve` and `make shots` (Playwright, desktop and phone). Read every
screenshot before showing anyone. Look for z-fighting stripes, black faces, clipped
views, and a panel covering the subject. Read them tiled, not one by one:
`make sheet OUT=out/sheet.jpg STILLS="street-dusk inside rear-none"` makes one labelled
sheet under 1568 px. After three rounds on one surface, call it an estimate instead of
tuning the measurement.

## 6. Drawings, cut list, buy list

Follow `docs/drawings.md`. The rule is **one set of numbers**: drawings call the same
layout functions the 3D generator does (`build.rear_opening`, `build.rail_runs`,
`build.baluster_layout`), never a copy. Add new ones to `build.py` and use them in
both places.

1. Write the brief first in `model/drawings.yaml`: title, what was asked, confidence,
   open items. The sheet prints all three.
2. Draw with the `Svg` kit in `model/drawings.py`: `dim()` for dimensions, `note()` for
   callouts, classes (`brick`, `pt`, `steel`, `eng`) instead of colors. One set per
   option that changes the drawing, and link it from the viewer section with a
   `drawings:` template.
3. Pieces go on the cut list from the same layout; `buy()` packs them with kerf.
   `make check` proves drawn = cut = bought and no board is bought for nothing.
4. `make check-drawings` must pass: no overlapping or crossed labels, nothing off the
   sheet, crossing leaders, or labels under 9 px on a phone. The first run on a new
   sheet usually fails. Move the label; don't shrink it.
5. Screenshot every sheet and read it. A passing check doesn't make a sheet clear.
6. Anything structural gets "by engineer" and an open item. The sheets say "not for
   construction".
7. Fill the set's `coverage:` table: every material in its GLBs is either `buy` or says
   whose it is. A buy list with silent gaps looks complete, and that's worse than having none.
8. Where it can, `check.py` cuts the GLB and compares it with the drawing (the hole in the
   brick against the masonry opening, baluster sections against the cut list). Add a cut
   check like that for each new kind of sheet.

## 7. Publish: ask which

Ask: **"GitHub Pages or Cloudflare?"** Then follow `docs/publish.md`.

- **GitHub Pages** (default for open source and demos). The included workflow builds,
  checks and deploys on push to `main`. Enable it with
  `gh api -X POST repos/OWNER/REPO/pages -f build_type=workflow`.
- **Cloudflare Workers static assets** (for a real house with its own domain).
  `npx wrangler@4 deploy` with `wrangler.jsonc`, plus a `custom_domain` route if the zone
  is on Cloudflare. Tokens stay in the environment, never in git.

Publishing is outward-facing. Confirm before the first deploy, and strip private notes
(addresses, correspondence, security details) from anything that goes into a GLB.

Serve it compressed (`docs/publish.md`, "Compression"). A GLB is mostly floats that
repeat, so it shrinks 5-20x, but only if something compresses it. Check with
`curl -sI -H 'Accept-Encoding: gzip, br' <url>/model/house.glb` and look for
`content-encoding`. GitHub Pages gzips GLBs. Cloudflare doesn't by default, since
`model/gltf-binary` isn't on its list. For a big real model, run `gltf-transform meshopt`
on the export too. Never `gltf-transform optimize`: its dedup and join steps merge
materials and nodes, and the viewer finds them by name.

On Cloudflare the viewer also takes comments (section 8): create the D1 database first
(`npx wrangler@4 d1 create 3d-model-comments`, id into `wrangler.jsonc`) or delete the
`d1_databases` block to go without. GitHub Pages has no server, so no comments; the button
hides itself there.

After a deploy, prove it: `uv run tools/verify_live.py <url>` compares every file with
the live site, byte for byte, plus the fingerprint. The Pages workflow's `verify` job does
it against the exact artifact it deployed. "CI is green" isn't proof the site is right.

## 8. Comments from the viewer

On Cloudflare the viewer has a **✎ Comment** button: people tap things (numbered pins that
keep the 3D point and the piece's `kp_id`/`kp_label` extras or node name), draw with a pen,
write a note and send it. `worker/index.js` stores it in D1 with a JPEG of the view (pins
and ink drawn in), the camera and a deep link. Details in `docs/comments.md`.

**Pick them up** (needs only this machine's wrangler login; `--local` for `make dev`'s copy):

```
make comments                                     # open notes (ALL=1 for every note)
uv run tools/comments.py show ID                  # the note; picture -> out/comments/ID.jpg
uv run tools/comments.py reply ID "text" [--status done|wontfix|open]
```

- The SessionStart hook in `.claude/settings.json` runs `tools/comments.py --hook`, so a
  session opens with the open notes in context. It's silent when there are none, offline,
  or before the database exists.
- **Look at the picture before acting.** Pen marks exist only there. A note with no pins or
  ink gives only the camera: recreate the view at the picture's aspect (the `cam` eye and
  target) and raycast to find what's in the middle of it.
- Act on it like any change (the YAML, `make check`, a PR, a deploy), then reply saying what
  changed and where. **Replies are public** on the site: keep them about the model, with no
  addresses or private detail.
- The POST endpoint is public (honeypot, size caps, no login). If spam shows up, suggest
  Turnstile on Send or Cloudflare Access on `/api/*`.
- The Worker takes notes only for names in its `MODELS` set; `make check` keeps that equal to
  `name:` in `options.yaml`. Rename both together.
- Viewer rules learned the hard way: the pen's canvas sits *below* the panels (z-index), or it
  eats the click on Send; keep the user's tool after a send (back in Point, a drag orbits
  instead of drawing the next circle); pin `compatibility_date` to one `wrangler dev`'s
  bundled workerd supports.

## Measure the model

Size is something to show, not to cut. Never decimate, simplify or split a model to make
it smaller: serve it compressed instead (float geometry brotlis about 4x) and let people
see what it weighs. `make build` writes `site/stats.json` (bytes raw, gzip and brotli,
triangles, vertices, draw calls, materials, textures, scan points per GLB) and the viewer's
"Model details" shows it for what's on screen. `make stats` prints it. Say the size when
you publish.

Log every modelling session: `make tokens SESSION=<id prefix> TITLE="..."` appends its
tokens, lead and workers apart, to `model/worklog.yml`, and the viewer's work log prices it
as an API list-price equivalent. Details in `docs/publish.md`, "Size, stats and the work log".

## Keep it cheap: a thin lead and a worker per part

A modelling session's cost is turns times context, not this file. One lead that read a
250 KB site file and full-size stills carried them on every later turn, and re-read about
300M cached tokens over ~640 turns. A redesign of the same scale run the way below used
about 40% of the tokens and of the cost.

- **Split before designing.** When `build.py` (or one site file) passes about 60 KB, split it
  into one module and one numbers file per part (a room, a facade, the yard) before any
  design work, and prove the split is a no-op: the build writes byte-identical GLBs (`cmp`, or
  the `sha256` in `controls.json` assets).
- **The lead stays thin.** It reads the request and the outline (`rg -n "^def "`), writes
  one shared brief (frame, levels, layers, the loop, what counts as a stand-in) and a
  paragraph of design direction per part, and reads one contact sheet per part per round.
  It never reads a big file whole or a full-size still.
- **One worker per part, on a cheaper model** (`model: sonnet` on the Agent call), each
  owning its module and numbers file. Workers draft small (half-size, low-sample stills;
  for the viewer, a small Playwright viewport), tile them into one sheet, pipe build output
  through `tail`, and hand back about 250 words, the sheet's path, and "still weak". The
  lead sends one polish round to the same worker (SendMessage), so its context is reused.
- **Shared checkout rules**, in the brief:
  - Keep your module importable at all times. Write a big rewrite to `<module>_next.py`,
    compile it (`python -m py_compile`), then swap it in one step; a half-written module
    breaks every sibling's build.
  - Prefix new material names with your part (`kitchen.counter`), so recolors and the
    drawings' coverage table don't collide.
  - Interiors must be lit: a dark tile is a bug, not a mood. The commonest worker failure is a
    correct room rendered nearly black. Check a dusk still too, and make it show something the
    day still doesn't (lit windows, lamps).
  - Shared files (views, materials, `options.yaml`) get small targeted edits; the lead does
    the full build, `make check` and the drawings at the end.
- **Cap machine load** when the machine is shared: one render at a time behind a lock (for
  example `flock /tmp/render.lock <cmd>`), at low priority (`nice -n 10`). Two renders at once
  are rarely faster than one after the other.
- **Watch the size each round.** Detail multiplies: ask every worker for the face count of
  each repeated part (a tree, a chair, a baluster) and how many it placed, and look at
  `make stats` before the next round. Big is fine; big by accident isn't.
- **Stand-ins read as cheap**: ball shrubs, a flat green board for a hedge, glowing signs,
  string lights everywhere. Use what a built project has: real materials, planters of
  leaning blades, signs lit from above, light in the structure. Workers list the stand-ins
  they left under "still weak"; read that list before you accept a sheet.

After each session, log it (`make tokens`), so the next one can see what this cost.

## Viewer controls

`site/app.js`. Lessons that cost time to learn:

- **Orbit** with `rotateSpeed` 0.45 and `dampingFactor` 0.1, so a swipe doesn't spin the
  house. Double-tap flies to the spot at half the distance (clamped 3 to 12 m) over 0.6 s.
- **Walk starts where you are.** Keep the camera and its look, and level only the roll.
  Leaving Walk orbits a point 3 m ahead.
- **Look** is a YXZ Euler, pitch clamped to ±1.5. Track `clientX/Y` yourself, because iOS
  leaves `movementX` at 0 for touches. Look follows only the pointer that started it.
- **Stay level:** flatten the facing vector, and divide by `max(1, hypot(x, y))` so
  diagonals aren't faster.
- **Joystick** only on `(pointer: coarse)`: a 128 px disc and 48 px rim, analogue, with pointer capture.
- **Hold to speed up:** 1.5 m/s for 1.2 s, then a smoothstep to 3x over 2.5 s.
- **Double-tap** is your own detector (iOS sends no `dblclick`): 350 ms, 30 px, one finger.
  Skip glass. In Walk, a floor stands you on it at 1.6 m and a wall stops you 0.6 m short.
- **Touch hygiene:** `touch-action: none` while walking. Clear keys on `blur`.
- Portrait phones need a wider vertical FOV (72 vs 50). On a desktop, `setViewOffset`
  centers the picture beside the panel.
- Test in a browser, not by reading code. Headless renders under 20 fps, so test that speed
  rises over a hold rather than the absolute speed.

## Gotchas

- GLTFLoader strips dots from `object.name` (`door.operable` becomes `dooroperable`). Match
  nodes on `userData.name`, which keeps the original. Material names keep their dots.
- trimesh boxes share vertices. `unmerge_vertices()` before export, or faces shade smooth.
- trimesh writes no normals unless you ask. Without them three skips shadows with no
  warning. Export with `include_normals=True` and set flat vertex normals yourself
  (`np.repeat(face_normals, 3, axis=0)` on unmerged faces).
- Open3D's tensor mesh keeps one material. Build the raycast mesh from bare geometry.
- One RANSAC run on a house is a coin flip. Try several and keep the best ICP fitness.
- Coplanar faces z-fight, and here it showed as plaster-white stripes in the brick three
  times (party walls, the wing corner). Raycast the pixel to find the two faces
  (`window.viewer` is exposed for that), then give each wall its own volume.
- Headless WebGL can run at 5 fps, and the viewer caps each frame's step, so a 0.6 s
  flight takes seconds. Tests wait on state (`viewer.moving()`, `viewer.walkPace()`),
  never on fixed sleeps.
- A stair with n risers has n - 1 treads. The last step lands on the walk.
- Brick and other textures on a box-built model: project world position per face
  (no UVs needed), and set anisotropy or it shimmers at grazing angles.

Record what you learn here when it would have saved time.
