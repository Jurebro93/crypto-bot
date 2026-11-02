"""Hand the finished report to a sender outside the server: the HTML is shrunk (repeated inline styles become
classes in one <style>, which Gmail keeps), gzip+base64 encoded and printed as numbered log lines

    REPORT-B64 2026-11-02 1/4 H4sIA...

A daily Claude routine reads these lines from the Render log, decodes them and sends the e-mail from the Gmail
account connected to Claude (Nicholas does not want SMTP credentials on the server). Decode:
    "".join(chunks) -> base64 -> gunzip -> HTML
"""
import base64
import collections
import gzip
import re

CHUNK = 3000


def compact(html):
    styles = collections.Counter(re.findall(r'style="([^"]*)"', html))
    cls = {s: f"c{i}" for i, (s, n) in enumerate(styles.most_common()) if n >= 2 and len(s) > 12}
    out = re.sub(r'style="([^"]*)"', lambda m: f'class="{cls[m.group(1)]}"' if m.group(1) in cls else m.group(0), html)
    css = "".join(f".{c}{{{s}}}" for s, c in cls.items())
    out = out.replace("</title></head>", f"</title><style>{css}</style></head>", 1)
    return re.sub(r">\s+<", "><", out)


def encode(html):
    return base64.b64encode(gzip.compress(compact(html).encode("utf-8"), 9)).decode("ascii")


def decode(b64):
    return gzip.decompress(base64.b64decode(b64)).decode("utf-8")


def lines(day, html):
    b = encode(html)
    parts = [b[i:i + CHUNK] for i in range(0, len(b), CHUNK)] or [""]
    return [f"REPORT-B64 {day} {i + 1}/{len(parts)} {p}" for i, p in enumerate(parts)]


def emit(day, html):
    for ln in lines(day, html):
        print(ln, flush=True)
