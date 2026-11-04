# /// script
# requires-python = ">=3.11"
# dependencies = ["trimesh>=4.4", "numpy>=1.26", "pyyaml>=6"]
# ///
"""Construction drawings, cut list and buy list, from the same numbers as the 3D model.

    uv run model/drawings.py

Writes site/drawings/<set>/index.html (SVG sheets you can read on a phone) and
site/drawings/takeoff.json (what check.py tests). tools/check_drawings.py checks
that every label is readable and prints each set to a letter-size PDF.

Nothing here has its own dimensions: openings, rail runs and baluster spacing come
from build.py's shared layouts, door sizes from doors.yaml, titles and open items
from drawings.yaml. If the model changes, the drawings change with it.
"""

from __future__ import annotations

import html
import json
import math
import sys
from fractions import Fraction
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import build  # noqa: E402

OUT = build.SITE / "drawings"
KERF = 0.125
LABEL_PX, MIN_LABEL_PX = 12, 9.5   # label size in drawing px; tools/check_drawings.py wants >= 9 on a phone
CHAR_PX = 6.6                      # rough width of a 12px character, for placing leaders


# ---------------------------------------------------------------- formatting

def frac(x: float) -> str:
    """5.25 -> 5 1/4", 71.25 -> 5'-11 1/4", to the nearest 1/16"."""
    neg = x < 0
    x = abs(round(x * 16) / 16)
    ft, rest = divmod(x, 12) if x >= 24 else (0, x)
    whole = int(rest)
    f = Fraction(rest - whole).limit_denominator(16)
    inch = (f"{whole} {f}" if whole and f else f"{f}" if f else f"{whole}") + '"'
    s = f"{int(ft)}'-{inch}" if ft else inch
    return "-" + s if neg else s


# ---------------------------------------------------------------- SVG kit (after Tunnel of Terror's coffin drawings)

class Svg:
    def __init__(self, k: float, x0: float, y0: float, w: float, h: float):
        """k px per inch; (x0, y0) is the drawing-space point at the top-left; y is up in drawing space."""
        self.k, self.x0, self.y0, self.w, self.h, self.parts = k, x0, y0, w, h, []

    def p(self, x, y):
        return ((x - self.x0) * self.k, (self.y0 - y) * self.k)

    def poly(self, pts, cls="line", close=True):
        d = " ".join("%.1f,%.1f" % self.p(*q) for q in pts)
        self.parts.append(f'<{"polygon" if close else "polyline"} class="{cls}" points="{d}"/>')

    def rect(self, x0, y0, x1, y1, cls="line"):
        self.poly([(x0, y0), (x1, y0), (x1, y1), (x0, y1)], cls)

    def line(self, a, b, cls="line"):
        (x1, y1), (x2, y2) = self.p(*a), self.p(*b)
        self.parts.append(f'<line class="{cls}" x1="{x1:.1f}" y1="{y1:.1f}" x2="{x2:.1f}" y2="{y2:.1f}"/>')

    def text(self, at, s, cls="n", anchor="middle", rot=None):
        x, y = self.p(*at)
        r = f' transform="rotate({rot} {x:.1f} {y:.1f})"' if rot is not None else ""
        self.parts.append(f'<text class="{cls}" x="{x:.1f}" y="{y:.1f}" text-anchor="{anchor}" dominant-baseline="central"{r}>{html.escape(s)}</text>')

    def dot(self, at):
        x, y = self.p(*at)
        self.parts.append(f'<circle class="dot" cx="{x:.1f}" cy="{y:.1f}" r="2.2"/>')

    def dim(self, a, b, label, off=0.0, side=1):
        """Dimension line a-b, offset `off` inches to one side, with extension lines and ticks.
        The label sits just off the line on the far side, rotated with it."""
        (ax, ay), (bx, by) = a, b
        L = math.hypot(bx - ax, by - ay) or 1
        ux, uy = (bx - ax) / L, (by - ay) / L
        nx, ny = -uy * side, ux * side
        a2, b2 = (ax + nx * off, ay + ny * off), (bx + nx * off, by + ny * off)
        if off:
            self.line(a, (a2[0] + nx * 0.8 * math.copysign(1, off), a2[1] + ny * 0.8 * math.copysign(1, off)), "ext")
            self.line(b, (b2[0] + nx * 0.8 * math.copysign(1, off), b2[1] + ny * 0.8 * math.copysign(1, off)), "ext")
        self.line(a2, b2, "dim")
        t = 4 / self.k
        for q in (a2, b2):  # architectural ticks
            self.line((q[0] - (ux + nx) * t, q[1] - (uy + ny) * t), (q[0] + (ux + nx) * t, q[1] + (uy + ny) * t), "dim")
        s = math.copysign(1, off) if off else 1
        clear = (LABEL_PX / 2 + 3) / self.k
        mid = ((a2[0] + b2[0]) / 2 + nx * clear * s, (a2[1] + b2[1]) / 2 + ny * clear * s)
        ang = -math.degrees(math.atan2(by - ay, bx - ax))
        if ang > 90 or ang <= -90:
            ang += 180
        self.text(mid, label, "d", rot=ang if abs(ang) > 0.1 else None)

    def note(self, at, target, s, anchor="start"):
        """A callout at `at` (one line per \\n) with a leader from the block's near side to `target`,
        so a leader never runs through its own words."""
        lines = s.split("\n")
        w = max(len(t) for t in lines) * CHAR_PX / self.k
        x0 = at[0] - (w if anchor == "end" else w / 2 if anchor == "middle" else 0)
        line_h = 14 / self.k
        mid_y = at[1] - (len(lines) - 1) * line_h / 2
        gap = 4 / self.k
        if target[0] > x0 + w:
            start = (x0 + w + gap, mid_y)
        elif target[0] < x0:
            start = (x0 - gap, mid_y)
        else:
            below = target[1] < at[1]
            start = (min(max(target[0], x0), x0 + w),
                     at[1] - (len(lines) - 1) * line_h - LABEL_PX / 2 / self.k - gap if below else at[1] + LABEL_PX / 2 / self.k + gap)
        self.line(start, target, "lead")
        self.dot(target)
        for i, t in enumerate(lines):
            self.text((at[0], at[1] - i * line_h), t, "n", anchor)

    def svg(self, label: str) -> str:
        # Never shrink below the width where 12px labels render at MIN_LABEL_PX; a phone scrolls the drawing instead.
        mw = self.w * self.k * MIN_LABEL_PX / LABEL_PX
        return (f'<div class="scroll"><svg style="min-width:{mw:.0f}px" viewBox="0 0 {self.w * self.k:.0f} {self.h * self.k:.0f}" '
                f'role="img" aria-label="{html.escape(label)}" xmlns="http://www.w3.org/2000/svg">{DEFS}{"".join(self.parts)}</svg></div>')


DEFS = ('<defs>'
        '<pattern id="brick" width="10" height="10" patternUnits="userSpaceOnUse" patternTransform="rotate(45)"><rect width="10" height="10" fill="#f6eee9"/><line x1="0" y1="0" x2="0" y2="10" stroke="#c9a493" stroke-width="1.2"/></pattern>'
        '<pattern id="masonry" width="10" height="10" patternUnits="userSpaceOnUse" patternTransform="rotate(-45)"><rect width="10" height="10" fill="#f1f1ef"/><line x1="0" y1="0" x2="0" y2="10" stroke="#c4c4bf" stroke-width="1"/></pattern>'
        '<pattern id="pt" width="6" height="6" patternUnits="userSpaceOnUse"><rect width="6" height="6" fill="#e5efdf"/><circle cx="3" cy="3" r=".9" fill="#93ad84"/></pattern>'
        '</defs>')


# ---------------------------------------------------------------- the takeoff: pieces, packing, buying

STOCK = {  # profile -> lengths the yard sells, in feet
    "PT 2x8": [8, 10, 12, 16],
    "2x2": [8],
    "2x3": [8, 10, 12],
    "2x4": [8, 10, 12, 16],
    "6x6": [10, 12],
}


def pack(lengths, stock_in, kerf=KERF):
    """First-fit decreasing: longest piece first, into the first board it fits, kerf between cuts."""
    boards = []
    for ln in sorted(lengths, reverse=True):
        for b in boards:
            if sum(b) + kerf * len(b) + ln <= stock_in:
                b.append(ln)
                break
        else:
            boards.append([ln])
    return boards


def buy(pieces):
    """For each profile, pick the stock length that wastes least, and say what to cut from each board."""
    out = []
    by_profile = {}
    for pc in pieces:
        if pc["profile"] in STOCK:
            by_profile.setdefault(pc["profile"], []).extend([pc["length"]] * pc["qty"])
    for prof, lengths in by_profile.items():
        best = None
        for ft in STOCK[prof]:
            if max(lengths) > ft * 12:
                continue
            boards = pack(lengths, ft * 12)
            score = (len(boards) * ft, len(boards))
            if best is None or score < best[0]:
                best = (score, ft, boards)
        if best is None:
            raise SystemExit(f"{prof}: a {max(lengths)}\" piece is longer than any stock")
        _, ft, boards = best
        out.append({"profile": prof, "stock_ft": ft, "count": len(boards), "boards": boards})
    return out


def door_pieces(o, door):
    (m0, m1, _, mh), (r0, r1, _, rh) = o["mo"], o["ro"]
    return [
        {"part": "buck jamb", "profile": "PT 2x8", "length": rh, "qty": 2, "note": "fastened to the masonry, sealant behind"},
        {"part": "buck head", "profile": "PT 2x8", "length": m1 - m0, "qty": 1, "note": "runs over the jambs"},
        {"part": "steel angle lintel", "profile": "steel", "length": (m1 - m0) + 2 * o["bearing"], "qty": 1, "note": "engineer to size; cut by the supplier"},
        {"part": f"{door['maker']} door unit", "profile": "unit", "length": door["unit"]["width"], "qty": 1, "note": door["model"]},
    ]


def porch_pieces(spec, p):
    pc = spec["porch"]
    (cw, ct), (bw, bt), bg = build.RAIL["cap"], build.RAIL["bottom"], build.RAIL["bottom_gap"]
    bal_len = pc["rail_height"] - ct - bg - bt
    pieces, n_total = [], 0
    for i, (a, b) in enumerate(build.rail_runs(spec, p), 1):
        L = abs(b[0] - a[0]) + abs(b[1] - a[1])
        n, _, _ = build.baluster_layout(L, pc)
        n_total += n
        pieces += [
            {"part": f"run {i} cap", "profile": "2x4", "length": L, "qty": 1, "note": "laid flat"},
            {"part": f"run {i} bottom rail", "profile": "2x3", "length": L, "qty": 1, "note": f"{frac(bg)} off the floor"},
            {"part": f"run {i} balusters", "profile": "2x2", "length": bal_len, "qty": n, "note": ""},
        ]
    posts = len(pc["posts_x"])
    pieces.append({"part": "posts", "profile": "6x6", "length": pc["ceiling"], "qty": posts, "note": "floor to beam"})
    return pieces, n_total


# ---------------------------------------------------------------- door sheets
# Seen from the yard, the wall's u runs right to left, so draw x = wall length - u.

def door_elevation(spec, p, door, o):
    L = o["wall"]
    (m0, m1, _, mh), (r0, r1, _, rh), (u0, u1, _, uh) = o["mo"], o["ro"], o["unit"]
    X = lambda u: L - u
    grade, top = p["grade"], mh + 30
    g = Svg(4.6, -34, top + 26, L + 92, top - grade + 72)
    g.rect(0, grade, L, top, "wall")
    g.line((-6, grade), (L + 6, grade), "ground")
    g.line((0, top), (L, top), "break")
    g.text((L / 2, top + 4), "wall continues up to the second floor", "n")
    g.rect(X(m1), 0, X(m0), mh, "open")                                    # masonry opening
    for a, b in ((m0, r0), (r1, m1)):
        g.rect(X(b), 0, X(a), rh, "pt")                                    # buck jambs
    g.rect(X(m1), rh, X(m0), mh, "pt")                                     # buck head
    g.rect(X(u1), 0, X(u0), uh, "unit")
    mid = (u0 + u1) / 2
    g.line((X(mid), 24), (X(mid), uh - 1), "line")   # meeting stiles; stops above the width dims
    g.rect(X(m1) - o["bearing"], mh, X(m0) + o["bearing"], mh + 3.5, "steel")
    # landing in front, below the threshold
    g.rect(X(L - 18), grade, X(18), -1.5, "concrete")
    # operable panel: the left one from outside (XO)
    y_arrow = uh * 0.55
    g.line((X(u1) + 8, y_arrow), (X(mid) - 4, y_arrow), "arrow")
    g.text((X(u1) + 14, y_arrow + 5), "X", "big")
    g.text((X(mid) + 14, y_arrow + 5), "O", "big")
    # widths: a chain along the bottom (masonry | opening | masonry), the wall under it;
    # unit and rough opening low inside the opening, clear of the meeting stile
    g.dim((0, grade), (X(m1), grade), frac(L - m1), -8, 1)
    g.dim((X(m1), grade), (X(m0), grade), f"M.O. {frac(m1 - m0)}", -8, 1)
    g.dim((X(m0), grade), (L, grade), frac(m0), -8, 1)
    g.dim((0, grade), (L, grade), f"wall {frac(L)}", -17, 1)
    g.dim((X(u1), 9), (X(u0), 9), f"unit {frac(u1 - u0)}", 0)
    g.dim((X(r1), 17), (X(r0), 17), f"R.O. {frac(r1 - r0)}", 0)
    g.dim((X(m1) - o["bearing"], mh + 3.5), (X(m1), mh + 3.5), frac(o["bearing"]), 3.5, 1)
    g.dim((X(m0), mh + 3.5), (X(m0) + o["bearing"], mh + 3.5), frac(o["bearing"]), 3.5, 1)
    right = X(m0) + o["bearing"] + 10
    g.dim((right, 0), (right, uh), f"unit {frac(uh)}", 0)
    g.dim((right + 9, 0), (right + 9, rh), f"R.O. {frac(rh)}", 0)
    g.dim((right + 18, 0), (right + 18, mh), f"M.O. {frac(mh)}", 0)
    g.line((X(m0), 0), (right + 20, 0), "ext")
    g.line((X(m0), mh), (right + 20, mh), "ext")
    g.note((-30, top - 4), (X(m1) - o["bearing"] / 2, mh + 1.75), "steel angle lintel\nengineer to size", "start")
    g.note((-30, mh * 0.55), (X(m1) + 0.75, rh * 0.6), "PT 2x8 buck,\njambs + head", "start")
    g.note((-30, -8), (X(L - 30), -6), "landing", "start")
    g.text((X(mid), -14.5), "first floor / threshold at 0\"", "n")
    return g.svg("Exterior elevation of the rear door opening")


def door_plan(spec, p, door, o):
    """Horizontal cut at 3', through the right-hand jamb as seen from the yard. x runs from
    the masonry opening's edge into the opening; y is depth, exterior at the bottom."""
    T, sb, D = p["T"], o["setback"], door["jamb_depth"]
    (m0, m1, _, _), (r0, r1, _, _), (u0, u1, _, _) = o["mo"], o["ro"], o["unit"]
    b, gap, frame = o["buck"], (r1 - r0 - (u1 - u0)) / 2, 1.75
    fx = b + gap                       # where the door frame starts
    g = Svg(10, -34, T + 22, 104, T + 40)
    y = lambda t: -t                   # depth into the wall
    g.rect(-18, 0, 0, 4, "brick")
    g.rect(-18, 4, 0, T, "masonry")
    g.rect(0, sb, b, T, "pt")
    g.rect(b, sb, fx, sb + D, "gap")
    g.rect(fx, sb, fx + frame, sb + D, "unit")
    t_op, t_fix = sb + D * 0.28, sb + D * 0.72
    g.rect(fx + frame, t_op - 0.875, 34, t_op + 0.875, "panel")
    g.rect(fx + frame + 3, t_fix - 0.875, 34, t_fix + 0.875, "panel")
    g.line((-18, 0), (34, 0), "break")
    g.text((-18, -8), "EXTERIOR", "h", "start")
    g.text((-18, T + 9), "INTERIOR", "h", "start")
    g.dim((-18, 0), (-18, 4), frac(4), -3, -1)
    g.dim((-18, 0), (-18, T), f"wall {frac(T)}", -9, -1)
    g.dim((39, sb), (39, sb + D), f"jamb {frac(D)}", 0)
    g.note((47, T + 9), (34 - 4, t_fix + 0.875), "fixed panel, interior track", "start")
    g.note((47, -5), (34 - 4, t_op - 0.875), "operable panel, exterior track", "start")
    g.note((8, T + 14), (b / 2, T - 1.5), f"PT 2x8 buck, {frac(b)}", "start")
    g.note((8, -10), (b + gap / 2, sb + D * 0.5), f"shim space {frac(gap)}, low-expansion foam", "start")
    g.note((-17, -14), (-1.5, 2), f"face brick returns {frac(sb)} to the frame", "start")
    return g.svg("Plan at the door jamb")


def door_head(spec, p, door, o):
    T, sb, D = p["T"], o["setback"], door["jamb_depth"]
    (_, _, _, mh), (_, _, _, rh), (_, _, _, uh) = o["mo"], o["ro"], o["unit"]
    g = Svg(11, -6, mh + 22, T + 44, 34)
    x = lambda t: -t                   # exterior face at x = 0, inside to the right
    g.rect(x(0), mh, x(-4), mh + 16, "brick")
    g.rect(x(-4), mh + 7.25, x(-T), mh + 16, "masonry")
    g.rect(x(-4), mh, x(-T), mh + 7.25, "eng")
    g.poly([(x(0) + 0.5, mh), (x(-3.5), mh), (x(-3.5), mh + 3.5), (x(-3.2), mh + 3.5), (x(-3.2), mh + 0.31), (x(0) + 0.5, mh + 0.31)], "steel")
    g.rect(x(-sb), rh, x(-T), mh, "pt")
    g.rect(x(-sb), uh - 1.75, x(-sb - D), uh, "unit")
    g.rect(x(-sb), uh, x(-sb - D), rh, "gap")
    g.line((x(0), mh), (x(0), uh - 6), "break")
    g.text((x(0) + 0.3, mh + 19), "EXT", "h", "start")
    nx = T + 4
    g.note((nx, mh + 12), (x(-9), mh + 4), "inner lintel: by engineer", "start")
    g.note((nx, mh + 6.5), (x(-1.75), mh + 0.16), "steel angle under the face brick", "start")
    g.note((nx, mh + 1), (x(-9), mh - o["buck"] / 2), f"PT 2x8 buck head, {frac(o['buck'])}", "start")
    g.note((nx, uh - 4), (x(-sb - D / 2), uh - 0.9), f"frame head, {frac(rh - uh)} shim space over", "start")
    return g.svg("Head section")


def door_sill(spec, p, door, o):
    T, sb, D = p["T"], o["setback"], door["jamb_depth"]
    g = Svg(9, -26, 14, T + 66, 34)
    x = lambda t: -t
    g.rect(x(0), -16, x(-4), -1.5, "brick")
    g.rect(x(-4), -16, x(-T), -1, "masonry")
    g.rect(x(-sb), -0.25, x(-sb - D), 0.9, "unit")
    g.rect(x(-sb) - 0.5, -0.5, x(-sb - D) + 0.5, -0.25, "steel")
    g.rect(x(-T), -1, x(-T) + 18, 0, "floor")
    g.rect(x(0) - 24, -16, x(0), -1.5, "concrete")
    g.line((x(0) - 24, -16), (x(-T) + 18, -16), "break")
    g.text((x(0) - 23, -12), "EXT", "h", "start")
    g.note((x(-T) + 2, 9), (x(-sb - D / 2), 0.9), "door sill on a sloped sill pan", "start")
    g.note((x(-T) + 6, -6), (x(-T) + 10, -0.5), "first floor", "start")
    g.note((x(0) - 24, 6), (x(0) - 8, -1.5), f"landing, {frac(2.4)} below the sill", "start")
    return g.svg("Sill section")


# ---------------------------------------------------------------- porch sheets

def railing_elevation(spec, p):
    pc = spec["porch"]
    runs = build.rail_runs(spec, p)
    a, b = max(runs, key=lambda r: abs(r[1][0] - r[0][0]))   # the longest front run
    L = abs(b[0] - a[0])
    (cw, ct), (bw, bt), bg = build.RAIL["cap"], build.RAIL["bottom"], build.RAIL["bottom_gap"]
    h, post = pc["rail_height"], pc["post"]
    n, start, pitch = build.baluster_layout(L, pc)
    g = Svg(5.6, -post - 16, h + 22, L + 2 * post + 44, h + 42)
    g.line((-post - 8, 0), (L + post + 8, 0), "ground")
    for x0 in (-post, L):
        g.rect(x0, 0, x0 + post, h + 12, "wood")
    g.rect(0, h - ct, L, h, "wood")
    g.rect(0, bg, L, bg + bt, "wood")
    for i in range(n):
        s = start + i * pitch
        g.rect(s, bg + bt, s + pc["baluster"], h - ct, "wood baluster")
    g.dim((0, 0), (L, 0), f"{frac(L)} between posts, {n} balusters", -6, 1)
    g.dim((L + post, 0), (L + post, h), f"guard {frac(h)}", 6, -1)
    g.dim((-post, 0), (-post, bg), frac(bg), -5, -1)
    s1 = start + pitch
    g.dim((start + pc["baluster"], h + 4), (s1, h + 4), frac(pc["baluster_gap"]), 0)
    g.text(((start + s1) / 2 + 26, h + 8.5), "every gap under 4\"", "n", "start")
    g.dim((0, h + 4), (start, h + 4), frac(start), 0)
    g.note((L * 0.55, h + 15), (L * 0.55, h - 0.75), f"cap: 2x4 flat ({frac(cw)} x {frac(ct)})", "start")
    return g.svg("Railing elevation, longest front run"), n


def porch_plan(spec, p):
    pc, W = spec["porch"], p["W"]
    d, post = pc["depth"], pc["post"]
    edge = -d + post / 2 + 0.75
    g = Svg(3.2, -30, 30, W + 70, d + 92)
    g.rect(0, -d, W, 0, "deck")
    g.line((-10, 0), (W + 10, 0), "wallline")
    g.text((W / 2, 6), "house front wall", "n")
    st = pc["stair"]
    g.rect(st["x"], -d - st["tread"] * (st["risers"] - 1), st["x"] + st["width"], -d, "line")   # n risers, n - 1 treads
    g.text((st["x"] + st["width"] / 2, -d - 18), "stair", "n")
    for x in pc["posts_x"]:
        g.rect(x - post / 2, edge - post / 2, x + post / 2, edge + post / 2, "postsq")
    total = 0
    for i, (a, b) in enumerate(build.rail_runs(spec, p), 1):
        L = abs(b[0] - a[0]) + abs(b[1] - a[1])
        n, start, pitch = build.baluster_layout(L, pc)
        total += n
        along_x = abs(b[0] - a[0]) > abs(b[1] - a[1])
        for k in range(n):  # every baluster, so the drawing can be counted against the buy list
            s = start + k * pitch + pc["baluster"] / 2
            c = (min(a[0], b[0]) + s, a[1]) if along_x else (a[0], min(a[1], b[1]) + s)
            g.rect(c[0] - 0.75, c[1] - 0.75, c[0] + 0.75, c[1] + 0.75, "baluster")
        g.line(a, b, "rail")
        mid = ((a[0] + b[0]) / 2, (a[1] + b[1]) / 2)
        if along_x:
            g.text((mid[0], mid[1] - 9), f"run {i}: {frac(L)}, {n} bal.", "n")
        else:
            inward = 6 if a[0] < W / 2 else -6     # inside the porch, clear of the dims outside
            anchor = "start" if inward > 0 else "end"
            g.text((mid[0] + inward, mid[1] + 2.5), f"run {i}", "n", anchor)
            g.text((mid[0] + inward, mid[1] - 2.5), f"{frac(L)}, {n} bal.", "n", anchor)
    st_depth = st["tread"] * (st["risers"] - 1)
    g.dim((0, -d), (W, -d), frac(W), -(st_depth + 10), 1)
    g.dim((W, -d), (W, 0), f"depth {frac(d)}", -26, 1)
    xs = pc["posts_x"]
    for x0, x1 in zip(xs, xs[1:]):
        g.dim((x0, 0), (x1, 0), frac(x1 - x0), 10, 1)
    return g.svg("Porch plan with posts and guard runs"), total


# ---------------------------------------------------------------- pages

CSS = """
:root{--ink:#1f2a2e;--muted:#5d6b70;--line:#d9dcd6;--accent:#2f5d62}
*{box-sizing:border-box} body{margin:0;background:#fff;color:var(--ink);font:15px/1.5 system-ui,-apple-system,sans-serif}
main{max-width:980px;margin:0 auto;padding:20px 16px 60px} h1{font:600 26px/1.2 Georgia,serif;margin:8px 0}
h2{font-size:18px;margin:34px 0 4px;border-top:1px solid var(--line);padding-top:16px} h3{font-size:15px;margin:18px 0 4px}
a{color:var(--accent)} .lede{color:var(--muted);max-width:720px} .warn{background:#fff6e5;border:1px solid #f0d9a8;border-radius:8px;padding:8px 12px}
.brief{color:var(--muted);margin:2px 0 6px;max-width:760px} .open{font-size:13px;color:#8a5a00}
.scroll{overflow-x:auto;-webkit-overflow-scrolling:touch;margin:8px 0} svg{display:block;width:100%;height:auto;border:1px solid var(--line);border-radius:6px;background:#fff}
.pair{display:grid;grid-template-columns:1fr;gap:12px} @media(min-width:860px){.pair{grid-template-columns:1fr 1fr}}
table{width:100%;border-collapse:collapse;font-size:14px;margin:8px 0} th,td{text-align:left;padding:5px 6px;border-bottom:1px solid var(--line);vertical-align:top} td.n{text-align:right;white-space:nowrap}
.tablewrap{overflow-x:auto}
svg .wall{fill:#f7f5f1;stroke:#333;stroke-width:1.4} svg .open{fill:#fff;stroke:#222;stroke-width:1.6} svg .unit{fill:#eef3f5;stroke:#1f2a2e;stroke-width:2}
svg .pt{fill:url(#pt);stroke:#5f7a50;stroke-width:1} svg .steel{fill:#4b4f52;stroke:#222;stroke-width:.8} svg .eng{fill:#fff;stroke:#b5482d;stroke-width:1.2;stroke-dasharray:5 3}
svg .brick{fill:url(#brick);stroke:#7a4a3a;stroke-width:1} svg .masonry{fill:url(#masonry);stroke:#777;stroke-width:1} svg .gap{fill:#fffbe8;stroke:#c9b26b;stroke-width:.8}
svg .panel{fill:#d9e8ee;stroke:#1f2a2e;stroke-width:1.2} svg .concrete{fill:#ecebe7;stroke:#888;stroke-width:1} svg .floor{fill:#c9a77c;stroke:#7d6140;stroke-width:1}
svg .wood{fill:#fbfaf6;stroke:#333;stroke-width:1.1} svg .deck{fill:#f4f2ec;stroke:#333;stroke-width:1.4} svg .postsq{fill:#333} svg .baluster{fill:#555;stroke:none}
svg .rail{stroke:#2f5d62;stroke-width:2} svg .wallline{stroke:#222;stroke-width:3}
svg .line{fill:none;stroke:#333;stroke-width:1.2} svg .ground{stroke:#222;stroke-width:2.4} svg .break{stroke:#999;stroke-width:1;stroke-dasharray:8 4}
svg .dim{stroke:#2f5d9a;stroke-width:.9} svg .ext{stroke:#9db3d0;stroke-width:.7} svg .lead{stroke:#555;stroke-width:.8} svg .dot{fill:#2f5d9a}
svg .arrow{stroke:#c4561a;stroke-width:2.2;marker-end:none}
svg text{font-family:system-ui,-apple-system,sans-serif} svg .n{font-size:12px;fill:#333} svg .d{font-size:12px;fill:#2f5d9a;font-weight:600}
svg .h{font-size:13px;font-weight:700;fill:#111;letter-spacing:.5px} svg .big{font-size:16px;font-weight:700;fill:#c4561a}
@media print{body{font-size:11px} main{max-width:none;padding:0} .noprint{display:none} svg{min-width:0!important;border:none;max-height:7in;break-inside:avoid}
  .sheet{break-before:page} h2{border:none}}
@page{size:letter;margin:.5in}
"""


def sheet(sid, reg, body):
    s = reg["sheets"][sid]
    opens = "".join(f"<li>{html.escape(x)}</li>" for x in s.get("open", []))
    return (f'<section class="sheet" id="{sid}"><h2>{sid} · {html.escape(s["title"])}</h2>'
            f'<p class="brief">{html.escape(s["brief"])} <i>{html.escape(s["confidence"])}</i></p>'
            + (f'<ul class="open">{opens}</ul>' if opens else "") + body + "</section>")


def table(rows, head):
    return ('<div class="tablewrap"><table><thead><tr>' + "".join(f"<th>{h}</th>" for h in head) + "</tr></thead><tbody>"
            + "".join("<tr>" + "".join(f'<td class="{"n" if isinstance(c, (int, float)) else ""}">{c}</td>' for c in r) + "</tr>" for r in rows)
            + "</tbody></table></div>")


def takeoff_html(pieces, bought, extra):
    cut = table([(html.escape(x["part"]), x["profile"], x["qty"], frac(x["length"]), html.escape(x["note"])) for x in pieces],
                ["Part", "Stock", "Qty", "Length", "Note"])
    rows = [(b["profile"], f"{b['stock_ft']}'", b["count"],
             "<br>".join(" + ".join(frac(l) for l in bd) for bd in b["boards"])) for b in bought]
    rows += [(html.escape(a), html.escape(b), c, html.escape(d)) for a, b, c, d in extra]
    buy_t = table(rows, ["Buy", "Length", "Qty", "Cut from each"])
    return (f'<section class="sheet"><h2>Cut list</h2>{cut}<h2>Buy list</h2>'
            f'<p class="brief">Boards packed longest-first with a {frac(KERF)} saw kerf between cuts; the stock length is whichever wastes least.</p>{buy_t}</section>')


def page(title, lede, body, pdf):
    return (f'<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
            f'<title>{html.escape(title)}</title><style>{CSS}</style></head><body><main>'
            f'<p class="noprint"><a href="../../">← 3D model</a> · <a href="../">all drawings</a> · <a href="{pdf}">PDF for printing</a></p>'
            f'<h1>{html.escape(title)}</h1><p class="lede">{lede}</p>'
            f'<p class="warn"><b>Design study, not for construction.</b> Drawn from the same numbers as the 3D model. '
            f'Lintels and anything structural need an engineer; verify every dimension in the field.</p>{body}</main></body></html>')


def main():
    spec = build.resolve(build.load("house.yaml"))
    doors = build.resolve(build.load("doors.yaml"))
    reg = build.load("drawings.yaml")
    p = build.plan(spec)
    takeoff = {}
    index = []

    for d_id, door in doors.items():
        if not door.get("unit"):
            continue
        o = build.rear_opening(spec, p, door)
        r = reg["door"]
        pieces = door_pieces(o, door)
        bought = buy(pieces)
        extra = [(door["model"], door["maker"], 1, f'unit {frac(door["unit"]["width"])} x {frac(door["unit"]["height"])}'),
                 ("steel angle " + spec["rear_door_install"]["lintel_angle"], "cut to length", 1, frac(pieces[2]["length"])),
                 ("sloped sill pan", "to suit", 1, f"{frac(door['unit']['width'])} long"),
                 ("masonry screws + low-expansion foam + sealant", "", 1, "")]
        specrow = table([(f'<a href="{door["url"]}">{html.escape(door["model"])}</a>',
                          f'{frac(door["unit"]["width"])} x {frac(door["unit"]["height"])}',
                          f'{frac(door["rough_opening"]["width"])} x {frac(door["rough_opening"]["height"])}',
                          frac(door["jamb_depth"]), html.escape(door.get("glass", "")))],
                        ["Door (maker's sheet)", "Unit", "Rough opening", "Jamb", "Glass"])
        body = (specrow
                + sheet("A1", r, door_elevation(spec, p, door, o))
                + sheet("A2", r, door_plan(spec, p, door, o))
                + sheet("A3", r, f'<div class="pair">{door_head(spec, p, door, o)}{door_sill(spec, p, door, o)}</div>')
                + takeoff_html(pieces, bought, extra))
        slug = f"door-{d_id}"
        (OUT / slug).mkdir(parents=True, exist_ok=True)
        (OUT / slug / "index.html").write_text(page(
            f"{r['title']}: {door['maker']} {door['label'].split(' ', 1)[-1]}",
            f"The {html.escape(door['model'])} in the rear wing's 12\" brick wall. Inches; seen from the yard unless noted.",
            body, f"{slug}.pdf"))
        takeoff[slug] = {"pieces": pieces, "bought": bought, "mo": o["mo"], "ro": o["ro"], "unit": o["unit"]}
        index.append((slug, f"{r['title']}: {door['maker']} {door['label'].split(' ', 1)[-1]}"))

    r = reg["porch"]
    opts = build.load("options.yaml")
    fields = {f["id"]: f for sec in opts["sections"] for f in sec["fields"]}
    pitch = fields["porch_pitch"]["default"]
    for rail in fields["rail_height"]["values"]:
        for depth in fields["porch_depth"]["values"]:
            v = build.porch_variant(spec, pitch, rail, depth)   # the same step the viewer shows
            pieces, n_bal = porch_pieces(v, p)
            bought = buy(pieces)
            elev, _ = railing_elevation(v, p)
            plan_svg, drawn = porch_plan(v, p)
            extra = [("2 1/2\" exterior screws", "1 lb box", 2, ""), ("structural screws, rail to post", "", 4 * len(build.rail_runs(v, p)), "")]
            body = sheet("P1", r, elev) + sheet("P2", r, plan_svg) + takeoff_html(pieces, bought, extra)
            slug = f"porch-{rail}-{depth}"
            title = f"{r['title']}: {rail}\" guard, {depth}' deep"
            (OUT / slug).mkdir(parents=True, exist_ok=True)
            (OUT / slug / "index.html").write_text(page(title, "Guard rail for the front porch: posts, caps, bottom rails and balusters. Inches.", body, f"{slug}.pdf"))
            takeoff[slug] = {"pieces": pieces, "bought": bought, "balusters_drawn": drawn, "balusters_cut": n_bal,
                             "rail_height": float(rail), "depth": float(depth)}
            index.append((slug, title))

    links = "".join(f'<li><a href="{s}/">{html.escape(t)}</a> · <a href="{s}/{s}.pdf">PDF</a></li>' for s, t in index)
    (OUT / "index.html").write_text(
        f'<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
        f'<title>Drawings</title><style>{CSS}</style></head><body><main><p><a href="../">← 3D model</a></p><h1>Construction drawings</h1>'
        f'<p class="lede">Drawn from the same numbers as the 3D model, so picking a different door gives you a different set.</p><ul>{links}</ul></main></body></html>')
    (OUT / "takeoff.json").write_text(json.dumps(takeoff, indent=1) + "\n")
    print(f"wrote {len(index)} drawing sets to {OUT.relative_to(build.ROOT)}/")


if __name__ == "__main__":
    main()
