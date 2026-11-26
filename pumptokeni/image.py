"""Slika tokena: izvorna jednostavna grafika u Pillowu (512×512 PNG). Boje iz hash-a imena, nekoliko geometrijskih
oblika i veliki simbol kao tekst; bez tuđih likova i logotipa. Deterministički: isto ime i simbol = isti bajtovi
(ista verzija Pillowa). normalize(): vlasnikova slika prerađena u 512×512 PNG (bez EXIF-a i ostalih metapodataka).
"""
import colorsys
import hashlib
import io
import os
import re

SIZE = 512
MAX_UPLOAD = 4 * 1024 * 1024
# 26.11. (vlasnik): slike sjemena iz datoteka pumptokeni/slike/<SIMBOL>.png (store.seed_image); ostalo generator
SLIKE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "slike")
_SYM = re.compile(r"^[A-Z0-9]{2,10}$")


def file_bytes(symbol, d=None):
    """Sirovi bajtovi pumptokeni/slike/<SIMBOL>.png ili None (simbol samo 2-10 velikih slova/brojki: bez putanja)."""
    sym = (symbol or "").strip().upper()
    if not _SYM.match(sym):
        return None
    p = os.path.join(d or SLIKE_DIR, sym + ".png")
    try:
        if os.path.getsize(p) > MAX_UPLOAD:
            return None
        with open(p, "rb") as f:
            return f.read()
    except OSError:
        return None


def from_file(symbol, d=None):
    """Slika iz datoteke prerađena kao vlasnikova (512×512 PNG bez metapodataka) ili None."""
    raw = file_bytes(symbol, d)
    if not raw:
        return None
    try:
        return normalize(raw)
    except ValueError:
        return None


def _rng(name, symbol):
    h = hashlib.sha256(f"{name}\x00{symbol}".encode("utf-8")).digest()
    i = [0]

    def nxt(n=1):
        v = int.from_bytes(h[i[0] % 32:i[0] % 32 + 2] or b"\x00", "big")
        i[0] += 2
        return v % n if n > 1 else v / 65535
    return nxt


def _rgb(hue, s, v):
    r, g, b = colorsys.hsv_to_rgb(hue % 1.0, s, v)
    return int(r * 255), int(g * 255), int(b * 255)


def _font(size):
    from PIL import ImageFont
    try:
        return ImageFont.load_default(size=size)
    except TypeError:   # Pillow < 10.1: no sized default font
        return ImageFont.load_default()


def generate(name, symbol):
    from PIL import Image, ImageDraw
    r = _rng(name or "", symbol or "")
    hue = r()
    bg = _rgb(hue, 0.55, 0.95)
    fg = _rgb(hue + 0.5, 0.75, 0.35)
    acc = [_rgb(hue + 0.12 * (k + 1), 0.6, 0.85) for k in range(4)]
    im = Image.new("RGB", (SIZE, SIZE), bg)
    d = ImageDraw.Draw(im)
    for k in range(7):   # shapes: circles, squares, triangles, positions and sizes from the hash
        kind, c = r(3), acc[r(4)]
        x, y, s = r(SIZE), r(SIZE), 40 + r(140)
        if kind == 0:
            d.ellipse((x - s, y - s, x + s, y + s), fill=c)
        elif kind == 1:
            d.rectangle((x - s, y - s, x + s, y + s), fill=c)
        else:
            d.polygon([(x, y - s), (x + s, y + s), (x - s, y + s)], fill=c)
    d.ellipse((56, 56, SIZE - 56, SIZE - 56), fill=(255, 255, 255))   # a plain disc so the symbol always reads
    text = (symbol or "?").upper()[:8]
    fs = 200
    font = _font(fs)
    while fs > 24:
        box = d.textbbox((0, 0), text, font=font)
        if box[2] - box[0] <= 330 and box[3] - box[1] <= 220:
            break
        fs -= 8
        font = _font(fs)
    box = d.textbbox((0, 0), text, font=font)
    w, h = box[2] - box[0], box[3] - box[1]
    d.text(((SIZE - w) / 2 - box[0], (SIZE - h) / 2 - box[1]), text, font=font, fill=fg)
    out = io.BytesIO()
    im.save(out, "PNG", optimize=False)
    return out.getvalue()


def normalize(raw):
    """Vlasnikova slika (bilo koji format koji Pillow čita) → 512×512 PNG (izrezana na kvadrat po sredini).
    ValueError kad nije slika ili je prevelika."""
    from PIL import Image, UnidentifiedImageError
    if not raw or len(raw) > MAX_UPLOAD:
        raise ValueError("slika je prazna ili veća od 4 MB")
    try:
        im = Image.open(io.BytesIO(raw))
        im.load()
    except (UnidentifiedImageError, OSError) as e:
        raise ValueError(f"nije čitljiva slika ({type(e).__name__})")
    im = im.convert("RGBA")
    w, h = im.size
    s = min(w, h)
    im = im.crop(((w - s) // 2, (h - s) // 2, (w - s) // 2 + s, (h - s) // 2 + s)).resize((SIZE, SIZE))
    out = io.BytesIO()
    im.save(out, "PNG")
    return out.getvalue()


def is_png_512(raw):
    from PIL import Image
    try:
        im = Image.open(io.BytesIO(raw))
        return im.format == "PNG" and im.size == (SIZE, SIZE)
    except Exception:  # noqa: BLE001
        return False
