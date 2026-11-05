"""5.11.: /share/novosti.png?d=YYYY-MM-DD: a 1200x675 card with that day's entries of share/novosti.json (what is new
in the app), public, for the evening X post through Buffer. Only product text from novosti.json goes on it: no
settings, keys, addresses, costs or internal state can reach the card because nothing else is read."""
import datetime as dt
import io
import re

W, H = 1200, 675
BG, INK, MUT, ACC = (11, 18, 32), (255, 255, 255), (170, 178, 194), (79, 70, 229)


def entries(day=None):
    """[(naslov, tekst)] for the day (YYYY-MM-DD, default today UTC), newest first."""
    from ui import novo
    day = day or dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d")
    out = []
    for e in novo.items():
        if str(e.get("datum", "")).startswith(day):
            out.append((str(e.get("naslov", "")).strip(), str(e.get("tekst", "")).strip()))
    return out


def _wrap(draw, text, font, width):
    words, lines, cur = text.split(), [], ""
    for w in words:
        t = f"{cur} {w}".strip()
        if draw.textlength(t, font=font) <= width:
            cur = t
        else:
            lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)
    return lines


def png(day=None, max_items=3):
    """PNG bytes of the card; None when Pillow is missing or the day has no entries."""
    try:
        from PIL import Image, ImageDraw, ImageFont
    except ImportError:
        return None
    items = entries(day)[:max_items]
    if not items:
        return None
    day = day or dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d")
    im = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(im)
    big, head, body, small = (ImageFont.load_default(size=s) for s in (54, 34, 26, 22))
    d.rectangle((0, 0, W, 10), fill=ACC)
    d.text((60, 48), "MemeSonar", font=head, fill=INK)
    y, m, dd = day.split("-")
    d.text((W - 60 - d.textlength(f"{int(dd)}.{int(m)}.{y}.", font=small), 56), f"{int(dd)}.{int(m)}.{y}.", font=small, fill=MUT)
    d.text((60, 110), "Što je novo danas", font=big, fill=INK)
    yy = 200
    for title, text in items:
        d.ellipse((60, yy + 12, 74, yy + 26), fill=ACC)
        for ln in _wrap(d, title, head, W - 180)[:2]:
            d.text((96, yy), ln, font=head, fill=INK)
            yy += 42
        for ln in _wrap(d, re.sub(r"\s+", " ", text), body, W - 180)[:2]:
            d.text((96, yy), ln, font=body, fill=MUT)
            yy += 32
        yy += 22
        if yy > H - 120:
            break
    d.text((60, H - 60), "app.memesonar.app", font=small, fill=MUT)
    buf = io.BytesIO()
    im.save(buf, "PNG", optimize=True)
    return buf.getvalue()
