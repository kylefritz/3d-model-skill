# /// script
# requires-python = ">=3.11,<3.13"
# dependencies = ["open3d>=0.19", "numpy>=1.26"]
# ///
"""Register a phone scan to the model and report how far apart they are.

    uv run tools/register_scan.py --demo                      # no phone needed
    uv run tools/register_scan.py scan.ply site/model/house.glb --out out/rear

Steps, each one a place real scans go wrong:
  1. Level the scan on its biggest floor-like plane. Phones drift in tilt more
     than in anything else, and a tilted scan fools every step after it.
  2. Coarse align with FPFH features + RANSAC (or pass --seed with a transform you
     got by picking matching points by eye; for hard scans that's faster).
  3. Refine with point-to-plane ICP.
  4. Measure: distance from every scan point to the model surface. Read the
     numbers, then look at deviation.ply: red is what the model doesn't explain.

Writes <out>.json (4x4 transform, residuals) and <out>-deviation.ply.
"""

import argparse
import json
from pathlib import Path

import numpy as np
import open3d as o3d

VOXEL = 0.05  # meters; phone LiDAR is good to about 1-3 cm up close, so 5 cm is plenty for alignment


def load_model(path):
    mesh = o3d.io.read_triangle_mesh(str(path))
    mesh.compute_vertex_normals()
    return mesh


def sample(mesh, n=200_000):
    pcd = mesh.sample_points_uniformly(n)
    pcd.estimate_normals(o3d.geometry.KDTreeSearchParamHybrid(radius=VOXEL * 2, max_nn=30))
    return pcd


def level(pcd, up=np.array([0, 1, 0.0])):
    """Rotate so the largest near-horizontal plane faces straight up."""
    rest, best = pcd, None
    for _ in range(4):
        plane, idx = rest.segment_plane(distance_threshold=0.02, ransac_n=3, num_iterations=1000)
        n = np.array(plane[:3]) / np.linalg.norm(plane[:3])
        if abs(n @ up) > 0.9:
            best = n if n @ up > 0 else -n
            break
        rest = rest.select_by_index(idx, invert=True)
    if best is None:
        return np.eye(4), None
    axis = np.cross(best, up)
    angle = np.arccos(np.clip(best @ up, -1, 1))
    R = o3d.geometry.get_rotation_matrix_from_axis_angle(axis / (np.linalg.norm(axis) or 1) * angle)
    T = np.eye(4)
    T[:3, :3] = R
    return T, np.degrees(angle)


def features(pcd, voxel):
    down = pcd.voxel_down_sample(voxel)
    down.estimate_normals(o3d.geometry.KDTreeSearchParamHybrid(radius=voxel * 2, max_nn=30))
    fpfh = o3d.pipelines.registration.compute_fpfh_feature(down, o3d.geometry.KDTreeSearchParamHybrid(radius=voxel * 5, max_nn=100))
    return down, fpfh


def coarse(scan, model, tries=6):
    """FPFH + RANSAC, a few times, keeping whichever start ICP likes best. One RANSAC
    run on a house is a coin flip: walls, floors and fences all look alike locally."""
    s, sf = features(scan, VOXEL * 2)
    m, mf = features(model, VOXEL * 2)
    reg = o3d.pipelines.registration
    best, best_fit = np.eye(4), -1
    for i in range(tries):
        o3d.utility.random.seed(i)
        r = reg.registration_ransac_based_on_feature_matching(
            s, m, sf, mf, True, VOXEL * 3, reg.TransformationEstimationPointToPoint(False), 3,
            [reg.CorrespondenceCheckerBasedOnEdgeLength(0.9), reg.CorrespondenceCheckerBasedOnDistance(VOXEL * 3)],
            reg.RANSACConvergenceCriteria(1_000_000, 0.999))
        fit = reg.registration_icp(s, m, VOXEL * 2, r.transformation, reg.TransformationEstimationPointToPlane()).fitness
        if fit > best_fit:
            best, best_fit = r.transformation, fit
    return best


def refine(scan, model, init):
    reg = o3d.pipelines.registration
    T = init
    for dist in (0.2, 0.08, 0.03):  # shrink the leash as it settles
        T = reg.registration_icp(scan, model, dist, T, reg.TransformationEstimationPointToPlane()).transformation
    return T


def residuals(scan, mesh):
    rs = o3d.t.geometry.RaycastingScene()
    bare = o3d.geometry.TriangleMesh(mesh.vertices, mesh.triangles)  # geometry only: materials confuse the tensor mesh
    rs.add_triangles(o3d.t.geometry.TriangleMesh.from_legacy(bare))
    d = rs.compute_distance(o3d.core.Tensor(np.asarray(scan.points), dtype=o3d.core.Dtype.Float32)).numpy()
    return d


def deviation_cloud(scan, d, out):
    # 0 cm green, 5 cm yellow, 10 cm+ red
    k = np.clip(d / 0.10, 0, 1)[:, None]
    colors = np.hstack([np.clip(2 * k, 0, 1), np.clip(2 - 2 * k, 0, 1), np.zeros_like(k)])
    pcd = o3d.geometry.PointCloud(scan.points)
    pcd.colors = o3d.utility.Vector3dVector(colors)
    o3d.io.write_point_cloud(str(out), pcd)


def fake_scan(mesh, rng):
    """What a phone would hand you: part of the house, noisy, in its own frame."""
    pcd = mesh.sample_points_uniformly(150_000)
    pts = np.asarray(pcd.points)
    keep = pts[:, 2] < -9.0            # only the rear: the yard, the wing, the slider
    pts = pts[keep] + rng.normal(0, 0.01, (keep.sum(), 3))   # ~1 cm noise
    R = o3d.geometry.get_rotation_matrix_from_xyz((np.radians(3), np.radians(25), np.radians(-2)))  # tilt + heading
    truth = np.eye(4)
    truth[:3, :3] = R
    truth[:3, 3] = [1.2, -0.3, 2.0]
    scan = o3d.geometry.PointCloud(o3d.utility.Vector3dVector(pts))
    scan.transform(truth)
    return scan, np.linalg.inv(truth)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("scan", nargs="?")
    ap.add_argument("model", nargs="?", default="site/model/house.glb")
    ap.add_argument("--seed", help="JSON file with a 4x4 'transform' to start from instead of RANSAC")
    ap.add_argument("--out", default="out/scan")
    ap.add_argument("--demo", action="store_true", help="make a fake scan from the model and register it")
    a = ap.parse_args()

    mesh = load_model(a.model)
    model = sample(mesh)
    truth = None
    if a.demo:
        scan, truth = fake_scan(mesh, np.random.default_rng(7))
    else:
        scan = o3d.io.read_point_cloud(a.scan)  # .ply points; for a .glb mesh, sample it first
    scan.estimate_normals(o3d.geometry.KDTreeSearchParamHybrid(radius=VOXEL * 2, max_nn=30))

    L, tilt = level(scan)
    scan.transform(L)
    if a.seed:
        init = np.array(json.loads(Path(a.seed).read_text())["transform"])
    else:
        init = coarse(scan, model)
    T = refine(scan, model, init)
    scan.transform(T)
    full = T @ L

    d = residuals(scan, mesh)
    report = {
        "transform": full.round(6).tolist(),
        "leveled_by_degrees": None if tilt is None else round(float(tilt), 2),
        "points": int(len(d)),
        "median_cm": round(float(np.median(d)) * 100, 2),
        "p90_cm": round(float(np.percentile(d, 90)) * 100, 2),
        "within_3cm": round(float((d < 0.03).mean()), 3),
    }
    if truth is not None:
        err = np.linalg.inv(truth) @ full
        report["demo_translation_error_cm"] = round(float(np.linalg.norm(err[:3, 3])) * 100, 2)
        report["demo_rotation_error_deg"] = round(float(np.degrees(np.arccos(np.clip((np.trace(err[:3, :3]) - 1) / 2, -1, 1)))), 3)
    out = Path(a.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.with_suffix(".json").write_text(json.dumps(report, indent=1) + "\n")
    deviation_cloud(scan, d, out.with_name(out.name + "-deviation.ply"))
    print(json.dumps(report, indent=1))


if __name__ == "__main__":
    main()
