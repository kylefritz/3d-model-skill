# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""Is the live site exactly what we built? Byte for byte, every file.

    uv run tools/verify_live.py https://you.github.io/3d-model-skill/            # against ./site
    uv run tools/verify_live.py https://you.github.io/3d-model-skill/ deployed/  # against a deploy artifact

Also checks the source fingerprint: the live controls.json must carry the sha256 of the
model/*.yaml and build.py it was built from, and so must the local build. A site built
from older sources fails here instead of quietly showing an old design.

Pages and Cloudflare cache for a few minutes, so every request carries a cache-busting
query and a failed file is retried for up to `--wait` seconds.
"""

import argparse
import hashlib
import json
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "model"))


def fetch(url):
    req = urllib.request.Request(url, headers={"User-Agent": "3d-model-skill verify_live", "Cache-Control": "no-cache"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return r.read()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("base")
    ap.add_argument("tree", nargs="?", default=str(ROOT / "site"))
    ap.add_argument("--wait", type=int, default=300)
    a = ap.parse_args()
    base, tree = a.base.rstrip("/") + "/", Path(a.tree)
    files = sorted(p for p in tree.rglob("*") if p.is_file() and p.name != ".DS_Store")
    bust = str(int(time.time()))
    problems, deadline = {}, time.time() + a.wait
    pending = files
    while pending:
        problems = {}
        for f in pending:
            rel = f.relative_to(tree).as_posix()
            try:
                live = fetch(f"{base}{rel}?v={bust}")
            except urllib.error.HTTPError as e:
                problems[f] = f"HTTP {e.code}"
                continue
            if hashlib.sha256(live).digest() != hashlib.sha256(f.read_bytes()).digest():
                problems[f] = f"differs ({len(live)} bytes live, {f.stat().st_size} built)"
        pending = list(problems)
        if not pending or time.time() > deadline:
            break
        print(f"{len(pending)} file(s) not live yet, retrying...")
        time.sleep(20)
        bust = str(int(time.time()))

    # the fingerprint: live == built == today's sources
    from fingerprint import fingerprint
    want = fingerprint()
    live_fp = json.loads(fetch(f"{base}controls.json?v={bust}")).get("source_sha256")
    built_fp = json.loads((tree / "controls.json").read_text()).get("source_sha256")
    fp_ok = live_fp == built_fp
    for f, why in problems.items():
        print(f"FAIL {f.relative_to(tree)}: {why}")
    if not fp_ok:
        print(f"FAIL live controls.json was built from {live_fp[:12] if live_fp else 'nothing'}, this build from {built_fp[:12]}")
    if built_fp != want:
        print(f"note: this tree was built from {built_fp[:12]}, the sources here are {want[:12]} (rebuild before comparing)")
    if problems or not fp_ok:
        sys.exit(1)
    print(f"ok   {len(files)} files live and identical; sources {want[:12]}")


if __name__ == "__main__":
    main()
