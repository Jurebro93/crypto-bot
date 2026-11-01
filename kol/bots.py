"""Automated alert accounts on X and Telegram ("scanner" bots), told apart from people who call tokens.

Accounts like blossomscanner, bitecong ("AI Signal ... CA:"), SolTokenScan ("PUMP MIGRATION SPOTTED"),
dex_kolwatcher ("Detect PAID DEXScreener") post a fixed template for EVERY fresh token. Counted as KOL calls they
co-call almost every token with each other, so the same pair showed up as the "KOL group" on 6 of 8 tokens of the
day (1.11.), fed the kol_group feature, the convergence entries and the KOL test book, and their measured
"calls" (dust-priced fresh pools) produced absurd best calls.

An account is a bot when (rules in kol/config.json "bots"):
  alert    at least alert_share of its posts are alert templates (AI Signal, migration, Liq:/Holders:/Top10, ...)
  handle   its name says so (scan, bot, alert, tracker, ...) AND it posts like one (some alerts, a fixed template,
           or many different tokens a day)
  template at least template_share of at least template_min posts are the same text once CA/ticker/numbers go
  volume   it named at least max_tokens_day different tokens within one 24 h window
  force    listed by hand in config (never: listed people that must not be flagged)
Its posts get kind 'bot' (not 'call'), so groups, KOL score, watch list, convergence and the morning report skip
them without any further change. Recomputed on every score run, so a better rule also fixes old rows.
"""
import collections
import re

ALERT = re.compile(r"ai signal|migrat(?:ed|ion)|detect paid|dex ?paid|cto ping|rug ?ratio|\brug:|top ?10:|holders:|"
                   r"\bliq(?:uidity)?:|bonding curve|new (?:pair|listing|token) (?:detected|alert|on)|token alert|"
                   r"just launched|fresh (?:pump|launch)|\bmint:|freeze:|renounced", re.I)
HANDLE = re.compile(r"scan|bot\b|bot_|_bot|alert|tracker|watcher|signal|monitor|feed|sniper_?bot", re.I)
_CA = re.compile(r"[1-9A-HJ-NP-Za-km-z]{32,44}|0x[0-9a-fA-F]{40}")


def _norm(text):
    """Template shape of a post: links, CAs, tickers and numbers replaced, first words only."""
    t = re.sub(r"https?://\S+", " U ", text or "")
    t = _CA.sub(" C ", t)
    t = re.sub(r"\$[A-Za-z][A-Za-z0-9]{1,11}", " T ", t)
    t = re.sub(r"\d+(?:[.,]\d+)*\s?[kKmMbBxX%]?", " N ", t)
    t = re.sub(r"[^A-Za-z]+", " ", t).strip().lower()
    return " ".join(t.split()[:6])


def classify(handle, posts, cfg):
    """posts: [(ts, token, text)] of one account (one row per tweet and token). -> (is_bot, reason)."""
    b = cfg.get("bots") or {}
    if handle in set(b.get("never") or []):
        return False, ""
    if handle.lower() in {h.lower() for h in b.get("force") or []}:
        return True, "ručno označen kao bot"
    texts = {}
    for ts, tok, text in posts:
        texts.setdefault((ts, text or ""), text or "")
    n = len(texts)
    if n == 0:
        return False, ""
    alert = sum(1 for t in texts.values() if ALERT.search(t)) / n
    shapes = collections.Counter(_norm(t) for t in texts.values())
    tmpl = shapes.most_common(1)[0][1] / n
    srt = sorted((ts, tok) for ts, tok, _ in posts)
    best, j = 0, 0
    for i in range(len(srt)):
        while srt[i][0] - srt[j][0] > 86400:
            j += 1
        best = max(best, len({t for _, t in srt[j:i + 1]}))
    min_posts = b.get("min_posts", 5)
    if n >= min_posts and alert >= b.get("alert_share", 0.5):
        return True, f"{alert:.0%} objava su automatske obavijesti"
    if HANDLE.search(handle.split(":", 1)[-1]) and (alert >= 0.2 or (n >= min_posts and tmpl >= 0.5)
                                                    or best >= b.get("handle_tokens_day", 15)):
        return True, f"ime računa i način objavljivanja ({best} tokena u 24 h, isti obrazac {tmpl:.0%})"
    if n >= b.get("template_min", 20) and tmpl >= b.get("template_share", 0.9):
        return True, f"{tmpl:.0%} objava je isti predložak"
    if best >= b.get("max_tokens_day", 40):
        return True, f"{best} različitih tokena u 24 h"
    return False, ""


def detect(con, cfg):
    """Flag bots in kols (bot, bot_why) from every stored post. Wallet rows (w:) are never bots. -> set of handles."""
    by = collections.defaultdict(list)
    for h, ts, tok, text in con.execute("SELECT handle, ts, token, text FROM calls WHERE kind IN "
                                        "('call', 'brag', 'warn', 'bot') AND handle NOT LIKE 'w:%'"):
        by[h].append((ts, tok, text))
    bots = {}
    for h, posts in by.items():
        ok, why = classify(h, posts, cfg)
        if ok:
            bots[h] = why
    con.execute("UPDATE kols SET bot = 0, bot_why = NULL WHERE COALESCE(bot, 0) != 0")
    con.executemany("UPDATE kols SET bot = 1, bot_why = ? WHERE handle = ?", [(w, h) for h, w in bots.items()])
    return set(bots)


def handles(con):
    """Set of handles flagged as bots ({} on an old kol.db without the column)."""
    if con is None:
        return set()
    try:
        return {h for (h,) in con.execute("SELECT handle FROM kols WHERE bot = 1")}
    except Exception:  # noqa: BLE001 - column or table missing
        return set()
