"""
TikTok video builder — ffmpeg pass over marketing/output/raw_session.webm.

Reads events.json (written by record_feature_video.py), trims the login/settle
preamble, upscales 404x720 -> 1080x1920 (lanczos), lays timed text overlays in
the TikTok safe zone (top-center; bottom ~20% and right edge are covered by
TikTok's UI), freezes the last frame for an end card, and writes h264 yuv420p
30fps with no audio (music gets added in the TikTok app).

Overlay font is Arial Bold (system) — NO emoji in drawtext, Arial has no
emoji glyphs. Brand pink #e91e63 per the email style guide.

Usage:  venv/bin/python marketing/build_tiktok.py
"""
import json
import subprocess
from pathlib import Path

OUT_DIR = Path(__file__).parent / "output"
RAW = OUT_DIR / "raw_session.webm"
FINAL = OUT_DIR / "tiktok_test.mp4"

FONT = "/System/Library/Fonts/Supplemental/Arial Bold.ttf"
PINK = "0xe91e63"
END_CARD_SECS = 2.6

events = json.loads((OUT_DIR / "events.json").read_text())
dur = float(subprocess.run(
    ["ffprobe", "-v", "error", "-show_entries", "format=duration",
     "-of", "csv=p=0", str(RAW)],
    capture_output=True, text=True, check=True).stdout.strip())

# events were stamped from context creation; the video's first frame lands a
# beat later, so anchor event time to video time via the final mark
offset = events["end"] - dur
trim = max(0.0, events["cut_start"] - offset + 0.1)


def t(name: str, delta: float = 0.0) -> float:
    """Event time on the OUTPUT timeline (post-trim)."""
    return round(events[name] - offset - trim + delta, 2)


main_len = round(dur - trim, 2)          # where the freeze/end card begins
total = round(main_len + END_CARD_SECS, 2)

seg2 = t("typing2_start", -0.15)


def banner(text, size, y, start, end, box=PINK, color="white", boxw=20):
    return (
        f"drawtext=fontfile='{FONT}':text='{text}':fontsize={size}:"
        f"fontcolor={color}:box=1:boxcolor={box}:boxborderw={boxw}:"
        f"x=(w-text_w)/2:y={y}:enable='between(t,{start},{end})'"
    )


filters = [
    f"trim=start={trim}",
    "setpts=PTS-STARTPTS",
    "scale=1080:1920:flags=lanczos",
    "setsar=1",
    "fps=30",
    f"tpad=stop_mode=clone:stop_duration={END_CARD_SECS}",

    # --- segment 1: product lookup ---
    banner("FEATURE&#58; PRODUCT LOOKUP".replace("&#58;", "\\:"), 52, 140, 0, seg2),
    banner("Price, Part # + Fact Sheet — instantly", 40, 262,
           t("reply1", 0.4), seg2, box="black@0.85", boxw=14),

    # --- segment 2: catalog browse ---
    banner("FEATURE&#58; CATALOG BROWSE".replace("&#58;", "\\:"), 52, 140, seg2, main_len),
    # starts as the scroll begins so the "Fragrance — 20 products" header
    # gets a clean beat on screen first
    banner("Every fragrance, one question", 40, 262,
           t("scroll_down_start", -0.3), main_len, box="black@0.85", boxw=14),

    # --- end card: darken the frozen frame, brand + price ---
    f"drawbox=x=0:y=0:w=iw:h=ih:color=black@0.60:t=fill:enable='gte(t,{main_len})'",
    banner("MyPinkAssistant", 88, 760, main_len, total + 1),
    banner("mypinkassistant.com", 54, 950, main_len, total + 1,
           box="black@0.0", color="white", boxw=1),
    banner("$5.99/mo — every feature", 48, 1070, main_len, total + 1,
           box="black@0.0", color="0xffc0d5", boxw=1),

    "format=yuv420p",
]

script = OUT_DIR / "filters.txt"
script.write_text(",\n".join(filters))

subprocess.run(
    ["ffmpeg", "-v", "error", "-y", "-i", str(RAW),
     "-filter_complex_script", str(script),
     "-c:v", "libx264", "-preset", "medium", "-crf", "20",
     "-movflags", "+faststart", "-an", str(FINAL)],
    check=True)

print(f"trim={trim:.2f}s  main={main_len:.2f}s  total={total:.2f}s")
print(f"saved: {FINAL}")
