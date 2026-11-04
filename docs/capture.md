# Capture: scanning a house with a phone

You need an iPhone or iPad Pro with LiDAR (iPhone 12 Pro and later Pros), a free scanning
app, a tape measure and an afternoon. The scans are evidence, not the model: they tell
you where the walls are to about an inch, and they stop wherever the phone couldn't see.

## The app

I use **[Scaniverse](https://apps.apple.com/us/app/scaniverse-lidar-3d-scanner/id1541433223)**.
It's free, it processes on the phone, and one capture exports both a textured mesh (GLB)
and points (PLY). It also makes Gaussian splats (SPZ or PLY), which look great and measure badly.

| App | Exports | Good for |
| --- | --- | --- |
| [Scaniverse](https://www.nianticspatial.com/products/capture) | GLB, USDZ, FBX meshes; PLY, SPZ splats | Free. The default here |
| [Polycam](https://poly.cam/pricing) | glTF free; OBJ, PLY, LAS, DXF, floor plans on paid plans | Floor plans and documentation exports |
| [3d Scanner App](https://apps.apple.com/us/app/-/id1419913995) | GLB, OBJ, USDZ; PLY, LAS, PTS, XYZ points; DXF | The rawest point clouds |
| [Matterport](https://apps.apple.com/us/app/matterport-3d-capture/id701086043) | E57, OBJ, XYZ (paid) | Walkthrough tours; schematic floor plans |
| [RoomPlan](https://developer.apple.com/augmented-reality/roomplan) apps | USDZ with walls, doors, furniture as boxes | A quick parametric room, not a measured one |

Niantic describes Scaniverse output as "metric-scale". Trust it after you've checked it:
tape one long dimension in every scan (a wall, a door width) and compare.

## How to walk a scan

Sources: [Scaniverse's techniques page](https://www.nianticspatial.com/docs/scaniverse/techniques),
[Apple's RoomPlan session](https://developer.apple.com/videos/play/wwdc2022/10127/),
[Polycam on buildings](https://poly.cam/blog/how-to-scan-a-building-interior-exterior-and-multi-story-workflows)
and [on glass and mirrors](https://poly.cam/blog/how-to-handle-reflective-glass-and-mirrors-in-3d-scans).

1. **Short scans with overlap.** A scan per room or per facade, under 5 minutes each.
   "A shorter scan with strong coverage is more reliable than a longer scan with gaps."
   Start each one on something the last scan saw (a doorway, a window), so they can be
   tied together.
2. **Slow.** Moving too fast is the most common cause of a warped scan. Keep moving,
   even if very slowly; slow down further on stairs and in dark corners.
3. **Mind the range.** iPhone LiDAR reaches about 5 m. A second-floor cornice from the
   sidewalk is out of range: it comes from photos and the camera, not the laser, and is
   worth less.
4. **Exteriors as a loop.** Walk the perimeter pointing in, then walk it back the other
   way. Overcast light beats sun for facades.
5. **Glass, mirrors, blinds, dark paint.** Glass reads whatever is behind it, and a
   mirror makes a room twice as deep. Scan glass at an angle from several spots. Blinds
   and curtains return points that look like a wall. Open them, or know they're there.
   Very dark surfaces return little.
6. **Tape one thing per scan.** Write it on the sketch with where you measured it.
   That one number is how you'll know whether the scan's scale is right.

## Export both files

Export the **GLB** (photo-textured mesh) *and* the **PLY** (points) from the same scan.
They're the same capture in the same coordinates, so one registration fits both.

- Read the **texture** to tell what a thing is: brick or siding, old joist or new
  pressure-treated lumber, wall or the blinds in front of it.
- Read the **points** for where it is.

Name files for what they saw and when (`2026-09-11-rear-yard.glb`), and keep the originals.
If they live in git, use [Git LFS](https://git-lfs.com) and a `SHA256SUMS` file so a
changed scan is obvious.

## Register scans to one frame

Pick an origin that won't move: the outside face of a masonry wall at finished floor is
good. Write it down. Never move it later, because every scan, drawing and number hangs off it.

`tools/register_scan.py` does what you'd do by hand in [CloudCompare](https://github.com/CloudCompare/CloudCompare):

1. **Level** each scan on its biggest floor plane. Phones drift in tilt more than anything.
2. **Coarse align.** FPFH features + RANSAC, tried a few times and judged by ICP fitness.
   When that fails (it will, on scans that are mostly flat walls), pick 3 matching points
   by eye and pass the transform with `--seed`.
3. **Refine** with [point-to-plane ICP](https://www.open3d.org/docs/release/tutorial/pipelines/icp_registration.html).
4. **Measure** the distance from every scan point to the model, and write a colored
   `-deviation.ply`: green fits, red is something the model doesn't explain yet.

Try it without a phone. The demo cuts a noisy partial "scan" out of the example house,
throws it 2 m off and 25 degrees around, and finds it again:

```
$ make demo-scan
 "leveled_by_degrees": 2.8,
 "median_cm": 0.64,
 "p90_cm": 1.59,
 "within_3cm": 0.998,
 "demo_translation_error_cm": 0.26,
 "demo_rotation_error_deg": 0.015
```

Lessons from real scans:

- **Rules break; seeds don't.** Finding features by rule ("the biggest vertical plane is
  the back wall") fails when the neighbor's wall is coplanar with yours or blinds
  return a fake wall. When that happens, pick the features by eye on a rendered sheet,
  save them as seeds, and let the script measure from the seeds.
- **Register on features, not on the cloud's center.** A window center and a transom
  head are better datums than the middle of a lumpy point cloud.
- **Chain what can't see the datum.** A street-side scan that never sees the rear wall
  gets tied in through an interior scan that sees both.
- **Write down the residual** next to the transform. "Rear good to about 1", street end
  about 3" in Z" is a real result. Don't claim better.

## What's new (late 2026)

None of these replace a tape measure. They're worth knowing about:

- **Gaussian splatting** ([paper](https://arxiv.org/abs/2308.04079),
  [project](https://repo-sam.inria.fr/fungraph/3d-gaussian-splatting/)) makes
  photoreal captures. Edit them in [SuperSplat](https://superspl.at/editor) and show them
  in three.js with [Spark](https://sparkjs.dev/). A splat next to the clean model works
  well as an "existing" view. Train your own with
  [gsplat](https://github.com/nerfstudio-project/gsplat) / [Nerfstudio](https://nerf.studio/).
- **Photos to geometry without LiDAR:** [COLMAP](https://colmap.github.io/) (now includes
  GLOMAP's global mapper), and the feed-forward models
  [DUSt3R](https://github.com/naver/dust3r), [MASt3R](https://github.com/naver/mast3r) and
  [VGGT](https://vgg-t.github.io/) (CVPR 2025 best paper), plus
  [π³](https://arxiv.org/abs/2507.13347). Good for a facade that's out of LiDAR range.
- **Photogrammetry apps:** [Apple Object Capture](https://developer.apple.com/documentation/realitykit/realitykit-object-capture),
  [RealityScan](https://www.realityscan.com/).
- **Scan to floor plan:** [RoomFormer](https://arxiv.org/abs/2211.15658),
  [SpatialLM](https://manycore-research.github.io/SpatialLM/) (an LLM that writes a
  structured layout from a point cloud), [CAGE](https://arxiv.org/abs/2509.15459).
