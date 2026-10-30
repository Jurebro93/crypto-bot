"""Keywords and a 0-100 hype score for each event."""
import math
import re
import unicodedata

# Names and themes the Solana memecoin crowd reliably trades. Extend freely.
CRYPTO_AFFINITY = {
    "elon": 25, "musk": 25, "tesla": 20, "spacex": 20, "starship": 15, "doge": 25,
    "trump": 25, "maga": 20, "melania": 15, "barron": 15, "vance": 10, "kirk": 20,
    "saylor": 15, "satoshi": 20, "bitcoin": 15, "vitalik": 10, "cz": 10, "pepe": 20,
    "openai": 10, "altman": 10, "grok": 15, "ai": 5, "nvidia": 10, "kanye": 15,
    "mrbeast": 15, "halloween": 10, "christmas": 10, "pope": 10,
}

STOP = {"the", "of", "and", "a", "an", "in", "on", "for", "to", "by", "will", "be", "yrs",
        "birthday", "death", "anniversary", "launch", "who", "what", "is",
        # months and generic market words: they match thousands of unrelated tokens
        "january", "february", "march", "april", "may", "june", "july", "august", "september",
        "october", "november", "december", "jan", "feb", "mar", "apr", "jun", "jul", "aug", "sep",
        "sept", "oct", "nov", "dec", "end", "price", "hit", "above", "below", "winner", "election",
        "company", "model", "team", "club", "more", "markets", "group", "stage", "best", "largest",
        "next", "release", "released", "vs", "tweets", "party", "win", "returns", "normal", "traffic"}


def _ascii(s):
    return unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode()


def keywords(event):
    """Ticker-style variants a pump.fun creator would plausibly use."""
    words = [w for w in re.findall(r"[A-Za-z0-9]+", _ascii(event["subject"]))
             if w.lower() not in STOP and not w.isdigit()]
    kws = set(k.upper() for k in event.get("signals", {}).get("keywords", []))
    for w in words:
        if len(w) >= 3:
            kws.add(w.upper())
    if 2 <= len(words) <= 3:
        kws.add("".join(words).upper())
    if event["kind"] == "birthday" and words:
        kws.add(f"{words[-1].upper()}BDAY")
    return sorted(k for k in kws if len(k) <= 14)


def affinity(event):
    text = _ascii(f"{event['title']} {event['subject']}").lower()
    return max([v for k, v in CRYPTO_AFFINITY.items() if re.search(rf"\b{k}\b", text)] or [0])


def hype_score(event, days_until):
    s = event.get("signals", {})
    fame = min(25, 25 * math.log10(1 + s.get("sitelinks", 0)) / math.log10(300))
    views = min(15, 15 * math.log10(1 + s.get("views_30d", 0)) / 7)  # 10M views = max
    trend = min(10, max(0, (s.get("trend", 1.0) - 1) * 10))
    market = min(20, 20 * math.log10(1 + s.get("pm_volume", 0)) / 8)  # $100M = max
    aff = min(25, affinity(event))
    manual = 10 if event["source"] == "manual" else 0  # curated = already judged relevant
    proximity = max(0, 5 - days_until * 0.5)
    return round(min(100, fame + views + trend + market + aff + manual + proximity), 1)


# How often each kind of event has historically spawned dedicated pump.fun tokens (prior, 0-1).
KIND_PRIOR = {
    "game_release": 0.8, "launch": 0.6, "media_release": 0.5, "viral_now": 0.25, "disaster": 0.55,
    "death_anniversary": 0.45, "birthday": 0.35, "crypto": 0.5, "holiday": 0.3,
    "launch_deadline": 0.4, "prediction_market": 0.15, "manual": 0.4, "election": 0.3,
    "rocket_launch": 0.05,
}
# Viral topics the memecoin crowd ignores: sport, awards, foreign politics.
VIRAL_IGNORED = re.compile(r"\b(footballer|football|soccer|cricket\w*|basketball|baseball|athlete|tennis|golfer|"
                           r"award|election|legislative|parliament\w*|general and politician|season)\b", re.I)
DEATH_IN_DESC = re.compile(r"\(\d{4}\s*[–-]\s*20\d\d\)|\bdied\b", re.I)
ROUTINE = re.compile(r"\b(starlink|transporter|bandwagon|cargo dragon|crs-\d+|ussf|weather|"
                     r"earnings|cpi|fomc|jobs report)\b", re.I)
# Words in a viral article's description that usually mean "this will get a token".
MEME_TRIGGERS = re.compile(r"\b(died|death|killed|shot|assassinat\w*|arrest\w*|meme|viral|scandal|"
                           r"earthquake|tsunami|hurricane|eruption|asteroid|crash|explosion|"
                           r"announced|unveiled|released|trailer|baby|wedding|divorce)\b", re.I)


def token_likelihood(event):
    """0-1 guess that people will mint tokens for this event. Tune with backtests."""
    s = event.get("signals", {})
    text = f"{event['title']} {event['subject']} {s.get('description', '')}"
    if ROUTINE.search(text):
        return 0.05
    if event["kind"] == "rocket_launch" and re.search(r"\bstarship\b", text, re.I):
        return 0.75  # Starship flights reliably get tokens; other launches don't
    if event["kind"] == "viral_now":
        return _viral_likelihood(event, s)
    p = KIND_PRIOR.get(event["kind"], 0.3)
    p += 0.3 * min(25, affinity(event)) / 25
    if MEME_TRIGGERS.search(text):
        p += 0.15
    if s.get("spike", 0) >= 10:
        p += 0.1
    if s.get("news_articles", 0) >= 5:
        p += 0.05
    if s.get("magnitude", 0) >= 8 or s.get("tsunami"):
        p += 0.1
    return round(min(1.0, p), 2)


def _viral_likelihood(event, s):
    desc = s.get("description", "")
    if VIRAL_IGNORED.search(f"{event['subject']} {desc}") and not affinity(event):
        return 0.1
    p = KIND_PRIOR["viral_now"] + 0.45 * min(25, affinity(event)) / 25
    if DEATH_IN_DESC.search(desc):
        p += 0.2  # celebrity deaths regularly get memorial tokens
    if MEME_TRIGGERS.search(f"{event['subject']} {desc}"):
        p += 0.1
    if s.get("spike", 0) >= 10:
        p += 0.1
    return round(min(1.0, p), 2)


def event_score(event, days_until):
    """Final ranking: hype (how big) weighted by token likelihood (will it get a token)."""
    tl = token_likelihood(event)
    s = event.get("signals", {})
    viral = min(25, 25 * math.log10(1 + s.get("views_1d", 0)) / 7) if event["kind"] == "viral_now" else 0
    news = min(10, 3 * s.get("news_articles", 0))
    return tl, round(min(100, (hype_score(event, days_until) + viral + news) * (0.3 + 0.7 * tl)), 1)
