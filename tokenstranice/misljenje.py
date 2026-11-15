"""Mišljenje AI-ja na stranici tokena (gpt-5-mini, OpenAI Responses API kroz critic/openai_api).

Kad: najviše jednom u EVERY_S (24 h) po tokenu, samo za aktivne stranice s dovoljno podataka (podaci.ENOUGH_DAYS),
u malim serijama (BATCH po satnom prolazu run_tokenstranice.py): prvo tokeni bez mišljenja, zatim najstarija, po
volumenu. Ulaz: samo zaokružene brojke stranice (podaci.basis: nikad adresa, interni servis ni trošak). Izlaz (JSON
shema, strogo): mišljenje na engleskom i hrvatskom (3-5 rečenica, navodi brojke, dobro i loše) i 2-4 rizika po
jeziku. clean() odbacuje odgovor s poveznicom, adresom, e-mailom ili nalogom za kupnju / prodaju. Stranica uz tekst
uvijek piše "Mišljenje AI-ja, nije financijski savjet" / "AI opinion, not financial advice" i datum.

Trošak (CLAUDE.md: izmjeri prije novog troška): vlastiti strop DAY_USD (TOKENSTRANICE_AI_USD_DAY, zadano 0,30 $ po UTC
danu) iz knjige ai_calls; prije svakog poziva se broji najviše što poziv može stajati (openai_api.max_cost), pa se strop
ne prijeđe. Uz to mjesečni strop kritičara (OPENAI_MONTH_USD) s njegovom rezervom za važnije pozive: ovo je posao
najnižeg prioriteta. Svaki poziv ide i u brojilo potrošnje kao usluga "openai", metoda "tokenstranice" (usage.db;
usage/daily.openai ga zbraja uz kritičara). Procjena: ~1.000 tokena ulaza + do ~1.500 izlaza (s razmišljanjem) =
najviše ~0,003 $ po pozivu, stvarno ~0,0015 $; 0,30 $ = 100-200 mišljenja dnevno. 0 isključuje.
"""
import json
import os
import re
import time

from tokenstranice import podaci, store

MODEL = os.environ.get("TOKENSTRANICE_AI_MODEL") or "gpt-5-mini"


def _f(name, default):
    try:
        return float(os.environ.get(name) or default)
    except ValueError:
        return default


DAY_USD = _f("TOKENSTRANICE_AI_USD_DAY", 0.30)
BATCH = int(_f("TOKENSTRANICE_AI_BATCH", 6))
EVERY_S = 86400
MAX_OUT = 1500
METER = True          # tests: False (no usage.db write)
CALL = None           # tests: a stand-in for openai_api.call_json (no network)
LABEL = {"en": "AI opinion, not financial advice", "hr": "Mišljenje AI-ja, nije financijski savjet"}

INSTR = """You write a short, balanced opinion about one Solana meme coin for its public page on a data site.
Rules:
- Use ONLY the numbers in the input JSON. Cite at least three of them with their values (for example "a typical daily
  range of 12 %"). A null value is unknown: never guess it.
- Say what looks strong and what looks weak. Then name 2 to 4 concrete risks.
- No price targets, no prediction of the future price, no instruction or suggestion to buy, sell or hold, no
  "not financial advice" line (the page adds its own label), no links, no wallet or contract addresses, no emojis,
  no hype words.
- Do not invent anything that is not in the input (team, roadmap, news, partnerships, listings).
- Shares are fractions (0.42 = 42 %), *_pct values are percent.
Write the same opinion twice: opinion_en in plain English and opinion_hr in natural Croatian (decimal comma), 3 to 5
sentences each, and the risks as short phrases in risks_en and risks_hr."""

SCHEMA = {"type": "object", "additionalProperties": False,
          "required": ["opinion_en", "opinion_hr", "risks_en", "risks_hr"],
          "properties": {"opinion_en": {"type": "string"}, "opinion_hr": {"type": "string"},
                         "risks_en": {"type": "array", "items": {"type": "string"}},
                         "risks_hr": {"type": "array", "items": {"type": "string"}}}}

_BAD = re.compile(r"https?://|www\.|\b[\w.+\-]+@[\w\-]+\.\w|[1-9A-HJ-NP-Za-km-z]{32,}|\bbuy now\b|\bsell now\b|"
                  r"\bkupi(te)? (odmah|sada)\b|\bprodaj(te)? (odmah|sada)\b|\bguarantee|\bzajamčen|\b100x\b|🚀", re.I)


def clean(data):
    """The answer as stored, or None when it breaks a rule (see the module text)."""
    if not isinstance(data, dict):
        return None
    out = {}
    for lang in ("en", "hr"):
        op = " ".join(str(data.get(f"opinion_{lang}") or "").split())[:1200]
        risks = [" ".join(str(r).split())[:220] for r in (data.get(f"risks_{lang}") or []) if str(r).strip()][:4]
        if len(op) < 40 or _BAD.search(op) or any(_BAD.search(r) for r in risks):
            return None
        out[lang] = {"text": op, "risks": risks}
    return out


def due(con, now, limit):
    """[(mint, data)] of the active pages with enough data whose opinion is missing or older than EVERY_S."""
    rows = con.execute("""SELECT p.mint, p.data FROM pages p LEFT JOIN opinions o ON o.mint = p.mint
        WHERE p.active = 1 AND p.enough = 1 AND (o.ts IS NULL OR o.ts < ?)
        ORDER BY (o.ts IS NOT NULL), o.ts, p.vol24 DESC LIMIT ?""", (int(now - EVERY_S), int(limit))).fetchall()
    out = []
    for m, raw in rows:
        try:
            out.append((m, json.loads(raw or "{}")))
        except ValueError:
            continue
    return out


def _month_start(now):
    import datetime as dt
    d = dt.datetime.fromtimestamp(int(now), dt.timezone.utc)
    return int(dt.datetime(d.year, d.month, 1, tzinfo=dt.timezone.utc).timestamp())


def month_room(con, now):
    """USD this job may still spend this month: the critic's month cap minus its reserve for the important kinds,
    minus what the critic (trade.db, read-only) and these pages spent. None = not readable (only the day cap then)."""
    try:
        from critic import store as cstore
        cap = cstore.MONTH_USD - cstore.MONTH_RESERVE.get("trades", 0.0)
        from trade import settings
        tc = podaci._ro(settings.DB)
        crit = 0.0
        if tc is not None:
            try:
                crit = cstore.spent(tc, cstore.month_start(now))
            except Exception:  # noqa: BLE001 - no critic table yet
                crit = 0.0
            finally:
                tc.close()
        return cap - crit - store.spent(con, _month_start(now))
    except Exception:  # noqa: BLE001
        return None


def _meter(cost):
    if not METER:
        return
    try:
        from usage import meter
        meter.record("openai", "tokenstranice", amount=float(cost or 0))
    except Exception:  # noqa: BLE001 - a lost count never stops the job
        pass


def run_batch(con, now=None, log=print, batch=None):
    """Up to `batch` opinions within the caps. {"n", "usd", "fail", "why"} (why: why it stopped early)."""
    now = int(now or time.time())
    out = {"n": 0, "usd": 0.0, "fail": 0, "why": None}
    if DAY_USD <= 0:
        out["why"] = "isključeno (strop 0)"
        return out
    from critic import openai_api
    call = CALL or openai_api.call_json
    if CALL is None and not openai_api.has_key():
        out["why"] = "nema ključa"
        return out
    for mint, d in due(con, now, BATCH if batch is None else batch):
        user = json.dumps(podaci.basis(d), ensure_ascii=False)
        est = openai_api.max_cost(MODEL, len(INSTR) + len(user), MAX_OUT)
        spent = store.spent(con, store.day_start(now))
        if spent + est > DAY_USD:
            out["why"] = f"dnevni strop {DAY_USD:.2f} $ (potrošeno {spent:.3f} $)"
            break
        room = month_room(con, now)
        if room is not None and est > room:
            out["why"] = "mjesečni strop OpenAI-ja (rezerva za kritičara)"
            break
        try:
            res = call(MODEL, INSTR, user, SCHEMA, "token_opinion", MAX_OUT, "low")
        except openai_api.ApiError as e:
            cost = openai_api.cost(e.model or MODEL, e.usage) if e.usage else 0.0
            store.book(con, mint, e.model or MODEL, e.usage, cost, False, str(e)[:120], now)
            _meter(cost)
            out["usd"] += cost
            out["fail"] += 1
            if e.usage is None:   # no answer at all (no access, rate limit, network): the next hour, not 6 waits
                out["why"] = f"OpenAI HTTP {e.status}" if e.status else "OpenAI nije odgovorio"
                break
            continue
        cost = float(res.get("cost_usd") or 0)
        _meter(cost)
        out["usd"] += cost
        data = clean(res.get("data"))
        if data is None:
            store.book(con, mint, res.get("model") or MODEL, res.get("usage"), cost, False, "odgovor prekršio pravila", now)
            out["fail"] += 1
            continue
        store.book(con, mint, res.get("model") or MODEL, res.get("usage"), cost, True, None, now)
        con.execute("INSERT OR REPLACE INTO opinions (mint, ts, model, data, cost_usd, basis) VALUES (?,?,?,?,?,?)",
                    (mint, now, res.get("model") or MODEL, json.dumps(data, ensure_ascii=False), round(cost, 6),
                     user[:4000]))
        con.commit()
        out["n"] += 1
    out["usd"] = round(out["usd"], 6)
    return out
