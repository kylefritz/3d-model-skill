"""The sha256 of everything the site is built from: model/*.yaml and the generators.
build.py writes it into controls.json; check.py and tools/verify_live.py compare it, so a
site built from older sources fails instead of quietly showing an old design."""

import hashlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def fingerprint() -> str:
    h = hashlib.sha256()
    for f in sorted([*ROOT.glob("model/*.yaml"), ROOT / "model/build.py", ROOT / "model/drawings.py"]):   # inputs, not checkers
        h.update(f.name.encode() + b"\0" + f.read_bytes())
    return h.hexdigest()
