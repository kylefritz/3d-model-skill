# /// script
# requires-python = ">=3.11"
# dependencies = ["pyyaml>=6"]
# ///
"""Log a Claude Code session that worked on the model, with its tokens, in model/worklog.yml.

    uv run tools/session_tokens.py --session <id-prefix> --title "what it did" [--from ISO] [--to ISO] [--dry-run]
    uv run tools/session_tokens.py --show                      # the log so far, priced

Claude Code keeps each session as ~/.claude/projects/<project dir>/<session id>.jsonl, and its
subagents' transcripts under <session id>/. This finds the session by id prefix in any project
dir (or only in --project-dir), counts the lead's tokens and the workers' separately, by model,
and appends an entry to the worklog (or replaces the one with the same session and --from, so a
re-run is safe). --from/--to keep only the turns in a window, for a session that also did other
work. Run it after each modelling session, then rebuild so the viewer's work log picks it up.

Counting: only `type == "assistant"` lines with message.usage, once per message id (a streamed
message is written on several lines, the last wins); `<synthetic>` turns are skipped.

Cost is an API list-price equivalent from PRICES below. The work may run on a subscription, so
it is not a bill, and the table goes stale: check it against the published prices and update
PRICES_AS_OF when you change it. A model not in the table shows its tokens and no cost.
"""
import argparse
import collections
import datetime as dt
import glob
import json
import os
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
WORKLOG = ROOT / "model" / "worklog.yml"
PROJECTS = Path(os.path.expanduser("~/.claude/projects"))
FIELDS = (("input", "input_tokens"), ("cache_write", "cache_creation_input_tokens"),
          ("cache_read", "cache_read_input_tokens"), ("output", "output_tokens"))

# Dollars per million tokens. Goes stale: re-check before trusting a total.
PRICES_AS_OF = "2026-11-03"
PRICES = {
    "claude-fable-5-2": {"input": 8.00, "output": 40.00, "cache_read": 0.20},
    "claude-opus-5-5": {"input": 4.00, "output": 20.00, "cache_read": 0.20},
    "claude-sonnet-5-5": {"input": 2.00, "output": 10.00, "cache_read": 0.10},
    "claude-haiku-5-5": {"input": 0.10, "output": 0.50, "cache_read": 0.01},
}
CACHE_WRITE_FACTOR = 1.25  # a 5-minute cache write costs 1.25x input

HEADER = """\
# Claude Code sessions that worked on this model, and their tokens: what could be attributed,
# not necessarily all of it. Written by tools/session_tokens.py; the build prices it into
# site/stats.json for the viewer's work log. Re-running an entry replaces it.
"""


def parse_ts(value):
    return dt.datetime.fromisoformat(value.replace("Z", "+00:00")) if value else None


def tally(path, start=None, end=None):
    """{model: {turns, input, cache_write, cache_read, output}} plus the first and last turn's time."""
    seen = {}
    with open(path, errors="replace") as f:
        for line in f:
            if '"assistant"' not in line:
                continue
            try:
                d = json.loads(line)
            except ValueError:
                continue
            msg = d.get("message") or {}
            usage = msg.get("usage")
            if d.get("type") != "assistant" or not usage or msg.get("model") == "<synthetic>":
                continue
            at = parse_ts(d.get("timestamp"))
            if (start and at and at < start) or (end and at and at > end):
                continue
            seen[msg.get("id") or d.get("uuid")] = (msg.get("model", "unknown"), usage, at)
    by_model = collections.defaultdict(lambda: dict(turns=0, **{k: 0 for k, _ in FIELDS}))
    for model, usage, _ in seen.values():
        row = by_model[model]
        row["turns"] += 1
        for key, source in FIELDS:
            row[key] += usage.get(source) or 0
    times = [at for _, _, at in seen.values() if at]
    return dict(by_model), (min(times) if times else None), (max(times) if times else None)


def merge(into, more):
    for model, row in more.items():
        target = into.setdefault(model, dict(turns=0, **{k: 0 for k, _ in FIELDS}))
        for key, value in row.items():
            target[key] += value


def find_session(prefix, project_dir=None):
    dirs = [Path(project_dir)] if project_dir else sorted(p for p in PROJECTS.iterdir() if p.is_dir())
    hits = [p for d in dirs for p in d.glob(f"{prefix}*.jsonl")]
    if len(hits) != 1:
        sys.exit(f"session {prefix}: " + ("not found" if not hits else "ambiguous, give more of the id: "
                                          + ", ".join(h.stem for h in hits)))
    return hits[0]


def workers_of(lead):
    return sorted(Path(p) for p in glob.glob(str(lead.with_suffix("") / "**" / "*.jsonl"), recursive=True))


def cost(model, row):
    """List-price equivalent in dollars of one model's row, or None for a model not in PRICES."""
    price = PRICES.get(model)
    if not price:
        return None
    return (row.get("input", 0) * price["input"] + row.get("cache_write", 0) * price["input"] * CACHE_WRITE_FACTOR
            + row.get("cache_read", 0) * price["cache_read"] + row.get("output", 0) * price["output"]) / 1e6


def load(path=WORKLOG):
    path = Path(path)
    if not path.exists():
        return []
    return (yaml.safe_load(path.read_text()) or {}).get("entries") or []


def save(path, entries):
    entries.sort(key=lambda e: (str(e.get("date")), e["session"], str(e.get("from") or "")))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(HEADER + yaml.safe_dump({"entries": entries}, sort_keys=False, allow_unicode=True, width=110))


def priced(path=WORKLOG):
    """The worklog as the viewer wants it: one row per session with its tokens, turns and cost by role,
    plus totals. None when there is no worklog."""
    entries = load(path)
    if not entries:
        return None
    sessions, total = [], {"turns": 0, "tokens": 0, "cost": 0.0, "unpriced": False}
    for e in entries:
        roles = {}
        for role, models in (e.get("usage") or {}).items():
            for model, row in models.items():
                r = roles.setdefault(role, {"models": [], "turns": 0, "tokens": 0, "cost": 0.0, "unpriced": False})
                r["models"].append(model)
                r["turns"] += row.get("turns", 0)
                r["tokens"] += sum(row.get(k, 0) for k, _ in FIELDS)
                c = cost(model, row)
                r["unpriced"] |= c is None
                r["cost"] += c or 0.0
        s = {k: e.get(k) for k in ("date", "session", "title", "attribution") if e.get(k)}
        s["roles"] = roles
        for key in ("turns", "tokens", "cost"):
            s[key] = sum(r[key] for r in roles.values())
            total[key] += s[key]
        s["unpriced"] = any(r["unpriced"] for r in roles.values())
        total["unpriced"] |= s["unpriced"]
        s["cost"] = round(s["cost"], 2)
        sessions.append(s)
    total["cost"] = round(total["cost"], 2)
    return {"prices_as_of": PRICES_AS_OF, "sessions": sessions, "total": total}


def fmt(usage):
    lines = []
    for role in ("lead", "workers"):
        for model, row in (usage.get(role) or {}).items():
            c = cost(model, row)
            lines.append(f"  {role:<7} {model:<20} {row['turns']:>5} turns  cache read {row['cache_read'] / 1e6:7.1f}M  "
                         f"cache write {row['cache_write'] / 1e6:6.2f}M  out {row['output'] / 1e6:5.2f}M  "
                         + (f"~${c:,.2f}" if c is not None else "unpriced"))
    return "\n".join(lines)


def log_session(args, worklog):
    lead_path = find_session(args.session, args.project_dir)
    start, end = parse_ts(args.start), parse_ts(args.end)
    lead, t0, t1 = tally(lead_path, start, end)
    workers, times = {}, [t for t in (t0, t1) if t]
    for path in workers_of(lead_path):
        rows, w0, w1 = tally(path, start, end)
        merge(workers, rows)
        times += [t for t in (w0, w1) if t]
    if not times:
        sys.exit(f"no assistant turns in {lead_path.name} for that window")
    entry = {"date": min(times).astimezone(dt.timezone.utc).date().isoformat(), "session": lead_path.stem[:8],
             "title": args.title}
    if args.start:
        entry["from"] = args.start
    if args.end:
        entry["to"] = args.end
    entry["attribution"] = args.attribution or (
        f"the session's turns from {args.start or 'its start'} to {args.end or 'its end'}"
        if (args.start or args.end) else "the whole session: lead and every worker")
    entry["usage"] = {k: v for k, v in (("lead", lead), ("workers", workers)) if v}
    print(f"{entry['session']} {entry['date']} {entry['title']}\n{fmt(entry['usage'])}")
    key = (entry["session"], entry.get("from"))
    entries = load(worklog)
    kept = [e for e in entries if (e["session"], e.get("from")) != key]
    if args.dry_run:
        print("dry run; drop --dry-run to write", worklog)
        return
    save(worklog, kept + [entry])
    print(("replaced in " if len(kept) != len(entries) else "added to ") + str(worklog))


def show(worklog):
    log = priced(worklog)
    if not log:
        print("no worklog at", worklog)
        return
    for s in log["sessions"]:
        print(f"{s['date']} {s['session']} {s['turns']:>5} turns {s['tokens'] / 1e6:8.1f}M tokens "
              f"${s['cost']:>8,.2f}{'+' if s['unpriced'] else ''}  {s['title']}")
    t = log["total"]
    print(f"total {t['turns']} turns, {t['tokens'] / 1e6:.1f}M tokens, ${t['cost']:,.2f} list-price equivalent "
          f"(prices as of {log['prices_as_of']})")


def main(argv):
    ap = argparse.ArgumentParser(description="Log a model's Claude Code sessions and their tokens.")
    ap.add_argument("--session", help="session id or a unique prefix of it")
    ap.add_argument("--title", help="what the session did, in a few words")
    ap.add_argument("--from", dest="start", help="ISO time: count only turns from here")
    ap.add_argument("--to", dest="end", help="ISO time: count only turns up to here")
    ap.add_argument("--attribution", help="say how the turns were attributed, if not the whole session")
    ap.add_argument("--project-dir", help="look only in this ~/.claude/projects/<dir>")
    ap.add_argument("--worklog", type=Path, default=WORKLOG)
    ap.add_argument("--show", action="store_true", help="print the log so far, priced")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args(argv)
    if args.show:
        return show(args.worklog)
    if not args.session or not args.title:
        ap.error("--session and --title are needed (or --show)")
    return log_session(args, args.worklog)


if __name__ == "__main__":
    main(sys.argv[1:])
