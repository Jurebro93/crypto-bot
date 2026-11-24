"""English version of the dashboard: the pages are written in Croatian and translated on the way out.

How it works
  * The language is a cookie (cb_lang=en), also stored in the player's ⚙️ Postavke so it follows him to a new device.
  * translate(html) walks the finished page. Text is cut into *segments*: a run of text with simple formatting tags
    (<b>, <i>, <br>, …) between block elements. A link or a span inside a sentence becomes a placeholder <n/> and
    its own text is a segment of its own, so "Kupi <a>BONK</a> sada" is looked up as "Kupi <1/> sada". Numbers
    become {0}, {1}, … so "prije 7 min" and "prije 12 min" are one entry. Attributes people read (title,
    placeholder, aria-label, data-tip, alt) are translated too. Scripts, styles, <pre>, <textarea>, <svg> and
    anything marked translate=no are left alone.
  * Lookup: ui/i18n_en.json (checked in, written by hand for the menu, settings and the most used pages) wins over
    DATA_DIR/i18n/en.json (filled automatically). A segment that is in neither stays Croatian for now and is queued;
    a background thread translates the queue with the Claude API (ANTHROPIC_API_KEY, model I18N_MODEL) in batches
    and stores the result, so the next view is English. I18N_DAILY_MAX caps how many segments a day are sent.
  * ui/i18n_seed.json lists the segments of every page seen when this was built, so right after a deploy the whole
    app is translated in the background before anybody asks for it.
  * 13.11. (Jure: the token page "bude na engleskom, a tekst je i sav kontent na hrvatskom"): the first English view
    of a page with new segments was Croatian, because every token's sentences were new keys (its symbol, its wallets,
    its list of reasons) and the English copy of the page was cached for 45 s. Now
      - the page's names (text marked translate=no: the token symbol in the h1, handles) and short addresses
        (7xKX…9fGh) become {n} like numbers, so "Kupi BONK" and "Kupi WIF" are one entry;
      - a segment missing as a whole is looked up sentence by sentence (". ", "; ", ": " where no tag or bracket is
        open), so a paragraph of four measured facts reuses four entries instead of needing one per combination;
        only the missing sentences are queued;
      - translate(page, wait=s) sends the page's missing segments at once (in parallel batches) and waits up to `wait`
        seconds (I18N_SYNC_S, run_ui: full pages only, never the 1-s fragments), then walks the page again; what
        arrives later is stored for the next view. last_missing() tells run_ui not to cache a partial English copy.
Croatian stays the default and costs nothing: with lang 'hr' nothing here runs.
"""
import contextvars
import json
import os
import re
import threading
import time

HERE = os.path.dirname(os.path.abspath(__file__))
LANG = contextvars.ContextVar("lang", default="hr")
COOKIE = "cb_lang"
MODEL = os.environ.get("I18N_MODEL", "claude-opus-5-5")
DAILY_MAX = int(os.environ.get("I18N_DAILY_MAX", "6000"))
BATCH = 60
SYNC_S = float(os.environ.get("I18N_SYNC_S", "4"))        # how long a visitor's first English view waits for new text
SYNC_MAX = int(os.environ.get("I18N_SYNC_MAX", "60"))     # segments sent while a visitor waits (the rest: the queue)
SYNC_CHUNK = 12                                           # per parallel request: small batches answer within seconds
SYNC_PARALLEL = 4

FORMAT = {"b", "strong", "i", "em", "small", "u", "s", "mark", "sup", "sub", "br", "wbr"}
OPAQUE = {"a", "span", "code", "kbd", "abbr", "img", "time", "q", "cite", "bdi", "var", "data"}
SKIP = {"script", "style", "pre", "textarea", "svg", "code", "noscript"}
VOID = {"br", "wbr", "img", "input", "hr", "meta", "link", "source", "area", "col", "embed", "param", "track"}
ATTRS = ("title", "placeholder", "aria-label", "data-tip", "alt", "data-ready", "data-bad", "data-big")

_TOK = re.compile(r"<!--.*?-->|<![^>]*>|<(/?)([a-zA-Z][a-zA-Z0-9\-]*)((?:[^>\"']|\"[^\"]*\"|'[^']*')*)>|[^<]+|<", re.S)
_ATTR = re.compile(r"""(\s(?:%s)\s*=\s*)("([^"]*)"|'([^']*)')""" % "|".join(ATTRS))
# numbers, Solana addresses and shortened ones (7xKX…9fGh, ui/html.short)
_NUM = re.compile(r"[1-9A-HJ-NP-Za-km-z]{30,}|[1-9A-HJ-NP-Za-km-z]{1,8}…[1-9A-HJ-NP-Za-km-z]{1,8}|\d+(?:[.,:]\d+)*")
_WORD = re.compile(r"[A-Za-zČčĆćŠšŽžĐđ]{2,}")
_ADDR = re.compile(r"^[1-9A-HJ-NP-Za-km-z]{25,}$|^https?://|^[\w.\-]+\.(com|io|fun|xyz|net|org)\b")
_PH = re.compile(r"</?\d+/?>|\{\d+\}")
_NOTR = re.compile(r"<([a-zA-Z][a-zA-Z0-9]*)\b[^>]*\stranslate\s*=\s*[\"']?no\b[^>]*>([^<>]{2,40})</\1\s*>")
_NAMES = contextvars.ContextVar("i18n_names", default=None)      # this page's names as one regex (or None)
_COLLECT = contextvars.ContextVar("i18n_collect", default=None)  # keys missing in the translate() running now
_LAST = contextvars.ContextVar("i18n_last", default=0)           # missing segments of the last translate()


def lang():
    return LANG.get()


def is_en():
    return LANG.get() == "en"


# --- dictionaries -----------------------------------------------------------------------------------------------

def _auto_path():
    d = os.path.join(os.environ.get("DATA_DIR") or os.path.dirname(HERE), "i18n")
    return os.path.join(d, "en.json")


_lock = threading.Lock()
_static = None
_auto = None
_pending = {}          # key -> first seen
_failed = {}           # key -> failures (2 = give up)


def _load():
    global _static, _auto
    if _static is None:
        try:
            with open(os.path.join(HERE, "i18n_en.json"), encoding="utf-8") as f:
                _static = json.load(f)
        except (OSError, ValueError):
            _static = {}
    if _auto is None:
        try:
            with open(_auto_path(), encoding="utf-8") as f:
                _auto = json.load(f)
        except (OSError, ValueError):
            _auto = {}
    return _static, _auto


def lookup(key):
    st, au = _load()
    v = st.get(key)
    if v is None:
        v = au.get(key)
    return v


def t(text):
    """One plain string (a menu name, a JS label) in the current language."""
    if not is_en() or not text:
        return text
    key, nums, v = _find(text)
    if not key:
        return text
    if v is None:
        _queue(key)
        return text
    return _fill(v, nums) or text


def _template(text, names=None):
    nums = []

    def sub(m):
        nums.append(m.group(0))
        return "{%d}" % (len(nums) - 1)
    rx = names or _NUM
    key = "".join(part if re.fullmatch(r"</?\d+/?>", part) else rx.sub(sub, part)
                  for part in re.split(r"(</?\d+/?>)", " ".join(text.split())))
    if not wants(key):
        return None, nums
    return key, nums


def _find(text):
    """(key, values, translation or None): the plain key first (numbers and addresses as {n}), then, when this page
    has names, the key with the names as {n} too. A miss returns the most general key (the one worth queueing)."""
    key, nums = _template(text)
    v = lookup(key) if key else None
    names = _NAMES.get()
    if v is None and names is not None:
        k2, n2 = _template(text, names)
        if k2 and k2 != key:
            key, nums, v = k2, n2, lookup(k2)
    return key, nums, v


def _names_rx(page):
    """One regex for this page's names (the text of short translate=no elements) and the numbers/addresses, or None."""
    names = set()
    for m in _NOTR.finditer(page):
        n = m.group(2).strip()
        if 2 <= len(n) <= 40 and _WORD.search(n) and "{" not in n:
            names.add(n)
        if len(names) >= 60:
            break
    if not names:
        return None
    alt = "|".join(re.escape(n) for n in sorted(names, key=len, reverse=True))
    return re.compile(r"(?<!\w)(?:%s)(?!\w)|%s" % (alt, _NUM.pattern))


def wants(key):
    """Worth translating: has words, is not an address, a link or a lone ticker."""
    bare = _PH.sub(" ", key).strip()
    if not _WORD.search(bare) or _ADDR.search(bare) or len(key) > 3000:
        return False
    if " " not in key.strip() and ("{" in key or key.startswith("$")):   # a ticker like $BONK or W{0}F
        return False
    return True


def _fill(v, nums):
    try:
        return re.sub(r"\{(\d+)\}", lambda m: nums[int(m.group(1))], v)
    except IndexError:
        return None


def _queue(key, label=False):
    # one word on its own (a token or a player name, mostly) is never sent: the menu words are in the dictionaries
    if " " not in _PH.sub("", key).strip() and not label:
        return
    if _failed.get(key, 0) >= 2:
        return
    coll = _COLLECT.get()
    if coll is not None and key not in coll:
        coll.append(key)
    if key in _pending or len(_pending) > 20000:
        return
    with _lock:
        _pending.setdefault(key, time.time())
    _start_worker()


# --- the page walk ----------------------------------------------------------------------------------------------

def _attr_sub(tag):
    def sub(m):
        q = '"' if m.group(3) is not None else "'"
        raw = m.group(3) if m.group(3) is not None else m.group(4)
        import html as h
        val = h.unescape(raw)
        new = t(val)
        if new == val:
            return m.group(0)
        return f"{m.group(1)}{q}{h.escape(new, quote=True)}{q}"
    return _ATTR.sub(sub, tag)


def translate(page, wait=0.0, call=None):
    """The page in English as far as the dictionaries go; unknown segments are queued for translation. wait > 0 (a
    whole page a visitor is waiting for): the missing segments are sent at once and the page is walked again with
    whatever arrived within `wait` seconds. last_missing() then says how many are still Croatian."""
    if not page or not is_en():
        _LAST.set(0)
        return page
    names = _NAMES.set(_names_rx(page))
    try:
        coll = []
        tok = _COLLECT.set(coll)
        try:
            out = _walk(page)
        finally:
            _COLLECT.reset(tok)
        if coll and wait > 0 and (call or _can_call()):
            if translate_now(coll, wait, call):
                coll = []
                tok = _COLLECT.set(coll)
                try:
                    out = _walk(page)
                finally:
                    _COLLECT.reset(tok)
        _LAST.set(len(coll) if _day_left() > 0 else 0)   # over the daily cap nothing more will come today
        return out
    finally:
        _NAMES.reset(names)


def last_missing():
    """Segments the last translate() in this context left Croatian (0 = the page is fully English, cache it)."""
    return _LAST.get()


def _walk(page):
    toks = [m.group(0) for m in _TOK.finditer(page)]
    kinds = []
    for m in _TOK.finditer(page):
        s = m.group(0)
        if s.startswith("<!") or (s == "<"):
            kinds.append(("x", None))
        elif m.group(2):
            kinds.append(("c" if m.group(1) else "o", m.group(2).lower(), m.group(3) or ""))
        else:
            kinds.append(("t", None))
    out = list(toks)
    skip_tag, skip_depth, skip_start = None, 0, None
    stack = [{"items": [], "tag": None, "depth": 0, "start": None}]

    def flush(run):
        items = run["items"]
        run["items"] = []
        if not items:
            return
        _render_run(items, out, toks)

    def flush_all():
        while len(stack) > 1:      # an inline element left open at a block edge: translate its pieces apart
            flush(stack.pop())
        flush(stack[0])

    for i, k in enumerate(kinds):
        kind = k[0]
        if skip_tag:
            if skip_tag == "script" and kind == "t":
                out[i] = js(toks[i])
            if kind == "o" and k[1] == skip_tag and k[1] not in VOID and not k[2].rstrip().endswith("/"):
                skip_depth += 1
            elif kind == "c" and k[1] == skip_tag:
                skip_depth -= 1
                if skip_depth == 0:
                    skip_tag = None
                    items = stack[-1]["items"]
                    if skip_start is not None and items and items[-1][:2] == ("p", skip_start):
                        items[-1] = ("P", skip_start, i)    # the untouched element is one placeholder in the sentence
                    skip_start = None
            continue
        if kind == "t":
            stack[-1]["items"].append(("t", i))
            continue
        if kind == "x":
            flush_all()
            continue
        name, attrs = k[1], k[2]
        if kind == "o" and any(a in attrs for a in ATTRS):
            out[i] = _attr_sub(toks[i])
        if kind == "o" and (name in SKIP or re.search(r"translate\s*=\s*[\"']?no", attrs)):
            if name in OPAQUE or name in FORMAT:   # inline and left as it is: a placeholder inside the sentence
                stack[-1]["items"].append(("p", i, None))
                if name not in VOID:
                    skip_tag, skip_depth, skip_start = name, 1, i
                    stack[-1]["items"][-1] = ("p", i, "skip:" + name)
                continue
            flush_all()
            if name not in VOID:
                skip_tag, skip_depth = name, 1
            continue
        if name in FORMAT:
            stack[-1]["items"].append(("f", i))
            continue
        if name in OPAQUE:
            if kind == "o":
                if name in VOID or attrs.rstrip().endswith("/"):
                    stack[-1]["items"].append(("p", i, None))
                else:
                    stack[-1]["items"].append(("p", i, name))
                    stack.append({"items": [], "tag": name, "depth": 1, "start": i})
            else:
                # closing an opaque element: finish its inner run, record where it ends
                for depth in range(len(stack) - 1, 0, -1):
                    if stack[depth]["tag"] == name:
                        while len(stack) - 1 > depth:
                            flush(stack.pop())
                        run = stack.pop()
                        flush(run)
                        outer = stack[-1]["items"]
                        for j in range(len(outer) - 1, -1, -1):
                            if outer[j][0] == "p" and outer[j][1] == run["start"]:
                                outer[j] = ("P", run["start"], i)
                                break
                        break
                else:
                    flush_all()
            continue
        flush_all()      # any block element ends the sentence
    flush_all()
    # placeholders whose element was skipped (code, translate=no): close them at the matching end tag
    # the page itself says it is English (the Croatian copy it came from said lang=hr; browsers then offer to
    # "translate from Croatian" and screen readers read English with Croatian rules)
    return figures(re.sub(r"<html lang=(hr|\"hr\")>", "<html lang=en>", "".join(out), count=1))


# 13.11.: ui/redak writes amounts the Croatian way ("412k $", "0,000412 $", "+142 %", "3 638"); English readers
# expect "$412k", "$0.000412", "+142%", "3,638". Only the page text is touched, never scripts, styles or tags.
_SP = "[\u00a0 ]"
_MONEY = re.compile(r"(?<![\w.,$])([−+-]?)(\d{1,3}(?:\u00a0\d{3})+|\d+)(?:,(\d+))?([kMB]?)" + _SP + r"\$")
_PCT = re.compile(r"(?<![\w.,])(\d+)(?:,(\d+))?" + _SP + r"%")
_THOUS = re.compile(r"(?<=\d)\u00a0(?=\d{3}(?!\d))")
_PARTS = re.compile(r"(<script\b.*?</script>|<style\b.*?</style>|<[^>]*>)", re.S | re.I)


def _figures_text(t):
    if not any(c in t for c in "$%\u00a0"):
        return t
    t = _MONEY.sub(lambda m: f"{m.group(1)}${m.group(2)}{'.' + m.group(3) if m.group(3) else ''}{m.group(4)}", t)
    t = _PCT.sub(lambda m: f"{m.group(1)}{'.' + m.group(2) if m.group(2) else ''}%", t)
    return _THOUS.sub(",", t)


def figures(html):
    """Croatian number formats in the text of an English page turned English (amounts, percentages, thousands)."""
    return "".join(p if i % 2 else _figures_text(p) for i, p in enumerate(_PARTS.split(html)))


def _render_run(items, out, toks):
    """Translate one run in place: items are ('t', i) text, ('f', i) format tag, ('P', start, end) a finished
    inline element, ('p', i, x) an inline element without a known end (kept as it is, ends the run there)."""
    # an unfinished element splits the run: translate the parts before and after it separately
    parts, cur = [], []
    for it in items:
        if it[0] == "p" and not (it[2] is None):
            if cur:
                parts.append(cur)
            cur = []
            continue
        cur.append(it)
    if cur:
        parts.append(cur)
    for part in parts:
        _render_part(part, out, toks)


def _render_part(items, out, toks):
    texts = [it for it in items if it[0] == "t"]
    if not texts or not any(toks[it[1]].strip() for it in texts):
        return
    import html as h
    key_parts, slots, n = [], {}, 0
    fmt_stack = []
    for it in items:
        if it[0] == "t":
            key_parts.append(h.unescape(toks[it[1]]).replace("<", "‹"))
        elif it[0] == "f":
            tag = toks[it[1]]
            name = re.match(r"</?([a-zA-Z0-9]+)", tag).group(1).lower()
            if tag.startswith("</"):
                for j in range(len(fmt_stack) - 1, -1, -1):
                    if fmt_stack[j][0] == name:
                        num = fmt_stack.pop(j)[1]
                        key_parts.append(f"</{num}>")
                        slots[f"</{num}>"] = tag
                        break
                else:
                    n += 1
                    key_parts.append(f"<{n}/>")
                    slots[f"<{n}/>"] = tag
            elif name in VOID:
                n += 1
                key_parts.append(f"<{n}/>")
                slots[f"<{n}/>"] = tag
            else:
                n += 1
                fmt_stack.append((name, n))
                key_parts.append(f"<{n}>")
                slots[f"<{n}>"] = tag
        else:   # finished inline element: its (already translated) html is one placeholder
            n += 1
            key_parts.append(f"<{n}/>")
            end = it[2] if it[0] == "P" else it[1]
            slots[f"<{n}/>"] = "".join(out[it[1]:end + 1])
    for name, num in fmt_stack:         # a <b> that never closed inside the run: keep it as a plain slot
        k = f"<{num}>"
        slots[f"<{num}/>"] = slots.pop(k)
        key_parts = [f"<{num}/>" if p == k else p for p in key_parts]
    raw = "".join(key_parts)
    lead = raw[:len(raw) - len(raw.lstrip())]
    trail = raw[len(raw.rstrip()):]
    key, nums, v = _find(raw)
    if not key:
        return
    if v is None:
        v = _by_sentences(raw, key)
        if v is None:
            return
    else:
        v = _fill(v, nums)
    if v is None or sorted(_PH.findall(v)) != sorted(p for p in _PH.findall(key) if not p.startswith("{")):
        return     # a stored translation that lost a placeholder would break the page: keep Croatian
    # rebuild: text escaped, placeholders back to the original tags / elements
    pieces = []
    for tok in re.split(r"(</?\d+/?>)", v):
        if re.fullmatch(r"</?\d+/?>", tok):
            pieces.append(slots.get(tok, ""))
        else:
            pieces.append(h.escape(tok.replace("‹", "<"), quote=False))
    first, last = items[0][1], (items[-1][2] if items[-1][0] == "P" else items[-1][1])
    for j in range(first, last + 1):
        out[j] = ""
    out[first] = lead + "".join(pieces).strip() + trail


_TAGTOK = re.compile(r"(</?\d+/?>)")


def _pieces(raw):
    """raw cut after ". ", "! ", "? ", "; " and ": " where no placeholder pair and no bracket is open; [raw] if it
    does not split. A full stop after a digit (dates, "1. sloj") never cuts."""
    out, cur, depth, paren = [], [], 0, 0
    for part in _TAGTOK.split(raw):
        if not part:
            continue
        if _TAGTOK.fullmatch(part):
            depth += 1 if re.fullmatch(r"<\d+>", part) else -1 if part.startswith("</") else 0
            cur.append(part)
            continue
        i = 0
        while i < len(part):
            c = part[i]
            cur.append(c)
            if c in "([„“\"":
                paren += 1 if c in "([„" else (-1 if c == "“" and paren else 0)
            elif c in ")]":
                paren = max(0, paren - 1)
            elif (c in ".!?;:" and depth == 0 and paren == 0 and i + 1 < len(part) and part[i + 1].isspace()
                  and not (c == "." and i and part[i - 1].isdigit())):
                j = i + 1
                while j < len(part) and part[j].isspace():
                    j += 1
                out.append("".join(cur))
                cur = []
                i = j
                continue
            i += 1
    if cur:
        out.append("".join(cur))
    merged = []
    for p in (p.strip() for p in out):
        if not p:
            continue
        if merged and not _WORD.search(_PH.sub(" ", p)):   # "<1/>" or "12." alone: stays with the sentence before
            merged[-1] += " " + p
        elif merged and not _WORD.search(_PH.sub(" ", merged[-1])):
            merged[-1] += " " + p
        else:
            merged.append(p)
    return merged if len(merged) > 1 else [raw]


def _local(p):
    """(key, values, translation or None, back): p looked up with its placeholders renumbered from 1; back() puts the
    page's own numbers back into a translation."""
    order = []
    for tag in _TAGTOK.findall(p):
        n = re.search(r"\d+", tag).group(0)
        if n not in order:
            order.append(n)
    to_new = {old: str(i + 1) for i, old in enumerate(order)}
    to_old = {v: k for k, v in to_new.items()}
    local = _TAGTOK.sub(lambda m: re.sub(r"\d+", lambda d: to_new[d.group(0)], m.group(0)), p)
    k, nums, v = _find(local)
    if v is not None:
        v = _fill(v, nums)
        if v is not None and sorted(_TAGTOK.findall(v)) != sorted(_TAGTOK.findall(local)):
            v = None
    return k, v, (lambda t: _TAGTOK.sub(lambda m: re.sub(r"\d+", lambda d: to_old[d.group(0)], m.group(0)), t))


def _by_sentences(raw, key):
    """The translation of `raw` put together from its sentences (each looked up on its own, placeholders renumbered
    from 1 so the same sentence matches on every page), or None: then the missing sentences are queued (or raw as a
    whole when it does not split)."""
    pieces = _pieces(raw.strip())
    if len(pieces) == 1:
        _queue(key)
        return None
    done, missing = [], []
    for whole in pieces:
        if not _WORD.search(_PH.sub(" ", whole)):
            done.append(whole)
            continue
        k, v, back = _local(whole)
        if not k:              # nothing to translate in it (a number, a name): kept as it is
            done.append(whole)
            continue
        if v is None:
            # lone elements at the edges (a status dot, a link after the sentence) are left outside the lookup
            m = re.fullmatch(r"((?:<\d+/>\s*)*)(.*?)((?:\s*<\d+/>)*)", whole, re.S)
            if m.group(1) or m.group(3):
                k2, v2, back2 = _local(m.group(2))
                if v2 is not None:
                    done.append(m.group(1) + back2(v2) + m.group(3))
                    continue
            missing.append(k)
            continue
        done.append(back(v))
    if missing:
        lone = [k for k in missing if " " not in _PH.sub("", k).strip()]
        if any(not k.endswith(":") for k in lone):
            _queue(key)        # a lone word ("dobro.") is never sent on its own: the whole segment goes instead
            return None
        for k in missing:
            _queue(k, label=k in lone)   # a lone label ("Kupnja:") is: it is a word of the app, not a name
        return None
    return " ".join(done)


# --- background translation -------------------------------------------------------------------------------------

_worker = None
_day = {"d": None, "n": 0}
SYSTEM = (
    "You translate the user interface of MemeSonar, a Croatian web app for Solana meme-coin traders (token radar, "
    "influencer/KOL tracking, demo trading competition, copy trading), from Croatian into natural, concise English "
    "as used by crypto traders. Rules: keep every placeholder exactly as written and keep their count: <1>…</1>, "
    "<2/>, {0}, {1}. You may move them where English word order needs them. Keep emoji, token symbols, names, "
    "brand names (DexScreener, pump.fun, Jupiter, Helius, Telegram, X, MemeSonar), $ amounts and units. Keep the "
    "trader terms traders use in English (KOL, rug, pump, dump, market cap, liquidity, holders, wallet, copy "
    "trading, DCA, stop loss, take profit). 'Natjecanje' = 'Competition', 'Pregled' = 'Overview', 'Postavke' = "
    "'Settings', 'Odjava' = 'Log out', 'Prijava' = 'Log in', 'demo račun' = 'demo account', 'novčanik' = "
    "'wallet', 'Pojmovnik' = 'Glossary', 'Ocjena' = 'Score'. Short labels stay short. If a string is already English "
    "or is only a name, return it unchanged. Return the translations in the same order.")


def _save_auto():
    p = _auto_path()
    os.makedirs(os.path.dirname(p), exist_ok=True)
    tmp = p + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(_auto, f, ensure_ascii=False, separators=(",", ":"))
    os.replace(tmp, p)


def _call(keys):
    import anthropic
    client = anthropic.Anthropic(timeout=180, max_retries=2)
    schema = {"type": "object", "properties": {"t": {"type": "array", "items": {"type": "string"}}},
              "required": ["t"], "additionalProperties": False}
    resp = client.messages.create(
        model=MODEL, max_tokens=16000, system=SYSTEM,
        output_config={"effort": "low", "format": {"type": "json_schema", "schema": schema}},
        messages=[{"role": "user", "content": "Translate these " + str(len(keys)) + " strings:\n"
                   + json.dumps(keys, ensure_ascii=False)}])
    if resp.stop_reason == "refusal":
        return None
    text = "".join(b.text for b in resp.content if b.type == "text")
    return json.loads(text).get("t")


def _ok(key, val):
    return isinstance(val, str) and val.strip() and sorted(_PH.findall(val)) == sorted(_PH.findall(key))


def _day_left():
    today = time.strftime("%Y-%m-%d")
    if _day["d"] != today:
        _day["d"], _day["n"] = today, 0
    return DAILY_MAX - _day["n"]


def run_once(call=None):
    """Translate one batch of the queue; returns how many were stored."""
    _load()
    with _lock:
        keys = [k for k in _pending if k not in _auto and k not in _static and k not in _inflight][:BATCH]
        for k in list(_pending):
            if k in _auto or k in _static:
                _pending.pop(k, None)
    if not keys:
        return 0
    return _translate_keys(keys, call)


def _translate_keys(keys, call=None):
    """Send `keys` to the model (one request), store the good answers; returns how many were stored."""
    with _lock:
        if _day_left() <= 0:
            return 0
        _day["n"] += len(keys)
    try:
        res = (call or _call)(keys)
    except Exception as e:   # no key, network, model error: try again later
        print(f"i18n: prijevod nije uspio ({type(e).__name__}: {str(e)[:200]})", flush=True)
        for k in keys:
            _failed[k] = _failed.get(k, 0) + 1
            if _failed[k] >= 2:
                _pending.pop(k, None)
        return 0
    stored = 0
    with _lock:
        for k, v in zip(keys, res or []):
            if _ok(k, v):
                _auto[k] = v.strip()
                stored += 1
                _pending.pop(k, None)
            else:
                _failed[k] = _failed.get(k, 0) + 1
                if _failed[k] >= 2:
                    _pending.pop(k, None)
        if stored:
            _save_auto()
    if stored:
        print(f"i18n: prevedeno {stored} novih dijelova stranica na engleski", flush=True)
    return stored


_inflight = {}   # key -> threading.Event while a visitor's request translates it


def _can_call():
    return SYNC_S > 0 and bool(os.environ.get("ANTHROPIC_API_KEY")) and not os.environ.get("I18N_OFF")


def translate_now(keys, wait, call=None):
    """Translate `keys` now in parallel batches of SYNC_CHUNK and wait up to `wait` seconds; True when any of them is
    in a dictionary afterwards. Keys another request is already translating are waited for, not sent twice; what
    arrives after `wait` is stored all the same (the next view has it)."""
    _load()
    with _lock:
        todo = [k for k in keys if k not in _static and k not in _auto and k not in _inflight
                and _failed.get(k, 0) < 2][:SYNC_MAX]
        if todo and _day_left() < len(todo):
            todo = todo[:max(0, _day_left())]
        events = [_inflight[k] for k in keys if k in _inflight]
        mine = []
        for i in range(0, len(todo), SYNC_CHUNK):
            chunk = todo[i:i + SYNC_CHUNK]
            ev = threading.Event()
            for k in chunk:
                _inflight[k] = ev
            mine.append((chunk, ev))
    if not mine and not events:
        return False

    def run(chunk, ev):
        try:
            _translate_keys(chunk, call)
        except Exception as e:  # noqa: BLE001 - a failed batch stays queued for the background worker
            print(f"i18n: odmah nije uspjelo ({type(e).__name__}: {str(e)[:120]})", flush=True)
        finally:
            with _lock:
                for k in chunk:
                    if _inflight.get(k) is ev:
                        _inflight.pop(k, None)
            ev.set()
    sem = threading.Semaphore(SYNC_PARALLEL)

    def gated(chunk, ev):
        with sem:
            run(chunk, ev)
    for chunk, ev in mine:
        threading.Thread(target=gated, args=(chunk, ev), daemon=True, name="i18n-now").start()
    end = time.time() + wait
    for ev in [e for _, e in mine] + events:
        left = end - time.time()
        if left <= 0 or not ev.wait(left):
            break
    with _lock:
        return any(k in _auto or k in _static for k in keys)


def _loop():
    while True:
        try:
            n = run_once()
        except Exception as e:
            print(f"i18n: {type(e).__name__}: {e}", flush=True)
            n = 0
        time.sleep(5 if n else 30)


def _start_worker():
    global _worker
    if _worker is not None or not os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("I18N_OFF"):
        return
    with _lock:
        if _worker is not None:
            return
        _worker = threading.Thread(target=_loop, name="i18n", daemon=True)
        _worker.start()


def seed():
    """Queue every known segment of the app (ui/i18n_seed.json) that is not translated yet."""
    try:
        with open(os.path.join(HERE, "i18n_seed.json"), encoding="utf-8") as f:
            keys = json.load(f)
    except (OSError, ValueError):
        return 0
    st, au = _load()
    todo = [k for k in keys if k not in st and k not in au]
    with _lock:
        for k in todo:
            _pending.setdefault(k, 0)
    if todo:
        _start_worker()
    return len(todo)


def stats():
    st, au = _load()
    return {"static": len(st), "auto": len(au), "pending": len(_pending)}


# --- strings inside the page scripts ----------------------------------------------------------------------------

def js(src):
    """Quoted Croatian strings in a script, swapped for their English entry when one exists ('Kopirano' …)."""
    if not is_en():
        return src

    def sub(m):
        q, body = m.group(1), m.group(2)
        if not _WORD.search(body) or "\\" in body or "${" in body:
            return m.group(0)
        new = _load()[0].get(" ".join(body.split()))   # only hand-written entries: a script must never break
        if not new or new == body:
            return m.group(0)
        return q + new.replace(q, "\\" + q) + q
    return re.sub(r"(['`])((?:(?!\1)[^\\\n<>{}=;]){2,120})\1", sub, src)
