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

FORMAT = {"b", "strong", "i", "em", "small", "u", "s", "mark", "sup", "sub", "br", "wbr"}
OPAQUE = {"a", "span", "code", "kbd", "abbr", "img", "time", "q", "cite", "bdi", "var", "data"}
SKIP = {"script", "style", "pre", "textarea", "svg", "code", "noscript"}
VOID = {"br", "wbr", "img", "input", "hr", "meta", "link", "source", "area", "col", "embed", "param", "track"}
ATTRS = ("title", "placeholder", "aria-label", "data-tip", "alt", "data-ready", "data-bad", "data-big")

_TOK = re.compile(r"<!--.*?-->|<![^>]*>|<(/?)([a-zA-Z][a-zA-Z0-9\-]*)((?:[^>\"']|\"[^\"]*\"|'[^']*')*)>|[^<]+|<", re.S)
_ATTR = re.compile(r"""(\s(?:%s)\s*=\s*)("([^"]*)"|'([^']*)')""" % "|".join(ATTRS))
_NUM = re.compile(r"[1-9A-HJ-NP-Za-km-z]{30,}|\d+(?:[.,:]\d+)*")   # numbers and Solana addresses
_WORD = re.compile(r"[A-Za-zČčĆćŠšŽžĐđ]{2,}")
_ADDR = re.compile(r"^[1-9A-HJ-NP-Za-km-z]{25,}$|^https?://|^[\w.\-]+\.(com|io|fun|xyz|net|org)\b")
_PH = re.compile(r"</?\d+/?>|\{\d+\}")


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
    key, nums = _template(text)
    if not key:
        return text
    v = lookup(key)
    if v is None:
        _queue(key)
        return text
    return _fill(v, nums) or text


def _template(text):
    nums = []

    def sub(m):
        nums.append(m.group(0))
        return "{%d}" % (len(nums) - 1)
    key = "".join(part if re.fullmatch(r"</?\d+/?>", part) else _NUM.sub(sub, part)
                  for part in re.split(r"(</?\d+/?>)", " ".join(text.split())))
    if not wants(key):
        return None, nums
    return key, nums


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


def _queue(key):
    # one word on its own (a token or a player name, mostly) is never sent: the menu words are in the dictionaries
    if " " not in _PH.sub("", key).strip():
        return
    if key in _pending or _failed.get(key, 0) >= 2 or len(_pending) > 20000:
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


def translate(page):
    """The page in English as far as the dictionaries go; unknown segments are queued for translation."""
    if not page or not is_en():
        return page
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
    return "".join(out)


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
    key, nums = _template(raw)
    if not key:
        return
    v = lookup(key)
    if v is None:
        _queue(key)
        return
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


# --- background translation -------------------------------------------------------------------------------------

_worker = None
_day = {"d": None, "n": 0}
SYSTEM = (
    "You translate the user interface of KriptoRadar, a Croatian web app for Solana meme-coin traders (token radar, "
    "influencer/KOL tracking, demo trading competition, copy trading), from Croatian into natural, concise English "
    "as used by crypto traders. Rules: keep every placeholder exactly as written and keep their count: <1>…</1>, "
    "<2/>, {0}, {1}. You may move them where English word order needs them. Keep emoji, token symbols, names, "
    "brand names (DexScreener, pump.fun, Jupiter, Helius, Telegram, X, KriptoRadar), $ amounts and units. Keep the "
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


def run_once(call=None):
    """Translate one batch of the queue; returns how many were stored."""
    _load()
    with _lock:
        keys = [k for k in _pending if k not in _auto and k not in _static][:BATCH]
        for k in list(_pending):
            if k in _auto or k in _static:
                _pending.pop(k, None)
    if not keys:
        return 0
    today = time.strftime("%Y-%m-%d")
    if _day["d"] != today:
        _day["d"], _day["n"] = today, 0
    if _day["n"] >= DAILY_MAX:
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
