"""
TikTok video builder — ffmpeg pass over marketing/output/raw_session.webm.

Reads events.json (written by record_feature_video.py), trims the login/settle
preamble, upscales 404x720 -> 1080x1920 (lanczos), lays timed text overlays,
and writes h264 yuv420p 30fps with no audio (music gets added in the TikTok
app).

2026-08-16 tweaks (Brian): FEATURE titles moved to the lower third — above
the chat input (top edge y=1655 at 1080x1920), below the responses — and
each auto-hides after 5s (the segment-2 title clears right before the
fragrance scroll starts). Fun font (Marker Felt), a bit larger, same brand
colors. "Every fragrance, one question" sub-banner and the whole end card
(brand/price/site + frozen frame) removed so replays loop naturally.

NO emoji in drawtext — these system fonts have no emoji glyphs. Brand pink
#e91e63 per the email style guide.

Usage:  venv/bin/python marketing/build_tiktok.py
"""
import json
import subprocess
from pathlib import Path

OUT_DIR = Path(__file__).parent / "output"
RAW = OUT_DIR / "raw_session.webm"
FINAL = OUT_DIR / "tiktok_test.mp4"

FONT = "/System/Library/Fonts/MarkerFelt.ttc"
PINK = "0xe91e63"
TITLE_SECS = 5.0   # feature titles auto-hide after this
TITLE_Y = 1500     # lower third: below the responses, above the chat input

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


main_len = round(dur - trim, 2)          # no end card — video ends naturally

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

    # --- segment 1: product lookup (title hides itself after 5s) ---
    banner("FEATURE&#58; PRODUCT LOOKUP".replace("&#58;", "\\:"), 64, TITLE_Y,
           0, min(TITLE_SECS, seg2)),
    banner("Price, Part # + Fact Sheet — instantly", 40, 262,
           t("reply1", 0.4), seg2, box="black@0.85", boxw=14),

    # --- segment 2: catalog browse (5s title clears just before the
    # fragrance scroll reveals the list) ---
    banner("FEATURE&#58; CATALOG BROWSE".replace("&#58;", "\\:"), 64, TITLE_Y,
           seg2, seg2 + TITLE_SECS),

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

print(f"trim={trim:.2f}s  total={main_len:.2f}s")
print(f"saved: {FINAL}")
