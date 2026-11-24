"""Keyword matching of event topics against token names, tickers and descriptions (pure, no I/O).

Token-aware and normalized (11.11., Jure "event tokeni s Grokom"):
  - case-insensitive, a leading or inner "$" is dropped ("$GTA6" == "GTA6")
  - words are runs of letters and digits; every other character (space, "-", "_", ".", "/", emoji) only separates
    them, and separators collapse: a keyword matches when some run of WHOLE consecutive words of the text, glued
    together, equals the keyword glued together. So "GTA 6" == "GTA6" == "gta-6" == "gta_6", and "Grand Theft Auto"
    matches the name "GrandTheftAuto".
  - a keyword never matches part of a word: "GTA6" does not match "GTA", "GTA 5" or "GTAV"; "GTA" does not match
    "GTAV" or "GTA6Inu" (list them as keywords when they should count).
  - a keyword must have at least 2 characters after normalization (validate() refuses the rest).
"""
import re

WORD = re.compile(r"[^\W_]+", re.UNICODE)
MIN_LEN = 2
MAX_LEN = 40
MAX_KEYWORDS = 20
FIELDS = ("symbol", "name", "description")   # the order a match reports its field in (the ticker first)


def words(text):
    """The text's words, lower case, "$" and every separator dropped."""
    return WORD.findall(str(text or "").lower().replace("$", " "))


def norm(keyword):
    """A keyword's normal form: its words glued together ("GTA 6" -> "gta6", "$GTA-6" -> "gta6")."""
    return "".join(words(keyword))


def spans(text, max_len=MAX_LEN):
    """Every run of whole consecutive words of the text glued together, up to max_len characters."""
    ws = words(text)
    out = set()
    for i in range(len(ws)):
        s = ""
        for w in ws[i:]:
            s += w
            if len(s) > max_len:
                break
            out.add(s)
    return out


def validate(keywords):
    """The keywords as given (stripped, deduplicated by normal form, order kept); ValueError with the reason for a
    list that is empty, too long, or has a keyword under MIN_LEN or over MAX_LEN characters after normalization."""
    if isinstance(keywords, str):
        keywords = [keywords]
    if not isinstance(keywords, (list, tuple)) or not keywords:
        raise ValueError("keywords must be a non-empty list of strings")
    if len(keywords) > MAX_KEYWORDS:
        raise ValueError(f"at most {MAX_KEYWORDS} keywords")
    out, seen = [], set()
    for k in keywords:
        if not isinstance(k, str):
            raise ValueError("every keyword must be a string")
        raw = k.strip()
        n = norm(raw)
        if len(n) < MIN_LEN:
            raise ValueError(f"keyword {raw!r} is too short: at least {MIN_LEN} letters or digits (no empty or 1-character "
                             "keywords)")
        if len(n) > MAX_LEN:
            raise ValueError(f"keyword {raw[:50]!r} is longer than {MAX_LEN} characters")
        if n not in seen:
            seen.add(n)
            out.append(raw[:60])
    return out


class Matcher:
    """Keywords of several topics compiled once: {normal form: [topic ids]}. match() checks a token's fields."""

    def __init__(self, topics):
        """topics: {topic_id: [keywords]}."""
        self.by_norm = {}
        for tid, kws in (topics or {}).items():
            for k in kws or []:
                n = norm(k)
                if len(n) >= MIN_LEN:
                    self.by_norm.setdefault(n, []).append(tid)
        self.max_len = max((len(n) for n in self.by_norm), default=0)

    def __bool__(self):
        return bool(self.by_norm)

    def match(self, symbol=None, name=None, description=None):
        """{topic_id: (field, keyword normal form)} of every topic whose keyword matches; the ticker is checked
        first, then the name, then the description (the first field that matches is reported)."""
        out = {}
        if not self.by_norm:
            return out
        for field, text in zip(FIELDS, (symbol, name, description)):
            if not text:
                continue
            for s in spans(text, self.max_len) & self.by_norm.keys():
                for tid in self.by_norm[s]:
                    out.setdefault(tid, (field, s))
        return out


def matches(keywords, symbol=None, name=None, description=None):
    """(field, keyword) of the first match of these keywords on one token, None without one (for tests and one-offs)."""
    return Matcher({0: keywords}).match(symbol, name, description).get(0)
