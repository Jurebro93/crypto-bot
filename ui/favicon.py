"""MemeSonar favicon set (from the logo in ui/html.LOGOS), served at the site root on every host.
Files live in ui/static/icons; HEAD goes into every page's <head>."""
import json
import os

DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static", "icons")
FILES = {
    "/favicon.ico": ("favicon.ico", "image/x-icon"),
    "/favicon.svg": ("favicon.svg", "image/svg+xml"),
    "/apple-touch-icon.png": ("apple-touch-icon.png", "image/png"),
    "/icon-192.png": ("icon-192.png", "image/png"),
    "/icon-512.png": ("icon-512.png", "image/png"),
}
PATHS = tuple(FILES) + ("/site.webmanifest",)
HEAD = ('<link rel=icon href="/favicon.ico" sizes="48x48"><link rel=icon type="image/svg+xml" href="/favicon.svg">'
        '<link rel=apple-touch-icon href="/apple-touch-icon.png"><link rel=manifest href="/site.webmanifest">')


def manifest():
    return json.dumps({
        "name": "MemeSonar", "short_name": "MemeSonar", "start_url": "/", "display": "standalone",
        "background_color": "#ffffff", "theme_color": "#4f46e5",
        "icons": [{"src": "/icon-192.png", "sizes": "192x192", "type": "image/png"},
                  {"src": "/icon-512.png", "sizes": "512x512", "type": "image/png"},
                  {"src": "/icon-512.png", "sizes": "512x512", "type": "image/png", "purpose": "maskable"}]})


def get(path):
    """(body bytes, content type) for a favicon path, else None."""
    if path == "/site.webmanifest":
        return manifest().encode("utf-8"), "application/manifest+json"
    f = FILES.get(path)
    if not f:
        return None
    with open(os.path.join(DIR, f[0]), "rb") as fh:
        return fh.read(), f[1]
