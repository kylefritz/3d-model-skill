# /// script
# requires-python = ">=3.11"
# dependencies = ["playwright>=1.47", "pillow>=10"]
# ///
"""Record a viewer tour to video, frame by frame.

    uv run tools/record_tour.py http://localhost:8000/ 0 out/tour            # tour 0 -> out/tour.mp4 + .gif
    uv run tools/record_tour.py http://localhost:8000/ 0 out/tour --every 1  # 1 frame a second, contact sheet only
    uv run tools/record_tour.py http://localhost:8000/ 0 out/tour --vertical # 1080x1920 for phones

The viewer's animation loop stops and each frame is posed from t alone
(window.viewer.tourFrame), so the video is smooth however slow the browser is.
Needs ffmpeg on PATH for the .mp4 and .gif.
"""

import argparse
import base64
import shutil
import tempfile
import subprocess
from pathlib import Path

from PIL import Image
from playwright.sync_api import sync_playwright


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("base")
    ap.add_argument("tour", type=int)
    ap.add_argument("out")
    ap.add_argument("--fps", type=int, default=24)
    ap.add_argument("--every", type=float, help="seconds between frames; writes a contact sheet instead of video")
    ap.add_argument("--vertical", action="store_true")
    a = ap.parse_args()
    out = Path(a.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    frames = Path(tempfile.mkdtemp(prefix="tour-"))   # never next to the output, so frames don't get committed
    size = {"width": 540, "height": 960} if a.vertical else {"width": 1280, "height": 720}
    with sync_playwright() as p:
        b = p.chromium.launch(args=["--use-angle=swiftshader", "--enable-unsafe-swiftshader"])
        page = b.new_page(viewport=size, device_scale_factor=2 if a.vertical else 1)
        page.goto(a.base)
        page.wait_for_function("window.viewer", timeout=60000)
        page.add_style_tag(content="#panel,#dock,#title,#walk-pad{display:none!important}")
        end = page.evaluate(f"viewer.tours[{a.tour}].keys.at(-1).at")
        step = a.every or 1 / a.fps
        n = int(end / step) + 1
        for i in range(n):
            url = page.evaluate(f"viewer.tourFrame({a.tour}, {i * step})")
            (frames / f"f{i:05d}.jpg").write_bytes(base64.b64decode(url.split(",", 1)[1]))
        b.close()
    if a.every:
        ims = [Image.open(f) for f in sorted(frames.glob("*.jpg"))]
        w, h = 320, int(320 * ims[0].height / ims[0].width)
        cols = 6
        sheet = Image.new("RGB", (w * cols, h * ((len(ims) + cols - 1) // cols)), "white")
        for i, im in enumerate(ims):
            sheet.paste(im.resize((w, h)), ((i % cols) * w, (i // cols) * h))
        sheet.save(out.with_suffix(".png"))
        shutil.rmtree(frames)
        print(out.with_suffix(".png"))
        return
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-framerate", str(a.fps), "-i", str(frames / "f%05d.jpg"),
                    "-c:v", "libx264", "-crf", "20", "-preset", "slow", "-pix_fmt", "yuv420p", "-movflags", "+faststart",
                    str(out.with_suffix(".mp4"))], check=True)
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(out.with_suffix(".mp4")), "-vf",
                    "fps=8,scale=480:-1:flags=lanczos,split[a][b];[a]palettegen=max_colors=64:stats_mode=diff[p];[b][p]paletteuse=dither=bayer:bayer_scale=4:diff_mode=rectangle",
                    str(out.with_suffix(".gif"))], check=True)
    shutil.rmtree(frames)
    print(out.with_suffix(".mp4"), out.with_suffix(".gif"))


if __name__ == "__main__":
    main()
