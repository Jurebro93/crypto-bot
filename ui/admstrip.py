"""Remove admin-only parts (class adm-only) from a cached page before it goes to a non-admin.

Pages are cached once for everyone; the adm-only class used to be only hidden with CSS, so a basic user could read
the admin bits (job logs, Sustav menu) in the HTML source (audit 4.11. §4.2). The server now sends non-admins a
copy without them; the admin's copy is unchanged."""
import re

_OPEN = re.compile(r"<([a-zA-Z][a-zA-Z0-9]*)\b[^>]*\badm-only\b[^>]*>")
VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "source", "track", "wbr"}


def strip(html):
    """html without every element whose start tag carries class adm-only (with all it contains)."""
    out, i = [], 0
    while True:
        m = _OPEN.search(html, i)
        if not m:
            out.append(html[i:])
            return "".join(out)
        out.append(html[i:m.start()])
        tag = m.group(1).lower()
        if tag in VOID or m.group(0).endswith("/>"):
            i = m.end()
            continue
        tok = re.compile(rf"<(/?){tag}\b[^>]*>", re.I)
        depth, j = 1, m.end()
        while depth:
            t = tok.search(html, j)
            if not t:                      # unbalanced: drop to the end rather than leak
                return "".join(out)
            depth += -1 if t.group(1) else 1
            j = t.end()
        i = j
