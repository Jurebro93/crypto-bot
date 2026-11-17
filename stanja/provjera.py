"""Literals of a state column as the code really writes and compares them (stdlib re; no import of the scanned code).

found(path, col) reads one source file and returns the set of quoted values that stand next to the column / key name
`col` in SQL text ("status='open'", "status IN ('open','pending')") and in Python ("r["status"] == "open"",
"status in ("a", "b")", {"status": "ok"}). drift() compares that with what stanja/registar.py declares: a literal the
registry does not know is a NEW implicit state (somebody added it without declaring it); a declared state that no
scanned file mentions any more is a dead one. tests/test_stanja_offline.py fails on either, which is the whole point:
the registry cannot go stale silently.
"""
import os
import re

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_Q = r"""(?:'([^'\n%{}]{1,40})'|"([^"\n%{}]{1,40})")"""
_ITEM = re.compile(_Q)
_SRC = {}


def _text(path):
    full = path if os.path.isabs(path) else os.path.join(ROOT, path)
    if full not in _SRC:
        with open(full, encoding="utf-8") as f:
            _SRC[full] = f.read()
    return _SRC[full]


def _patterns(col):
    c = re.escape(col)
    key = rf"""(?:\[\s*["']{c}["']\s*\]|\.get\(\s*["']{c}["']\s*\)|\b{c}\b)"""
    return (
        re.compile(rf"{key}\s*(?:==|!=|<>|=)\s*{_Q}"),                           # status = 'open' / r["status"] == "open"
        re.compile(rf"{key}\s+(?:NOT\s+|not\s+)?(?:IN|in)\s*[\(\[\{{]([^\)\]\}}]*)[\)\]\}}]"),   # status IN ('a','b')
        re.compile(rf"""["']{c}["']\s*:\s*{_Q}"""),                              # {"status": "ok"}
        re.compile(rf"\bSET\s+{c}\s*=\s*{_Q}"),
    )


def found(path, col):
    """{literal} written or compared for `col` in the file."""
    out = set()
    src = _text(path)
    for i, rx in enumerate(_patterns(col)):
        for m in rx.finditer(src):
            if i == 1:
                out.update(a or b for a, b in _ITEM.findall(m.group(1)))
            else:
                out.add(m.group(1) or m.group(2))
    return {x.strip() for x in out if x and re.search(r"[A-Za-zčćšžđ]", x)}


def mentions(path, literal):
    src = _text(path)
    return f"'{literal}'" in src or f'"{literal}"' in src


def drift(machines):
    """[(machine key, kind, literal, file)]: kind "nedeklarirano" (in the code, not in the registry) or "mrtvo" (declared,
    in no scanned file). Machines that share a (file, column) are checked against the union of their states."""
    union = {}
    for m in machines:
        for path, col in m.scan:
            union.setdefault((path, col), set()).update(m.states, m.extra)
    out = []
    for m in machines:
        for path, col in m.scan:
            for lit in sorted(found(path, col) - union[(path, col)]):
                out.append((m.key, "nedeklarirano", lit, path))
        if m.scan:
            for lit in m.states:
                files = [p for p, _c in m.scan] + list(m.also)
                if not any(mentions(p, lit) for p in files):
                    out.append((m.key, "mrtvo", lit, ", ".join(files)))
    return sorted(set(out))
