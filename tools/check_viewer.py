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

        # walk keeps the view
        start_dir = page.evaluate("viewer.camera.getWorldDirection(new viewer.THREE.Vector3()).toArray()")
        page.click("#walk")
        page.wait_for_timeout(200)
        same_dir = page.evaluate("viewer.camera.getWorldDirection(new viewer.THREE.Vector3()).toArray()")
        check(dist(start_dir, same_dir) < 0.05, "entering Walk keeps the view")
        check(page.is_visible("#walk-stick"), "joystick shows on a touch screen")

        # hold the stick forward: it moves, and the second half of a hold covers more ground
        box = page.locator("#walk-stick").bounding_box()
        cx, cy = box["x"] + box["width"] / 2, box["y"] + box["height"] / 2
        page.mouse.move(cx, cy)
        page.mouse.down()
        page.mouse.move(cx, cy - 60)
        p0 = cam(page)
        page.wait_for_timeout(1800)
        p1 = cam(page)
        page.wait_for_timeout(1800)
        p2 = cam(page)
        page.mouse.up()
        early, late = dist(p0, p1), dist(p1, p2)
        check(early > 0.05, f"stick walks ({early:.2f} m in the first 1.8 s)")
        check(late > early * 1.2, f"holding speeds up ({early:.2f} m then {late:.2f} m)")
        check(abs(p2[1] - p0[1]) < 0.01, "walking stays level")

        # double-tap the ground in the lower middle of the screen
        page.wait_for_timeout(300)
        before = cam(page)
        x, y = 195, 560
        page.touchscreen.tap(x, y)
        page.wait_for_timeout(120)
        page.touchscreen.tap(x, y)
        page.wait_for_timeout(1500)
        moved = dist(before, cam(page))
        check(moved > 0.3, f"double-tap goes there ({moved:.2f} m)")

        check(not errors, f"no page errors {errors[:2]}")
        browser.close()
    if failures:
        sys.exit(1)


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "http://localhost:8000/")
