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
Not a KOL either (2.11.: Nicholas opened the top of the leaderboard on X and most were not KOLs):
  spam     hacked accounts of unrelated people (a footballer, a rapper, a painter) posting one drainer template
           "$TOKEN is in the listing window ... Click below to vote" + CA + a random 5-character code, 1-20 views
  promo    sells access to a paid group ("DM for early access", "private TG", "VIP TG")
  dev      pumps its own launches: first on X for (nearly) every token and posts about each one again and again
  force    news/listing bots and anything else checked by hand
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
ALERT_NEWS = re.compile(r"alpha alert|trending .{0,30}alert|is surging on|now listed on|listing on (?:binance|bybit|okx|"
                        r"mexc|gate|bitget|kucoin|coinbase)", re.I)
# drainer network: "vote" / "listing window" posts and a random 5-character code right after the CA
VOTE = re.compile(r"\bvote\b|listing window", re.I)
CODE = re.compile(r"(?:[1-9A-HJ-NP-Za-km-z]{32,44})[ \t]+[a-z0-9]{5}[ \t]*$", re.M)
PAID = re.compile(r"dm (?:me )?for (?:the |my )?(?:invitation|invite|early access|access|vip)|private (?:tg|telegram|group|"
                  r"channel)|vip (?:group|channel|tg|telegram)|paid (?:group|channel)|premium (?:group|channel|tg)|"
                  r"join my (?:vip|private|premium)", re.I)


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
        ok, why = classify(handle, posts, dict(cfg, bots=dict(b, force=[])))
        return True, why if ok else "ručno provjereno: nije KOL"
    texts = {}
    for ts, tok, text, *_ in posts:
        texts.setdefault((ts, text or ""), text or "")
    n = len(texts)
    if n == 0:
        return False, ""
    vote = sum(1 for t in texts.values() if VOTE.search(t))
    code = sum(1 for t in texts.values() if CODE.search(t))
    both = sum(1 for t in texts.values() if VOTE.search(t) and CODE.search(t))
    spam = b.get("spam_share", 0.3)
    if both or (code >= 2 and code / n >= spam) or (vote >= 2 and vote / n >= spam and code):
        return True, "spam mreža (vjerojatno hakiran račun): \"klikni za glasanje\" + CA + nasumični kod, link je " \
                     "vjerojatno drainer"
    paid = sum(1 for t in texts.values() if PAID.search(t))
    if paid and paid / n >= b.get("promo_share", 0.3):
        return True, f"prodaje pristup plaćenoj grupi ({paid} od {n} objava)"
    dev = _dev(posts, b)
    if dev:
        return True, dev
    alert = sum(1 for t in texts.values() if ALERT.search(t) or ALERT_NEWS.search(t)) / n
    shapes = collections.Counter(_norm(t) for t in texts.values())
    tmpl = shapes.most_common(1)[0][1] / n
    srt = sorted((p[0], p[1]) for p in posts)
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


def _dev(posts, b):
    """Reason when an account pumps its own launches, else ''. posts may carry first_overall as a 4th field: 1 when
    this account was the first on X to name the token."""
    per = collections.defaultdict(lambda: [set(), 0])
    for p in posts:
        per[p[1]][0].add((p[0], p[2] or ""))
        if len(p) > 3 and p[3]:
            per[p[1]][1] = 1
    tok = len(per)
    n = sum(len(v[0]) for v in per.values())
    if tok < b.get("dev_tokens", 5) or n < b.get("dev_posts", 20):
        return ""
    first = sum(v[1] for v in per.values()) / tok
    heavy = sum(len(v[0]) for v in per.values() if len(v[0]) >= b.get("dev_heavy", 5)) / n
    if first >= b.get("dev_first", 0.9) and heavy >= b.get("dev_heavy_share", 0.5):
        return f"zove vlastite tokene: prvi na X-u za {first:.0%} od {tok} tokena i objavljuje o svakom iznova"
    return ""


def detect(con, cfg):
    """Flag bots in kols (bot, bot_why) from every stored post. Wallet rows (w:) are never bots. -> set of handles."""
    by = collections.defaultdict(list)
    for h, ts, tok, text, first in con.execute("SELECT handle, ts, token, text, first_overall FROM calls WHERE kind IN "
                                               "('call', 'brag', 'warn', 'bot') AND handle NOT LIKE 'w:%'"):
        by[h].append((ts, tok, text, first))
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
