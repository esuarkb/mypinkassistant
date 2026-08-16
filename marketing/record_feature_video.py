"""
TikTok feature-video recorder — scripted Playwright session against the LOCAL
app (127.0.0.1:8777) using the local throwaway login (consultant 55,
demo.video@example.com — local SQLite only, never prod).

Records a phone-aspect browser session of:
  1. Product lookup: "Charcoal mask" -> price / Part # / Fact Sheet / OOA card
  2. Catalog browse: "What fragrances do we have" -> 20-product list + scroll

Writes video (webm) + events.json (timestamps for the ffmpeg overlay pass in
build_tiktok.py). Overlay timings are anchored to t0 = context creation, which
is when Playwright starts the recording.

Usage:  venv/bin/python marketing/record_feature_video.py
"""
import json
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

BASE = "http://127.0.0.1:8777"
EMAIL = "demo.video@example.com"
PASSWORD = "TikTokDemo!2026"
OUT_DIR = Path(__file__).parent / "output"
OUT_DIR.mkdir(exist_ok=True)

# 9:16 phone viewport. Playwright never upscales the recording — a record
# size larger than the viewport just letterboxes into the top-left corner —
# so record at viewport size and upscale to 1080x1920 in the ffmpeg pass.
VIEWPORT = {"width": 405, "height": 720}
RECORD_SIZE = dict(VIEWPORT)

TYPE_DELAY_MS = 85


def main() -> None:
    events = {}
    with sync_playwright() as p:
        browser = p.chromium.launch()
        ctx = browser.new_context(
            viewport=VIEWPORT,
            device_scale_factor=2,
            record_video_dir=str(OUT_DIR),
            record_video_size=RECORD_SIZE,
        )
        t0 = time.monotonic()

        def mark(name):
            events[name] = round(time.monotonic() - t0, 2)
            print(f"  [{events[name]:6.2f}s] {name}")

        page = ctx.new_page()

        # --- login (happens before the trim point; never shown in the cut) ---
        page.goto(f"{BASE}/login")
        page.fill('input[name="email"]', EMAIL)
        page.fill('input[name="password"]', PASSWORD)
        page.click('button[type="submit"]')
        page.wait_for_selector("#msg", timeout=15000)
        mark("chat_ready")
        page.wait_for_timeout(1800)  # let the welcome bubble settle
        mark("cut_start")  # final video starts a beat after this

        # --- segment 1: product lookup ---
        page.wait_for_timeout(700)
        mark("typing1_start")
        page.type("#msg", "Charcoal mask", delay=TYPE_DELAY_MS)
        page.wait_for_timeout(350)
        page.click("#send")
        mark("sent1")
        page.wait_for_selector('#chat :text("Product Look Up")', timeout=15000)
        mark("reply1")
        page.wait_for_timeout(4800)  # reading time on the card

        # --- segment 2: catalog browse ---
        mark("typing2_start")
        page.type("#msg", "What fragrances do we have", delay=TYPE_DELAY_MS)
        page.wait_for_timeout(350)
        page.click("#send")
        mark("sent2")
        # NB: must not match the typed question itself ("What fragrances do we
        # have" contains "fragrance"), so wait on the reply header's count
        page.wait_for_selector('#chat :text("20 products")', timeout=15000)
        mark("reply2")
        page.wait_for_timeout(600)

        # Scroll so the TOP of the fragrance reply is visible, hold, then
        # smooth-scroll down through all 20 products.
        page.evaluate(
            """() => {
                const chat = document.getElementById('chat');
                const bubbles = chat.querySelectorAll(':scope > *');
                const last = bubbles[bubbles.length - 1];
                last.scrollIntoView({block: 'start'});
            }"""
        )
        mark("scroll_top")
        page.wait_for_timeout(1600)
        mark("scroll_down_start")
        # smooth constant-rate scroll to the bottom — the scrolling container
        # is #chatWrap (the section wrapping #chat), not #chat itself
        for _ in range(400):
            done = page.evaluate(
                """() => {
                    const s = document.getElementById('chatWrap');
                    s.scrollBy(0, 6);
                    return s.scrollTop + s.clientHeight >= s.scrollHeight - 2;
                }"""
            )
            if done:
                break
            page.wait_for_timeout(16)
        mark("scroll_done")
        page.wait_for_timeout(2400)  # hold on the end of the list
        mark("end")

        video = page.video
        ctx.close()  # flushes the recording
        path = video.path()
        browser.close()

    final = OUT_DIR / "raw_session.webm"
    Path(path).rename(final)
    (OUT_DIR / "events.json").write_text(json.dumps(events, indent=2))
    print(f"\nsaved: {final}\nevents: {json.dumps(events)}")


if __name__ == "__main__":
    main()
