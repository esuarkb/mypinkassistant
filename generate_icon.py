"""
Run once locally to generate web app icons.
  pip install Pillow
  python generate_icon.py
"""
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

PINK = "#e91e63"
WHITE = (255, 255, 255)
OUT = Path(__file__).parent / "web"

FONT_CANDIDATES = [
    "/System/Library/Fonts/Helvetica.ttc",
    "/System/Library/Fonts/Arial.ttf",
    "/Library/Fonts/Arial Bold.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
]


def find_font(size):
    for path in FONT_CANDIDATES:
        try:
            return ImageFont.truetype(path, size)
        except Exception:
            continue
    return ImageFont.load_default()


def make_icon(px):
    img = Image.new("RGBA", (px, px), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    # Rounded pink background
    radius = px // 5
    draw.rounded_rectangle([0, 0, px - 1, px - 1], radius=radius, fill=PINK)

    # "MPA" centered
    font_size = px // 3
    font = find_font(font_size)
    text = "MPA"

    bbox = draw.textbbox((0, 0), text, font=font)
    tw = bbox[2] - bbox[0]
    th = bbox[3] - bbox[1]
    x = (px - tw) / 2 - bbox[0]
    y = (px - th) / 2 - bbox[1]

    draw.text((x, y), text, fill=WHITE, font=font)
    return img


sizes = {
    "apple-touch-icon.png": 180,
    "icon-192.png": 192,
    "icon-512.png": 512,
}

for filename, px in sizes.items():
    path = OUT / filename
    make_icon(px).save(path)
    print(f"✓ {path}")

print("Done. Commit the files in web/ and deploy.")
