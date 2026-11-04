# /// script
# requires-python = ">=3.11"
# dependencies = ["playwright>=1.47"]
# ///
"""Drive the viewer like a person would and check it reacts.

    uv run tools/check_viewer.py http://localhost:8000/

On an emulated iPhone: open the panel, swap cladding and door, recolor, slide the door,
enter Walk, hold the joystick (it should move, and faster the longer you hold),
double-tap the ground (it should go there). Headless WebGL is slow (often under
20 fps), so it checks that speed rises over a hold, not the absolute speed.
"""

import sys

from playwright.sync_api import sync_playwright

failures = []


def check(ok, msg):
    print(("ok   " if ok else "FAIL ") + msg)
    if not ok:
        failures.append(msg)


def cam(page):
    return page.evaluate("viewer.camera.position.toArray()")


def dist(a, b):
    return sum((x - y) ** 2 for x, y in zip(a, b)) ** 0.5


def main(base):
    with sync_playwright() as p:
        browser = p.chromium.launch(args=["--use-angle=swiftshader", "--enable-unsafe-swiftshader"])
        page = browser.new_page(**p.devices["iPhone 13"])
        errors = []
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.goto(base + "?view=back-yard")
        page.wait_for_function("window.viewer", timeout=60000)

        # swaps load their files and the URL follows
        page.evaluate("viewer.set('cladding', 'shingle')")
        page.evaluate("viewer.set('door', 'marvin')")
        page.wait_for_timeout(1500)
        names = page.evaluate("(() => { const s = new Set(); viewer.root.traverse(o => o.isMesh && s.add(o.material.name)); return [...s]; })()")
        check("door.frame" in names, "door GLB loaded")
        page.wait_for_timeout(400)
        check("cladding=shingle" in page.url and "door=marvin" in page.url, "share link carries the choices")
        check(page.evaluate("viewer.settings().door_color") == "stone_white", "door color falls back to the new maker's first color")

        # color: every paint.body material takes the chip
        page.evaluate("viewer.set('body', 'sw2802')")
        hexes = page.evaluate("(() => { const s = new Set(); viewer.root.traverse(o => o.isMesh && o.material.name === 'paint.body' && s.add(o.material.color.getHexString())); return [...s]; })()")
        check(hexes == ["622f2d"], f"body paint applied ({hexes})")

        # range: the operable panel moves by the travel in the contract
        before = page.evaluate("(() => { let x; viewer.root.traverse(o => { if ((o.userData.name || '').startsWith('door.operable')) x = o.position.x; }); return x; })()")
        page.evaluate("viewer.set('door_open', 100)")
        page.wait_for_timeout(300)
        after = page.evaluate("(() => { let x; viewer.root.traverse(o => { if ((o.userData.name || '').startsWith('door.operable')) x = o.position.x; }); return x; })()")
        check(before is not None and after < before - 0.3, f"door slides open ({before} -> {after})")

        # steps: a geometry slider loads its pre-built shape, and the drawings link follows it
        page.evaluate("viewer.set('rail_height', '42')")
        page.evaluate("viewer.set('porch_depth', '6')")
        page.wait_for_timeout(1500)
        check("rail_height=42" in page.url and "porch_depth=6" in page.url, "geometry sliders land in the share link")
        page.click("#panel-toggle")
        hrefs = page.evaluate("[...document.querySelectorAll('a.drawings')].map(a => a.getAttribute('href'))")
        check("drawings/porch-42-6/" in hrefs, f"porch drawings link follows the sliders ({hrefs})")
        check("drawings/door-marvin/" in hrefs, "door drawings link follows the door")
        r = page.request.get(base + "drawings/porch-42-6/")
        check(r.ok and "porch-42-6.pdf" in r.text(), "that drawing set exists")
        page.click("#panel-toggle")

        # a tour moves the camera on its own, then gives orbit back
        page.wait_for_timeout(300)
        c0 = cam(page)
        page.click("#tour")
        page.wait_for_timeout(2500)
        check(dist(c0, cam(page)) > 1, "Tour flies the camera")
        page.click("#tour")
        check(page.evaluate("viewer.orbit.enabled"), "stopping the tour gives orbit back")

        # walk keeps the view (from a known spot: the tour left the camera somewhere).
        # Wait on state, not time: headless WebGL can run at 5 fps, and the viewer caps each
        # frame's step, so a 0.6 s flight can take seconds of wall clock.
        page.select_option("#view", "2")
        page.wait_for_function("!viewer.moving()", timeout=20000)
        start_dir = page.evaluate("viewer.camera.getWorldDirection(new viewer.THREE.Vector3()).toArray()")
        page.click("#walk")
        page.wait_for_timeout(200)
        same_dir = page.evaluate("viewer.camera.getWorldDirection(new viewer.THREE.Vector3()).toArray()")
        check(dist(start_dir, same_dir) < 0.05, "entering Walk keeps the view")
        check(page.is_visible("#walk-stick"), "joystick shows on a touch screen")

        # double-tap the ground in the lower middle of the screen, while there's yard ahead
        before = cam(page)
        for _ in range(2):
            page.touchscreen.tap(195, 560)
            page.wait_for_timeout(120)
        page.wait_for_function("!viewer.moving()", timeout=20000)
        moved = dist(before, cam(page))
        check(moved > 0.3, f"double-tap goes there ({moved:.2f} m)")

        # hold the stick forward: it walks, level, and the pace climbs while held
        box = page.locator("#walk-stick").bounding_box()
        cx, cy = box["x"] + box["width"] / 2, box["y"] + box["height"] / 2
        page.mouse.move(cx, cy)
        page.mouse.down()
        page.mouse.move(cx, cy - 60)
        p0 = cam(page)
        try:
            page.wait_for_function("viewer.walkPace() > 1.3", timeout=30000)
            pace = page.evaluate("viewer.walkPace()")
        except Exception:
            pace = page.evaluate("viewer.walkPace()")
        p1 = cam(page)
        page.mouse.up()
        check(dist(p0, p1) > 0.05, f"stick walks ({dist(p0, p1):.2f} m)")
        check(pace > 1.3, f"holding speeds up (pace reached {pace:.2f}x)")
        check(abs(p1[1] - p0[1]) < 0.01, "walking stays level")

        check(not errors, f"no page errors {errors[:2]}")
        browser.close()
    if failures:
        sys.exit(1)


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "http://localhost:8000/")
