# /// script
# requires-python = ">=3.11"
# dependencies = ["playwright>=1.47"]
# ///
"""Shoot the README images from a running site.

    uv run tools/screenshots.py http://localhost:8000/ docs/img

Each shot is a query string, the same link the Share button makes, so a screenshot
is reproducible from its file name. First run: `uvx playwright install chromium`.
"""

import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

SHOTS = {
    # name: (query, viewport)
    "street-brick": ("view=street", "desktop"),
    "street-lap-sea-salt": ("cladding=lap&body=sw6204&trim=sw7005&porch_floor=sw6244&view=street", "desktop"),
    "street-shingle": ("cladding=shingle&body=sw6187&porch_ceiling=sw7005&front_door=sw6258&view=street", "desktop"),
    "porch-painted-brick": ("paint_brick=1&body=sw7005&trim=sw6258&porch_trim=sw6258&front_door=sw6244&view=front-porch", "desktop"),
    "rear-andersen": ("door=andersen200&door_open=60&view=rear-door", "desktop"),
    "rear-batten-marvin": ("cladding=batten&body=sw7036&door=marvin&door_open=0&view=back-yard", "desktop"),
    "rear-none": ("door=none&view=rear-door", "desktop"),
    "inside": ("door=pella&door_open=80&view=inside", "desktop"),
    "phone-street": ("cladding=lap&body=sw2802&view=street", "phone"),
    "phone-panel": ("cladding=batten&body=sw6244&view=front-porch&panel=1", "phone"),
}
VIEWPORTS = {
    "desktop": dict(viewport={"width": 1280, "height": 800}, device_scale_factor=1),
    "phone": dict(viewport={"width": 390, "height": 844}, device_scale_factor=2, is_mobile=True, has_touch=True),
}


def main(base, out, only=None):
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        browser = p.chromium.launch(args=["--use-angle=swiftshader", "--enable-unsafe-swiftshader"])
        for name, (query, kind) in SHOTS.items():
            if only and name not in only:
                continue
            page = browser.new_page(**VIEWPORTS[kind])
            page.goto(f"{base}?{query}")
            page.wait_for_function("document.body.classList.contains('ready')", timeout=60000)
            if "panel=1" in query:
                page.click("#panel-toggle")
            page.wait_for_timeout(1500)
            page.screenshot(path=str(out / f"{name}.png"))
            page.close()
            print(out / f"{name}.png")
        browser.close()


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2], sys.argv[3:] or None)
