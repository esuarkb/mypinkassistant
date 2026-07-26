"""Trace the chosen MPA mark into vector, then emit the full production set.

TWO MARKS, one family (Brian's call, 2026-07-25):
  * lone M  -> browser tab favicon (.svg + .ico). Three letters are illegible
               at 16px; a single M holds.
  * MPA     -> app icons (PWA 192/512, apple-touch 180, App Store 1024).
Both are cut from the same traced outlines, so they are the same letterform.

Why trace instead of re-setting in a font: the mark is a condensed grotesque
matching no installed face exactly (best IoU 0.93, SF Pro Bold — which Apple's
licence forbids in a logo anyway). Tracing is exact and carries no licence.
The only source is 512px, so deriving everything from vector keeps the 1024
App Store icon genuinely crisp rather than interpolated.

Design: -2 stroke weight, subtly rounded corners, gradient field + light sweep.
"""
import os, math, sys
from PIL import Image, ImageDraw, ImageFilter, ImageChops, ImageFont

ROOT = "/Users/desktop/Documents/Brian's Folder/Python Projects/MK Automation"
OUT = os.path.join(ROOT, "brand", "out")
os.makedirs(OUT, exist_ok=True)
sys.setrecursionlimit(20000)

SS, S = 4, 512
BIG = S * SS
TRACE_RES = 1024
GRAD = ((246, 74, 130), (198, 20, 84))
RX = 14 / 64          # corner radius as a fraction of the side

# ---------------------------------------------------------------- source mask
# The ORIGINAL 2026-07-05 artwork, kept here on purpose: web/icon-512.png is
# now this script's own output, so tracing that would trace the trace.
src = Image.open(os.path.join(ROOT, "brand/source-original-512.png")).convert("RGBA")
_, g, _, a = src.split()
cov = Image.eval(g, lambda v: max(0, min(255, int((v - 30) * 255 / 225))))
cov = ImageChops.multiply(cov, Image.eval(a, lambda v: 255 if v > 128 else 0))
LET = cov.resize((BIG, BIG), Image.LANCZOS)


def _shift(im, dx, dy):
    return im.transform(im.size, Image.AFFINE, (1, 0, -dx, 0, 1, -dy),
                        resample=Image.NEAREST, fillcolor=0)


def erode_disc(mask, r):
    m = mask
    for i in range(int(round(r))):
        if i % 2 == 0:
            m = m.filter(ImageFilter.MinFilter(3))
        else:
            d = m
            for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                d = ImageChops.darker(d, _shift(m, dx, dy))
            m = d
    return m


letters = LET.filter(ImageFilter.GaussianBlur(4 * SS * 0.62)).point(
    lambda v: 255 if v >= 128 else 0)
letters = erode_disc(letters, 3.0 * SS)

# lone M: the M occupies x 65..211 at 512 (verified by column profile)
m_only = letters.copy()
ImageDraw.Draw(m_only).rectangle([220 * SS, 0, BIG, BIG], fill=0)
bb = m_only.getbbox()
ink = m_only.crop(bb)
TARGET_H = int(0.47 * S * SS)                       # cap height 47% of the tile
nw = max(1, int(ink.width * TARGET_H / ink.height))
ink = ink.resize((nw, TARGET_H), Image.LANCZOS).point(lambda v: 255 if v >= 128 else 0)
m_mark = Image.new("L", (BIG, BIG), 0)
m_mark.paste(ink, ((BIG - nw) // 2, (BIG - TARGET_H) // 2))

# ------------------------------------------------------------ marching squares
SEG = {
    1:  [((.5, 1), (0, .5))],      2:  [((1, .5), (.5, 1))],
    3:  [((1, .5), (0, .5))],      4:  [((.5, 0), (1, .5))],
    5:  [((.5, 0), (0, .5)), ((.5, 1), (1, .5))],
    6:  [((.5, 0), (.5, 1))],      7:  [((.5, 0), (0, .5))],
    8:  [((0, .5), (.5, 0))],      9:  [((.5, 1), (.5, 0))],
    10: [((0, .5), (.5, 1)), ((1, .5), (.5, 0))],
    11: [((1, .5), (.5, 0))],      12: [((0, .5), (1, .5))],
    13: [((.5, 1), (1, .5))],      14: [((0, .5), (.5, 1))],
}


def trace(mask, res=TRACE_RES):
    m = mask.resize((res, res), Image.LANCZOS).point(lambda v: 255 if v >= 128 else 0)
    W = H = res + 2
    grid = Image.new("L", (W, H), 0)
    grid.paste(m, (1, 1))
    px = grid.load()
    nxt = {}
    for i in range(H - 1):
        for j in range(W - 1):
            code = ((1 if px[j, i] else 0) * 8 + (1 if px[j + 1, i] else 0) * 4 +
                    (1 if px[j + 1, i + 1] else 0) * 2 + (1 if px[j, i + 1] else 0))
            if code in (0, 15):
                continue
            for (ax, ay), (bx, by) in SEG[code]:
                nxt.setdefault((j + ax, i + ay), []).append((j + bx, i + by))
    loops = []
    for start in list(nxt.keys()):
        while nxt.get(start):
            loop, cur = [start], start
            while True:
                opts = nxt.get(cur)
                if not opts:
                    break
                nx = opts.pop()
                if not opts:
                    nxt.pop(cur, None)
                loop.append(nx)
                cur = nx
                if cur == start:
                    break
            if len(loop) > 8:
                loops.append(loop)
    return loops


def rdp(pts, eps):
    if len(pts) < 3:
        return pts
    ax, ay = pts[0]; bx, by = pts[-1]
    dx, dy = bx - ax, by - ay
    n = math.hypot(dx, dy)
    imax, dmax = 0, -1
    for i in range(1, len(pts) - 1):
        x, y = pts[i]
        d = (abs(dy * x - dx * y + bx * ay - by * ax) / n) if n else math.hypot(x - ax, y - ay)
        if d > dmax:
            imax, dmax = i, d
    if dmax > eps:
        return rdp(pts[:imax + 1], eps)[:-1] + rdp(pts[imax:], eps)
    return [pts[0], pts[-1]]


def vectorize(mask, eps=0.55):
    loops = trace(mask)
    k = S / TRACE_RES
    out = []
    for lp in loops:
        simp = rdp(lp, eps)
        if len(simp) >= 4:
            out.append([((x - 1) * k, (y - 1) * k) for x, y in simp])
    return out


PATHS_MPA = vectorize(letters)
PATHS_M = vectorize(m_mark)
print(f"MPA: {len(PATHS_MPA)} contours, {sum(len(p) for p in PATHS_MPA)} points")
print(f"M  : {len(PATHS_M)} contours, {sum(len(p) for p in PATHS_M)} points")


# --------------------------------------------------------------- SVG assembly
def path_d(pts):
    d = f"M{pts[0][0]:.2f} {pts[0][1]:.2f}"
    for x, y in pts[1:]:
        d += f"L{x:.2f} {y:.2f}"
    return d + "Z"


def svg(paths, note):
    d = " ".join(path_d(p) for p in paths)
    return f'''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 512 512" width="512" height="512">
  <!-- MyPinkAssistant — {note}
       Letterforms traced from the original artwork: no font dependency and no
       font licence. Chosen 2026-07-25: -2 stroke weight, subtly rounded
       corners, gradient field with a light sweep. -->
  <defs>
    <linearGradient id="mpaField" x1="0" y1="0" x2="1" y2="1">
      <stop offset="0" stop-color="#f64a82"/>
      <stop offset="1" stop-color="#c61454"/>
    </linearGradient>
    <radialGradient id="mpaSweep" cx="0.28" cy="-0.15" r="0.95">
      <stop offset="0" stop-color="#ffffff" stop-opacity="0.30"/>
      <stop offset="0.55" stop-color="#ffffff" stop-opacity="0.10"/>
      <stop offset="1" stop-color="#ffffff" stop-opacity="0"/>
    </radialGradient>
    <clipPath id="mpaClip"><rect width="512" height="512" rx="{RX * 512:.0f}"/></clipPath>
  </defs>
  <g clip-path="url(#mpaClip)">
    <rect width="512" height="512" fill="url(#mpaField)"/>
    <rect width="512" height="512" fill="url(#mpaSweep)"/>
    <path fill="#ffffff" fill-rule="evenodd" d="{d}"/>
  </g>
</svg>
'''


open(os.path.join(OUT, "icon.svg"), "w").write(
    svg(PATHS_M, "browser-tab mark (lone M — three letters are illegible at 16px)"))
open(os.path.join(OUT, "icon-app.svg"), "w").write(
    svg(PATHS_MPA, "app mark (MPA)"))
print("wrote icon.svg (M) and icon-app.svg (MPA)")


# ------------------------------------------------------- raster from the paths
def render(paths, size, full_bleed=False, supersample=4):
    n = size * supersample
    field = Image.new("RGB", (n, n))
    d = ImageDraw.Draw(field)
    for i in range(n * 2):
        t = i / (n * 2 - 1)
        d.line([(i, 0), (i - n, n)],
               fill=tuple(int(GRAD[0][j] + (GRAD[1][j] - GRAD[0][j]) * t) for j in range(3)),
               width=2)
    gl = Image.new("L", (n, n), 0)
    ImageDraw.Draw(gl).ellipse([-n * .5, -n * .85, n * 1.05, n * .55], fill=52)
    gl = gl.filter(ImageFilter.GaussianBlur(n * 0.05))
    field = Image.blend(field, Image.composite(
        Image.new("RGB", (n, n), (255, 255, 255)), field, gl), 0.55)

    lm = Image.new("L", (n, n), 0)
    k = n / 512
    for p in paths:                        # evenodd via XOR of each closed loop
        layer = Image.new("L", (n, n), 0)
        ImageDraw.Draw(layer).polygon([(x * k, y * k) for x, y in p], fill=255)
        # XOR on 0/255 masks == absolute difference; gives the even-odd rule
        lm = ImageChops.difference(lm, layer)
    icon = Image.new("RGBA", (n, n), (0, 0, 0, 0))
    if full_bleed:
        icon.paste(field, (0, 0))
    else:
        tm = Image.new("L", (n, n), 0)
        ImageDraw.Draw(tm).rounded_rectangle([0, 0, n - 1, n - 1],
                                             radius=int(n * RX), fill=255)
        icon.paste(field, (0, 0), tm)
        lm = ImageChops.multiply(lm, tm)
    icon.paste((255, 255, 255), (0, 0), lm)
    out = icon.resize((size, size), Image.LANCZOS)
    return out.convert("RGB") if full_bleed else out


for name, size, fb in [("icon-512.png", 512, False), ("icon-192.png", 192, False),
                       ("apple-touch-icon.png", 180, False),
                       ("icon-1024-ios.png", 1024, True)]:
    render(PATHS_MPA, size, full_bleed=fb).save(os.path.join(OUT, name))
    print("wrote", name, f"({size}px{', full-bleed square for App Store' if fb else ''})")

render(PATHS_M, 256).save(os.path.join(OUT, "favicon.ico"),
                          sizes=[(16, 16), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
print("wrote favicon.ico (lone M, multi-size 16-256)")


def badge(paths, size, pad=0.08, supersample=4):
    """Notification badge: glyph alone on transparency, cropped and centred.

    Android renders a badge from the ALPHA CHANNEL only — colour is discarded.
    A full tile (M or MPA) is opaque edge to edge, so it flattens to a solid
    blob. Only the letter may be opaque, and it must be cropped tight: the
    badge slot is ~24dp, so tile padding would shrink the glyph to nothing.
    """
    n = size * supersample
    lm = Image.new("L", (n, n), 0)
    k = n / 512
    for p in paths:                        # evenodd, same as render()
        layer = Image.new("L", (n, n), 0)
        ImageDraw.Draw(layer).polygon([(x * k, y * k) for x, y in p], fill=255)
        lm = ImageChops.difference(lm, layer)

    lm = lm.crop(lm.getbbox())
    inner = int(n * (1 - 2 * pad))
    w, h = lm.size
    s = inner / max(w, h)
    lm = lm.resize((max(1, int(w * s)), max(1, int(h * s))), Image.LANCZOS)
    canvas = Image.new("L", (n, n), 0)
    canvas.paste(lm, ((n - lm.size[0]) // 2, (n - lm.size[1]) // 2))

    out = Image.new("RGBA", (n, n), (255, 255, 255, 0))
    out.putalpha(canvas)
    return out.resize((size, size), Image.LANCZOS)


badge(PATHS_M, 96).save(os.path.join(OUT, "badge-96.png"))
print("wrote badge-96.png (lone M, transparent — Android monochrome badge)")

# ------------------------------------------------------------------ proof sheet
old_icon = Image.open(os.path.join(ROOT, "web/icon-512.png")).convert("RGBA")
new_mpa = render(PATHS_MPA, 512)
new_m = render(PATHS_M, 512)

W, H = 1180, 860
sheet = Image.new("RGB", (W, H), (247, 247, 249))
sd = ImageDraw.Draw(sheet)
h1 = ImageFont.truetype("/System/Library/Fonts/Helvetica.ttc", 32, index=1)
h2 = ImageFont.truetype("/System/Library/Fonts/Helvetica.ttc", 19, index=1)
bd = ImageFont.truetype("/System/Library/Fonts/Helvetica.ttc", 15)
sm = ImageFont.truetype("/System/Library/Fonts/Helvetica.ttc", 13)

sd.text((40, 30), "Production set — vector traced", font=h1, fill=(28, 28, 32))
sd.text((40, 72), "Two marks, one family: MPA for app icons, lone M for browser tabs.",
        font=bd, fill=(118, 118, 128))

for i, (lab, im) in enumerate((("Current (shipped)", old_icon),
                               ("New — app icon", new_mpa),
                               ("New — tab favicon", new_m))):
    x = 40 + i * 380
    sd.text((x, 112), lab, font=h2, fill=(28, 28, 32))
    big = im.resize((300, 300), Image.LANCZOS)
    sheet.paste(big, (x, 142), big)

sd.text((40, 480), "At tab size — why the M wins", font=h2, fill=(28, 28, 32))
sd.text((40, 508), "Each icon shown at 32px and 16px, then magnified 4x so you can see what the browser actually renders.",
        font=bd, fill=(118, 118, 128))
row = [("MPA @32", new_mpa, 32), ("MPA @16", new_mpa, 16),
       ("M @32", new_m, 32), ("M @16", new_m, 16)]
for i, (lab, im, s) in enumerate(row):
    x = 40 + i * 260
    tiny = im.resize((s, s), Image.LANCZOS)
    sheet.paste(tiny, (x, 560), tiny)
    mag = tiny.resize((s * 4, s * 4), Image.NEAREST)
    sheet.paste(mag, (x + 60, 560), mag)
    sd.text((x, 560 + 140), lab, font=sm, fill=(90, 90, 100))
sheet.save(os.path.join(OUT, "before_after.png"), quality=95)
print("wrote before_after.png")
print("\nAll files in:", OUT)
