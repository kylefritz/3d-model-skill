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


SAMPLE_WORKLOG = {  # a made-up session, so the work log table is exercised without a real worklog
    "prices_as_of": "2026-01-01",
    "sessions": [{"date": "2026-01-02", "session": "0000abcd", "title": "Sample session", "turns": 120,
                  "tokens": 4_200_000, "cost": 3.5, "unpriced": False,
                  "roles": {"lead": {"models": ["claude-opus-5-5"]}, "workers": {"models": ["claude-sonnet-5-5"]}}}],
    "total": {"turns": 120, "tokens": 4_200_000, "cost": 3.5, "unpriced": False},
}


def check_details(browser, base):
    """Model details: the size and counts of what's on screen, and the work log when stats.json has one."""
    page = browser.new_page(viewport={"width": 1280, "height": 900})
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))

    def with_worklog(route):
        body = route.fetch().json()
        body["worklog"] = SAMPLE_WORKLOG
        route.fulfill(json=body)

    page.route("**/stats.json", with_worklog)
    page.goto(base)
    page.wait_for_function("window.viewer", timeout=60000)
    summary = page.locator("fieldset.details summary")
    check(summary.count() == 1 and ("KB" in summary.inner_text() or "MB" in summary.inner_text()),
          f"model details shows the size ({summary.inner_text() if summary.count() else 'missing'})")
    summary.click()
    facts = page.evaluate("Object.fromEntries([...document.querySelectorAll('.details dl div')].map(d => [d.querySelector('dt').textContent, d.querySelector('dd').textContent]))")
    check(int(facts.get("Draw calls", "0").replace(",", "")) > 0, f"details counts draw calls ({facts.get('Draw calls')})")
    check(facts.get("Scan points") == "off", "scan points read off while the layer is off")
    page.evaluate("viewer.display.scan = true; viewer.set('body', 'sw2802')")
    page.wait_for_timeout(2500)
    scan = page.evaluate("document.querySelector('.details dl div:nth-child(7) dd').textContent")
    check(scan not in ("off", ""), f"turning the scan on counts its points ({scan})")
    check(page.evaluate("document.querySelector('fieldset.details details').open"), "details stays open across a panel rebuild")
    rows = page.locator(".worklog tbody tr").count()
    check(rows == 1 and "$3.50" in page.locator(".worklog tfoot").inner_text(), "work log lists sessions and a cost total")
    check(not errors, f"no page errors in details {errors[:2]}")
    page.close()


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

        # existing vs proposed: existing shows the house as measured, and your design comes back
        page.evaluate("viewer.setState('existing')")
        page.wait_for_timeout(1200)
        slots = page.evaluate("viewer.slots()")
        check(slots["door"].endswith("door-none.glb") and "porch-1-36-8" in slots["porch"], f"existing shows the measured house ({slots['door']}, {slots['porch']})")
        check("state=existing" in page.url and "door=marvin" in page.url, "the link keeps your design while showing existing")
        page.evaluate("viewer.setState('proposed')")
        page.wait_for_timeout(1200)
        check(page.evaluate("viewer.settings().door") == "marvin", "back to proposed restores your door")

        # light, plan cut, evidence
        page.evaluate("viewer.display.light = 'dusk'; viewer.applyLight()")
        check(page.evaluate("viewer.scene.children.some(o => o.isGroup && o.visible && o.children.some(c => c.isPointLight && c.intensity > 0))"), "dusk turns the lights on")
        page.evaluate("viewer.display.light = 'day'; viewer.applyLight()")
        page.select_option("#view", str(page.evaluate("viewer.tours && document.querySelector('#view').options.length") - 2))
        page.wait_for_timeout(500)
        check(page.evaluate("viewer.renderer.clippingPlanes.length") == 1, "a plan view clips above the cut")
        page.select_option("#view", "2")
        page.wait_for_timeout(300)
        check(page.evaluate("viewer.renderer.clippingPlanes.length") == 0, "leaving it removes the cut")
        page.evaluate("viewer.display.scan = true")
        page.evaluate("viewer.set('body', 'sw2802')")
        page.wait_for_timeout(2500)
        check(page.evaluate("viewer.scene.children.some(o => o.visible && (() => { let p = false; o.traverse(c => { if (c.isPoints) p = true; }); return p; })())"), "the scan points layer loads")
        page.evaluate("viewer.display.scan = false")
        page.wait_for_timeout(400)
        check("scan=1" in page.url, "the link remembers the evidence layer")

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
        # both taps in one script call: in a slow headless browser, two separate taps can land
        # more than the 350 ms double-tap window apart once frames get heavy (shadows)
        page.evaluate("""() => { const c = viewer.renderer.domElement;
          for (let i = 0; i < 2; i++) for (const type of ['pointerdown', 'pointerup'])
            c.dispatchEvent(new PointerEvent(type, {clientX: 195, clientY: 560, pointerId: 7, pointerType: 'touch', bubbles: true})); }""")
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
        check_details(browser, base)
        browser.close()
    if failures:
        sys.exit(1)


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "http://localhost:8000/")
