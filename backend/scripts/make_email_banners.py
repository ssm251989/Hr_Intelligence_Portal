"""Part 22.6: builds the 6 bundled email banner GIFs (+ a static PNG fallback each) into
app/platform/comms/banners/. Original artwork drawn with Pillow -- no third-party images.

    python -m scripts.make_email_banners

Each GIF is 600x180, a short loop, under 300 KB. Colours are neutral-festive so they sit well with any brand.
"""

import math
import random
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

OUT = Path(__file__).resolve().parent.parent / "app" / "platform" / "comms" / "banners"
W, H, FRAMES = 600, 180, 14
PALETTE = [(244, 180, 0), (233, 30, 99), (0, 172, 193), (124, 77, 255), (67, 160, 71), (255, 112, 67), (255, 255, 255)]


def _font(size: int, bold: bool = True):
    for name in ("seguibl.ttf", "arialbd.ttf", "DejaVuSans-Bold.ttf", "Arial Bold.ttf") if bold else ("segoeui.ttf", "arial.ttf", "DejaVuSans.ttf"):
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    return ImageFont.load_default()


def _gradient(top, bottom) -> Image.Image:
    im = Image.new("RGB", (W, H))
    d = ImageDraw.Draw(im)
    for y in range(H):
        t = y / (H - 1)
        d.line([(0, y), (W, y)], fill=tuple(int(top[i] + (bottom[i] - top[i]) * t) for i in range(3)))
    return im


def _title(d: ImageDraw.ImageDraw, text: str, sub: str, colour=(255, 255, 255)):
    f, s = _font(46), _font(20, bold=False)
    tw = d.textlength(text, font=f)
    d.text(((W - tw) / 2 + 2, 52 + 2), text, font=f, fill=(0, 0, 0, 60))
    d.text(((W - tw) / 2, 52), text, font=f, fill=colour)
    sw = d.textlength(sub, font=s)
    d.text(((W - sw) / 2, 112), sub, font=s, fill=colour)


def confetti(name, top, bottom, text, sub, seed=1):
    rnd = random.Random(seed)
    pieces = [(rnd.uniform(0, W), rnd.uniform(-H, H), rnd.uniform(3, 7), rnd.choice(PALETTE[:6]), rnd.uniform(0.8, 1.6), rnd.uniform(0, 6.28)) for _ in range(130)]
    frames = []
    for i in range(FRAMES):
        im = _gradient(top, bottom)
        d = ImageDraw.Draw(im, "RGBA")
        for x, y0, s, c, sp, ph in pieces:
            y = (y0 + i * sp * (H * 2 / FRAMES)) % (H * 2) - H / 2
            xx = x + math.sin(ph + i / 2) * 6
            if int(ph * 10) % 2:
                d.rectangle([xx, y, xx + s, y + s * 0.5], fill=c)
            else:
                d.ellipse([xx, y, xx + s * 0.8, y + s * 0.8], fill=c)
        _title(d, text, sub)
        frames.append(im)
    return name, frames


def fireworks(name, text, sub, seed=2):
    rnd = random.Random(seed)
    bursts = [(rnd.uniform(60, W - 60), rnd.uniform(25, 90), rnd.choice(PALETTE[:6]), rnd.randrange(FRAMES)) for _ in range(6)]
    frames = []
    for i in range(FRAMES):
        im = _gradient((20, 24, 66), (58, 32, 110))
        d = ImageDraw.Draw(im, "RGBA")
        for _ in range(40):
            d.point((rnd.uniform(0, W), rnd.uniform(0, H)), fill=(255, 255, 255, 120))
        for x, y, c, start in bursts:
            age = (i - start) % FRAMES
            r = 4 + age * 4
            alpha = max(0, 255 - age * 22)
            for k in range(14):
                a = k * 2 * math.pi / 14
                d.line([(x + math.cos(a) * r * 0.6, y + math.sin(a) * r * 0.6), (x + math.cos(a) * r, y + math.sin(a) * r)], fill=c + (alpha,), width=2)
        _title(d, text, sub)
        frames.append(im)
    return name, frames


def balloons(name, text, sub, seed=3):
    rnd = random.Random(seed)
    bal = [(rnd.uniform(20, W - 20), rnd.uniform(0, H * 2), rnd.choice(PALETTE[:6]), rnd.uniform(14, 22)) for _ in range(12)]
    frames = []
    for i in range(FRAMES):
        im = _gradient((255, 236, 210), (255, 205, 220))
        d = ImageDraw.Draw(im, "RGBA")
        for x, y0, c, s in bal:
            y = H + 40 - ((y0 + i * (H * 2 / FRAMES)) % (H * 2 + 60))
            d.line([(x, y + s), (x + math.sin(i / 2 + x) * 4, y + s + 28)], fill=(120, 120, 120, 160), width=1)
            d.ellipse([x - s * 0.75, y - s, x + s * 0.75, y + s], fill=c + (220,))
            d.ellipse([x - s * 0.35, y - s * 0.6, x - s * 0.1, y - s * 0.25], fill=(255, 255, 255, 120))
        _title(d, text, sub, colour=(110, 30, 70))
        frames.append(im)
    return name, frames


def sparkle(name, top, bottom, text, sub, seed=4):
    rnd = random.Random(seed)
    stars = [(rnd.uniform(10, W - 10), rnd.uniform(10, H - 10), rnd.uniform(3, 8), rnd.randrange(FRAMES)) for _ in range(30)]
    frames = []
    for i in range(FRAMES):
        im = _gradient(top, bottom)
        d = ImageDraw.Draw(im, "RGBA")
        for x, y, s, ph in stars:
            k = (math.sin((i + ph) / FRAMES * 2 * math.pi) + 1) / 2
            r = s * (0.4 + k)
            a = int(80 + 175 * k)
            d.polygon([(x, y - r), (x + r * 0.25, y - r * 0.25), (x + r, y), (x + r * 0.25, y + r * 0.25), (x, y + r), (x - r * 0.25, y + r * 0.25),
                       (x - r, y), (x - r * 0.25, y - r * 0.25)], fill=(255, 255, 255, a))
        _title(d, text, sub)
        frames.append(im)
    return name, frames


def wave(name, text, sub):
    frames = []
    for i in range(FRAMES):
        im = _gradient((14, 124, 102), (47, 111, 222))
        d = ImageDraw.Draw(im, "RGBA")
        for band, (amp, col) in enumerate(((10, (255, 255, 255, 40)), (14, (255, 255, 255, 28)), (8, (255, 255, 255, 50)))):
            pts = [(x, H - 30 - band * 14 + math.sin(x / 50 + i / FRAMES * 2 * math.pi + band) * amp) for x in range(0, W + 10, 10)]
            d.polygon(pts + [(W, H), (0, H)], fill=col)
        # a waving hand drawn as a simple palm + fingers, rocking
        cx, cy, ang = 34, 70, math.sin(i / FRAMES * 2 * math.pi) * 0.35
        for k in range(4):
            a = -1.2 + k * 0.35 + ang
            d.line([(cx, cy), (cx + math.cos(a) * 22, cy + math.sin(a) * 22)], fill=(255, 214, 102), width=6)
        d.ellipse([cx - 12, cy - 7, cx + 12, cy + 17], fill=(255, 214, 102))
        _title(d, text, sub)
        frames.append(im)
    return name, frames


def save(name, frames):
    OUT.mkdir(parents=True, exist_ok=True)
    pal = [f.convert("P", palette=Image.ADAPTIVE, colors=64) for f in frames]
    pal[0].save(OUT / f"{name}.gif", save_all=True, append_images=pal[1:], duration=90, loop=0, optimize=True, disposal=2)
    frames[len(frames) // 2].save(OUT / f"{name}.png", optimize=True)
    print(name, (OUT / f"{name}.gif").stat().st_size // 1024, "KB gif,", (OUT / f"{name}.png").stat().st_size // 1024, "KB png")


if __name__ == "__main__":
    for n, fr in (
        confetti("confetti", (233, 30, 99), (124, 77, 255), "Congratulations!", "You're selected"),
        fireworks("fireworks", "Congratulations!", "A big moment - well done"),
        balloons("balloons", "Hooray!", "Your offer is here"),
        wave("welcome-wave", "Welcome aboard!", "We're so glad you're joining us"),
        sparkle("welcome-sparkle", (0, 150, 136), (63, 81, 181), "Welcome to the team!", "Your first day is almost here"),
        confetti("welcome-confetti", (255, 152, 0), (233, 30, 99), "Welcome!", "Let's make great things together", seed=9),
    ):
        save(n, fr)
