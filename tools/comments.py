# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""Read and answer the notes people send from the viewer's Comment button.

Notes live in the D1 database `3d-model-comments` (worker/index.js writes them). This reads it
with `wrangler d1 execute --remote`, so it needs a wrangler login on this machine and nothing
else: no token in the repo.

    uv run tools/comments.py                 # open notes, one line each (make comments)
    uv run tools/comments.py --all           # every note
    uv run tools/comments.py show ID         # one note in full; its picture -> out/comments/ID.jpg
    uv run tools/comments.py reply ID "text" [--status done|wontfix|open]
    uv run tools/comments.py --hook          # SessionStart hook: say nothing unless notes are open
    uv run tools/comments.py --local ...     # against `make dev`'s local database

A reply shows under the note in the viewer's "Earlier notes", for anyone who opens the site.
Pins are viewer metres (glTF, Y up: the model frame's (x, y, z) is the viewer's (x, z, -y)); `id` is the piece's
kp_id extra if the model has one, else the node's name (here, the material: paint.trim).
"""

import argparse
import base64
import json
import re
import shutil
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CONFIG = ROOT / "wrangler.jsonc"
OUT = ROOT / "out" / "comments"
DB = "3d-model-comments"
FIELDS = "id, created, model, author, body, link, show, cam, pins, strokes, status, reply, replied"


def q(s: str) -> str:
    """A SQL string literal (the command goes to wrangler as one argv entry, no shell)."""
    return "'" + s.replace("'", "''") + "'"


def configured() -> bool:
    """False while wrangler.jsonc still has the placeholder database id (or no database)."""
    text = CONFIG.read_text() if CONFIG.exists() else ""
    m = re.search(r'"database_id"\s*:\s*"([^"]*)"', text)
    return bool(m) and not m.group(1).startswith("<")


def sql(command: str, where: str, timeout: int = 60) -> list[dict]:
    wrangler = [shutil.which("wrangler")] if shutil.which("wrangler") else ["npx", "--yes", "wrangler@4"]
    run = subprocess.run(
        [*wrangler, "d1", "execute", DB, where, "--json", "--config", str(CONFIG), "--command", command],
        capture_output=True,
        text=True,
        timeout=timeout,
        cwd=ROOT,
    )
    if run.returncode:
        raise SystemExit(f"wrangler d1 failed:\n{run.stderr.strip() or run.stdout.strip()}")
    return json.loads(run.stdout)[0]["results"]


def line(c: dict) -> str:
    pins = json.loads(c["pins"])
    bits = [f"{c['id']}  {c['created'][:16].replace('T', ' ')}Z  {c['model']}  {c['show']}  [{c['status']}]"]
    bits.append(f"  {c['author'] or 'someone'}: {c['body'] or '(no text)'}")
    if pins:
        bits.append("  pins: " + "; ".join(f"{p['n']} {p['label'] or p['id'] or 'a spot'}" for p in pins))
    if c["strokes"]:
        bits.append(f"  pen: {c['strokes']} stroke(s), see the picture")
    if c["reply"]:
        bits.append(f"  reply: {c['reply']}")
    return "\n".join(bits)


def show(cid: str, where: str) -> None:
    rows = sql(f"SELECT {FIELDS}, image FROM comments WHERE id = {q(cid)}", where)
    if not rows:
        raise SystemExit(f"no note {cid}")
    c = rows[0]
    print(line(c))
    print(f"  view: {c['link']}")
    print(f"  cam (eye x,y,z, target x,y,z; viewer metres): {c['cam']}")
    for p in json.loads(c["pins"]):
        print(f"  pin {p['n']}: ({p['x']}, {p['y']}, {p['z']}) m  id={p['id']}  {p['label'] or ''}")
    if c["image"]:
        OUT.mkdir(parents=True, exist_ok=True)
        path = OUT / f"{cid}.jpg"
        path.write_bytes(base64.b64decode(c["image"].split(",", 1)[1]))
        print(f"  picture: {path.relative_to(ROOT)}  (read it: the pen marks are only in the picture)")


def reply(cid: str, text: str, state: str, where: str) -> None:
    now = datetime.now(UTC).isoformat(timespec="seconds")
    sql(f"UPDATE comments SET reply = {q(text)}, status = {q(state)}, replied = {q(now)} WHERE id = {q(cid)}", where)
    print(f"{cid}: {state}, replied")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("action", nargs="?", choices=["list", "show", "reply"], default="list")
    ap.add_argument("id", nargs="?")
    ap.add_argument("text", nargs="?")
    ap.add_argument("--status", choices=["done", "wontfix", "open"], default="done")
    ap.add_argument("--all", action="store_true", help="every note, not only open ones")
    ap.add_argument("--hook", action="store_true", help="quiet unless notes are open; never fails")
    ap.add_argument("--local", action="store_true", help="the local database `make dev` uses")
    a = ap.parse_args()
    where = "--local" if a.local else "--remote"
    if a.hook and not a.local and not configured():
        return  # comments aren't set up in this copy: no network, no noise
    if a.action == "show":
        return show(a.id or ap.error("show needs an ID"), where)
    if a.action == "reply":
        if not (a.id and a.text):
            ap.error("reply needs an ID and the text")
        return reply(a.id, a.text, a.status, where)
    filt = "" if a.all else "WHERE status = 'open'"
    try:
        rows = sql(f"SELECT {FIELDS} FROM comments {filt} ORDER BY created", where, timeout=20 if a.hook else 60)
    except (SystemExit, subprocess.TimeoutExpired, OSError, ValueError) as e:
        if a.hook:
            return  # offline or logged out: a session start shouldn't fail over it
        raise SystemExit(str(e)) from None
    if a.hook:
        if rows:
            print(f"The viewer has {len(rows)} open comment(s). Read each with `uv run tools/comments.py show ID`")
            print("and look at its picture, act on it, then answer with")
            print('`uv run tools/comments.py reply ID "what changed"`. Mention them to the user.\n')
            print("\n".join(line(c) for c in rows))
        return
    print("\n".join(line(c) for c in rows) or ("no notes" if a.all else "no open notes"))


if __name__ == "__main__":
    sys.exit(main())
