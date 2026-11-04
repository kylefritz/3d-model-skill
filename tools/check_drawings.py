# /// script
# requires-python = ">=3.11"
# dependencies = ["playwright>=1.47"]
# ///
"""Are the construction drawings readable? Renders every drawing set in Chromium and fails when:

- two labels overlap,
- a label is crossed by any line: a leader (its own included), a dimension or extension
  line, or a part's outline (a label may sit inside a part, but not across its edge),
- a label runs past the drawing's edge,
- leader lines cross each other (a crossed callout points at the wrong part),
- a label renders under 9px on a 390px phone, or the page scrolls sideways there.

With --pdf it also prints each set to <set>/<set>.pdf (letter, 1/2" margins).

    uv run tools/check_drawings.py http://localhost:8000/drawings/ [--pdf]

Ported from the Tunnel of Terror coffin drawings check. Text boxes are glyph boxes
(getBBox) in each label's own rotated frame, trimmed a little top and bottom because
the box includes the font's full ascent and descent.
"""

import json
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
MIN_PX = 9

GEOMETRY_JS = r"""() => {
  const inv = m => m.inverse();
  const pt = (m, x, y) => { const p = new DOMPoint(x, y).matrixTransform(m); return [p.x, p.y]; };
  // Clip a segment to a rectangle (Liang-Barsky); null if it misses. Parts in a nested <svg> are clipped to it.
  const clip = (a, b, r) => {
    let t0 = 0, t1 = 1; const dx = b[0] - a[0], dy = b[1] - a[1];
    for (const [p, q] of [[-dx, a[0] - r.left], [dx, r.right - a[0]], [-dy, a[1] - r.top], [dy, r.bottom - a[1]]]) {
      if (p === 0) { if (q < 0) return null; continue; }
      const t = q / p;
      if (p < 0) { if (t > t1) return null; if (t > t0) t0 = t; } else { if (t < t0) return null; if (t < t1) t1 = t; }
    }
    return [[a[0] + t0 * dx, a[1] + t0 * dy], [a[0] + t1 * dx, a[1] + t1 * dy]];
  };
  const segsOf = el => {
    const m = el.getScreenCTM(), raw = [];
    const out = { push: s => raw.push(s) };
    const tag = el.tagName;
    if (tag === 'line') out.push([pt(m, +el.getAttribute('x1'), +el.getAttribute('y1')), pt(m, +el.getAttribute('x2'), +el.getAttribute('y2'))]);
    else if (tag === 'polygon' || tag === 'polyline') {
      const ps = [...el.points].map(p => pt(m, p.x, p.y));
      for (let i = 0; i + 1 < ps.length; i++) out.push([ps[i], ps[i + 1]]);
      if (tag === 'polygon' && ps.length > 2) out.push([ps[ps.length - 1], ps[0]]);
    } else if (tag === 'path') {
      const L = el.getTotalLength(), n = Math.max(8, Math.ceil(L / 4));
      let prev = null;
      for (let i = 0; i <= n; i++) { const p = el.getPointAtLength(L * i / n); const q = pt(m, p.x, p.y); if (prev) out.push([prev, q]); prev = q; }
    } else if (tag === 'circle') {
      const cx = +el.getAttribute('cx'), cy = +el.getAttribute('cy'), r = +el.getAttribute('r');
      const ps = [[cx - r, cy - r], [cx + r, cy - r], [cx + r, cy + r], [cx - r, cy + r]].map(([x, y]) => pt(m, x, y));
      for (let i = 0; i < 4; i++) out.push([ps[i], ps[(i + 1) % 4]]);
    }
    const own = el.ownerSVGElement;
    let r = own.getBoundingClientRect();
    if (own.ownerSVGElement) {  // a nested <svg>: its viewport, from its own attributes (its client rect is its content's)
      const pm = own.ownerSVGElement.getScreenCTM(), g = n => own[n].baseVal.value;
      const [a, b] = [pt(pm, g('x'), g('y')), pt(pm, g('x') + g('width'), g('y') + g('height'))];
      r = {left: a[0], top: a[1], right: b[0], bottom: b[1]};
    }
    return raw.map(([a, b]) => clip(a, b, r)).filter(Boolean);
  };
  // Liang-Barsky: does segment a-b enter the box?
  const crosses = (a, b, box) => {
    let t0 = 0, t1 = 1; const dx = b[0] - a[0], dy = b[1] - a[1];
    for (const [p, q] of [[-dx, a[0] - box.x0], [dx, box.x1 - a[0]], [-dy, a[1] - box.y0], [dy, box.y1 - a[1]]]) {
      if (p === 0) { if (q < 0) return false; continue; }
      const r = q / p;
      if (p < 0) { if (r > t1) return false; if (r > t0) t0 = r; } else { if (r < t0) return false; if (r < t1) t1 = r; }
    }
    return true;
  };
  const corners = t => [[t.box.x0, t.box.y0], [t.box.x1, t.box.y0], [t.box.x1, t.box.y1], [t.box.x0, t.box.y1]].map(([x, y]) => pt(t.m, x, y));
  const sat = (A, B) => {
    for (const P of [A, B]) for (let i = 0; i < 4; i++) {
      const [x1, y1] = P[i], [x2, y2] = P[(i + 1) % 4], nx = y1 - y2, ny = x2 - x1;
      const pa = A.map(([x, y]) => x * nx + y * ny), pb = B.map(([x, y]) => x * nx + y * ny);
      if (Math.max(...pa) < Math.min(...pb) || Math.max(...pb) < Math.min(...pa)) return false;
    }
    return true;
  };
  return [...document.querySelectorAll('main svg:not(svg svg)')].map(svg => {
    const label = svg.getAttribute('aria-label');
    const sb = svg.getBoundingClientRect(), vb = svg.viewBox.baseVal;
    const scale = sb.width / vb.width;
    const texts = [...svg.querySelectorAll('text')].filter(t => t.textContent.trim()).map(t => {
      const b = t.getBBox(), trimY = b.height * 0.2, trimX = 1;
      return {s: t.textContent, m: t.getScreenCTM(), mi: inv(t.getScreenCTM()),
              box: {x0: b.x + trimX, x1: b.x + b.width - trimX, y0: b.y + trimY, y1: b.y + b.height - trimY},
              px: parseFloat(getComputedStyle(t).fontSize) * scale};
    });
    const segs = [];
    for (const el of svg.querySelectorAll('line, polygon, polyline, path, circle')) {
      if (el.closest('defs')) continue;
      for (const s of segsOf(el)) segs.push({s, cls: el.getAttribute('class') || el.tagName});
    }
    const issues = [];
    texts.forEach((t, i) => {
      for (const c of corners(t)) if (c[0] < sb.left - 0.5 || c[0] > sb.right + 0.5 || c[1] < sb.top - 0.5 || c[1] > sb.bottom + 0.5) { issues.push(`runs off the drawing: "${t.s}"`); break; }
      const hit = new Set();
      for (const {s, cls} of segs) if (crosses(pt(t.mi, ...s[0]), pt(t.mi, ...s[1]), t.box)) hit.add(cls);
      if (hit.size) issues.push(`"${t.s}" is crossed by ${[...hit].join(', ')}`);
      for (let j = i + 1; j < texts.length; j++) if (sat(corners(t), corners(texts[j]))) issues.push(`"${t.s}" overlaps "${texts[j].s}"`);
    });
    // Leaders must not cross each other: crossed callouts read as pointing at the wrong part.
    const leads = segs.filter(x => x.cls === 'lead').map(x => x.s);
    const side = (p, q, r) => Math.sign((q[0] - p[0]) * (r[1] - p[1]) - (q[1] - p[1]) * (r[0] - p[0]));
    let crossed = 0;
    for (let i = 0; i < leads.length; i++) for (let j = i + 1; j < leads.length; j++) {
      const [a, b] = leads[i], [c, d] = leads[j];
      if (side(a, b, c) * side(a, b, d) < 0 && side(c, d, a) * side(c, d, b) < 0) crossed++;
    }
    if (crossed) issues.push(`${crossed} pair(s) of leader lines cross`);
    const smallest = texts.length ? Math.min(...texts.map(t => t.px)) : 99;
    const box = svg.parentElement.getBoundingClientRect();
    return {label, issues, smallest, scrolls: sb.width > box.width + 1};
  });
}"""


def sets(base):
    takeoff = json.loads((ROOT / "site/drawings/takeoff.json").read_text())
    return [(slug, base.rstrip("/") + f"/{slug}/") for slug in takeoff]


def run(base, pdf=False):
    fails = []
    with sync_playwright() as p:
        b = p.chromium.launch()
        for slug, url in sets(base):
            for width in (1000, 390):
                page = b.new_page(viewport={"width": width, "height": 900}, device_scale_factor=2)
                page.goto(url, wait_until="networkidle")
                if width == 390 and page.evaluate("document.documentElement.scrollWidth") > width:
                    fails.append(f"{slug} {width}px: the page scrolls sideways")
                for d in page.evaluate(GEOMETRY_JS):
                    if width == 1000:
                        fails += [f"{slug} / {d['label']}: {i}" for i in d["issues"]]
                    if d["smallest"] < MIN_PX:
                        fails.append(f"{slug} / {d['label']}: labels are {d['smallest']:.1f}px on a {width}px screen (min {MIN_PX})")
                if pdf and width == 1000:
                    out = ROOT / "site/drawings" / slug / f"{slug}.pdf"
                    page.emulate_media(media="print")
                    page.pdf(path=str(out), format="Letter", margin={k: "0.5in" for k in ("top", "bottom", "left", "right")}, print_background=True)
                page.close()
        b.close()
    return fails


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    fails = run(args[0] if args else "http://localhost:8000/drawings/", pdf="--pdf" in sys.argv)
    for f in fails:
        print("FAIL", f)
    print(f"{len(fails)} readability problems" if fails else "ok   every drawing is readable")
    sys.exit(1 if fails else 0)
