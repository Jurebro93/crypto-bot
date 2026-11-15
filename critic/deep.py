"""Kritičar (OpenAI): the deep session (15.11. navečer, vlasnik: "dubinski pregled"). The strong model (OPENAI_MODEL_DEEP,
gpt-6-astra) gets a READ-ONLY SQL tool over the bot's SQLite databases and looks for correlations between features and
outcomes after fees, checked on later days (holdout), with n, effect size and a warning about multiple testing. ADVICE
ONLY: findings are suggestion notes, one daily summary "Dubinski pregled"; nothing applies by itself.

The SQL tool (sql(db, query)), the hard limits:
  - every database opened read-only (file:...?mode=ro); only SELECT / WITH statements, one statement; the SQLite
    authorizer allows reads and functions only (no PRAGMA but table_info, no ATTACH, no write of any kind)
  - DENY_TABLES / DENY_COLUMNS (settings, key-value state, keys, signatures, the owner's wallet, chat, site visitors)
    are refused by the authorizer, also through SELECT *; DENY_DBS are not offered at all
  - QUERY_TIMEOUT_S per query (a progress handler), MAX_ROWS rows, MAX_RESULT_CHARS characters of JSON, MAX_QUERIES
    a session; QUERY_PAUSE_S between queries (the server is near its CPU limit; the process runs at nice 10)
  - every Solana address in a result is replaced by an alias [a:xxxxxx] (a hash), so no wallet or token address
    leaves; an alias in the model's query is mapped back to the address before it runs; player names are replaced
    too; the whole outgoing text is scrubbed (critic/privacy.py)
Budget: OPENAI_DEEP_USD (2.00) per session (each turn's most is checked before it is sent, leaving room for the final
answer), the month cap with the priority reserves (critic/store.py). Each API turn is a critic_calls row (kind deep).

Schedule (run_sched kriticar_dubinski -> run_critic.py deep --auto every 10 min): the FIRST session right after the
deploy that brings this (once: critic_kv deep_first), then every KRITICAR_DEEP_EVERY_H (48) hours, inside the night
window 01-06 Zagreb (ops/heavy.NIGHT). Log: "kritičar: dubinski pregled spremljen, N nalaza, upita Q, trošak X $".
"""
import datetime as dt
import glob
import hashlib
import json
import os
import re
import sqlite3
import time

from critic import data as cdata
from critic import notes as cnotes
from critic import openai_api, privacy, prompts
from critic import store

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EVERY_H = float(os.environ.get("KRITICAR_DEEP_EVERY_H") or 48)
MAX_QUERIES = 30
MAX_ROWS = 200
MAX_RESULT_CHARS = 20_000
QUERY_TIMEOUT_S = 5.0
QUERY_PAUSE_S = 0.5
MAX_TURNS = 16
TURN_OUT = 6000
FINAL_OUT = 10000
EFFORT = "medium"
SCHEMA_TTL_S = 24 * 3600
DENY_DBS = {"analytics.db"}   # the public site's visitors
DENY_TABLES = {"settings", "invites", "access_requests", "ap_chat", "ap_chat_votes", "members", "profiles",
               "live_state", "site_log", "critic_kv", "sqlite_master", "sqlite_schema", "sqlite_sequence"}
DENY_PREFIX = ("ga_", "gsc_", "sqlite_")
DENY_SUFFIX = ("kv",)
DENY_COLUMNS = {"signature", "request_id", "key_id", "owner_note", "email", "password", "pass", "secret", "api_key",
                "apikey", "private_key", "privkey", "secret_key", "phone", "ip", "user_agent", "cookie", "session",
                "wallet_pub", "who", "sig"}
ALIAS = re.compile(r"\[a:([0-9a-f]{8})\]")
SQL_TOOL = {"type": "function", "name": "sql", "strict": True,
            "description": ("Run ONE read-only SQLite query (SELECT or WITH only) on one of the bot's databases. At most "
                            f"{MAX_ROWS} rows and about {MAX_RESULT_CHARS // 1000} kB are returned, {QUERY_TIMEOUT_S:.0f} s "
                            "per query. Aggregate in SQL. Addresses appear as [a:xxxxxxxx] aliases; an alias may be "
                            "used as a value in a query."),
            "parameters": {"type": "object", "additionalProperties": False, "required": ["db", "query"],
                           "properties": {"db": {"type": "string", "description": "database name from the catalog, e.g. league"},
                                          "query": {"type": "string"}}}}


def denied_table(name):
    n = str(name or "").lower()
    return n in DENY_TABLES or n.startswith(DENY_PREFIX) or n.endswith(DENY_SUFFIX)


def databases(root=None):
    """{name without ".db" (the tool's db argument): path} of the bot's databases that may be read."""
    root = root or ROOT
    out = {}
    for p in sorted(glob.glob(os.path.join(root, "*.db"))):
        n = os.path.basename(p)
        if n in DENY_DBS:
            continue
        try:
            if os.path.getsize(p) > 0:
                out[n[:-3]] = p
        except OSError:
            continue
    return out


_OK_ACTIONS = {sqlite3.SQLITE_SELECT, sqlite3.SQLITE_FUNCTION, getattr(sqlite3, "SQLITE_RECURSIVE", 33)}


def _authorizer(action, a1, a2, _db, _trigger):
    if action in _OK_ACTIONS:
        return sqlite3.SQLITE_OK
    if action == sqlite3.SQLITE_READ:
        if denied_table(a1) or str(a2 or "").lower() in DENY_COLUMNS:
            return sqlite3.SQLITE_DENY
        return sqlite3.SQLITE_OK
    if action == sqlite3.SQLITE_PRAGMA and str(a1 or "").lower() == "table_info" and not denied_table(a2):
        return sqlite3.SQLITE_OK
    return sqlite3.SQLITE_DENY


def open_ro(path):
    con = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=5)
    con.execute("PRAGMA query_only = ON")
    con.set_authorizer(_authorizer)
    return con


def check_sql(q):
    """The statement, stripped, or ValueError: one SELECT / WITH statement, nothing else."""
    s = str(q or "").strip().rstrip(";").strip()
    if not s:
        raise ValueError("prazan upit")
    if ";" in s:
        raise ValueError("samo jedna naredba")
    head = s.split(None, 1)[0].upper()
    if head not in ("SELECT", "WITH"):
        raise ValueError("dopušteni su samo SELECT i WITH")
    if re.search(r"\b(ATTACH|DETACH|PRAGMA|INSERT|UPDATE|DELETE|REPLACE|CREATE|DROP|ALTER|VACUUM|REINDEX|ANALYZE)\b",
                 s, re.I):
        raise ValueError("naredba nije dopuštena")
    return s


class Aliases:
    """Address <-> [a:xxxxxxxx]: one-way for the model (a hash), mapped back for its queries within the session."""
    def __init__(self, names=()):
        self.back = {}
        self.names = {n for n in names if n and len(n) >= 3}

    def alias(self, addr):
        a = "[a:" + hashlib.sha256(addr.encode()).hexdigest()[:8] + "]"
        self.back[a[3:-1]] = addr
        return a

    def hide(self, text):
        s = privacy.B58.sub(lambda m: self.alias(m.group(0)), str(text))
        for n in sorted(self.names, key=len, reverse=True):
            s = re.sub(rf"\b{re.escape(n)}\b", "[igrač]", s)
        return s

    def reveal(self, query):
        return ALIAS.sub(lambda m: "'" + self.back[m.group(1)] + "'" if m.group(1) in self.back else m.group(0),
                         query.replace("'[a:", "[a:").replace("]'", "]"))


def run_sql(dbs, db, query, aliases, timeout=QUERY_TIMEOUT_S):
    """The tool's answer as text (JSON): {"columns", "rows", "truncated"} or {"error"}."""
    db = db[:-3] if db.endswith(".db") else db
    if db not in dbs:
        return json.dumps({"error": f"nepoznata baza {db}; dostupne: {', '.join(sorted(dbs))}"}, ensure_ascii=False)
    try:
        q = aliases.reveal(check_sql(query))
    except ValueError as e:
        return json.dumps({"error": str(e)}, ensure_ascii=False)
    try:
        con = open_ro(dbs[db])
    except sqlite3.Error as e:
        return json.dumps({"error": f"baza se ne može otvoriti ({e})"}, ensure_ascii=False)
    t0 = time.monotonic()
    con.set_progress_handler(lambda: 1 if time.monotonic() - t0 > timeout else 0, 20_000)
    try:
        cur = con.execute(q)
        cols = [c[0] for c in cur.description or []]
        rows = cur.fetchmany(MAX_ROWS + 1)
    except sqlite3.Error as e:
        msg = "upit prekinut (više od %.0f s)" % timeout if "interrupt" in str(e).lower() else str(e)[:300]
        return json.dumps({"error": msg}, ensure_ascii=False)
    finally:
        con.close()
    more = len(rows) > MAX_ROWS
    rows = [[(round(v, 6) if isinstance(v, float) else (v.decode(errors="replace")[:200] if isinstance(v, bytes) else v))
             for v in r] for r in rows[:MAX_ROWS]]
    out = {"columns": cols, "rows": rows, "truncated": more}
    s = aliases.hide(json.dumps(out, ensure_ascii=False, default=str))
    while len(s) > MAX_RESULT_CHARS and out["rows"]:
        out["rows"] = out["rows"][: max(1, len(out["rows"]) * 2 // 3)] if len(out["rows"]) > 1 else []
        out["truncated"] = True
        s = aliases.hide(json.dumps(out, ensure_ascii=False, default=str))
    return s[:MAX_RESULT_CHARS]


def catalog(dbs, tcon=None, now=None):
    """{db: {table: {"stupci": [...], "redaka": approx}}} of what may be read (MAX(rowid): approximate, fast);
    cached in critic_kv for SCHEMA_TTL_S."""
    now = int(now or time.time())
    if tcon is not None:
        hit = store.kv_get(tcon, "deep_catalog")
        if isinstance(hit, dict) and now - (hit.get("ts") or 0) < SCHEMA_TTL_S and set(hit.get("dbs") or {}) == set(dbs):
            return hit["dbs"]
    out = {}
    for name, path in dbs.items():
        try:
            con = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=5)
        except sqlite3.Error:
            continue
        try:
            tabs = {}
            for (t,) in con.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name").fetchall():
                if denied_table(t):
                    continue
                cols = [r[1] for r in con.execute(f'PRAGMA table_info("{t}")') if r[1].lower() not in DENY_COLUMNS]
                try:
                    n = con.execute(f'SELECT MAX(rowid) FROM "{t}"').fetchone()[0]
                except sqlite3.Error:
                    n = None
                tabs[t] = {"stupci": cols, "redaka": n}
            if tabs:
                out[name] = tabs
        except sqlite3.Error:
            pass
        finally:
            con.close()
    if tcon is not None:
        store.kv_put(tcon, "deep_catalog", {"ts": now, "dbs": out})
    return out


def player_names(lpath=None):
    """The players' names (UI_USERS and the registered members, league.db read-only): replaced in every result."""
    from trade import settings
    names = set()
    try:
        from league import store as lstore
        names |= {u for u in lstore.env_users() if u}
        con = cdata._ro(lpath or lstore.DB)
        if con is not None:
            try:
                names |= {r[0] for r in con.execute("SELECT name FROM members") if r[0]}
            except sqlite3.Error:
                pass
            finally:
                con.close()
    except Exception:  # noqa: BLE001
        pass
    return {n for n in names if n not in (settings.LEAGUE_USER, settings.PAPER_USER)}


def learned_exits(tcon, now, dbs):
    """The learned per-source exits (izlazi/, nightly): izlazi.report.critic_summary (priors, the sources with the
    biggest out-of-sample gain and every proven one: params, n, n_out, EV out vs default, intervals, the source's
    behaviour), else the raw learned_exits rows of whichever database has that table. None before the first night."""
    try:
        from izlazi import report as izreport
        d = izreport.critic_summary(top=30)
        if d and d.get("available", True) is not False:   # before the first night: the table scan below (None)
            return d
    except Exception:  # noqa: BLE001 - fall back to the table itself
        pass
    for name, path in dbs.items():
        try:
            con = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=5)
        except sqlite3.Error:
            continue
        try:
            if not con.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='learned_exits'").fetchone():
                continue
            cur = con.execute("SELECT * FROM learned_exits ORDER BY rowid DESC LIMIT 40")
            cols = [c[0] for c in cur.description]
            keep = [i for i, c in enumerate(cols) if c.lower() not in DENY_COLUMNS]
            rows = [[r[i] for i in keep] for r in cur.fetchall()]
            n = con.execute("SELECT COUNT(*) FROM learned_exits").fetchone()[0]
            return {"baza": name, "redaka": n, "stupci": [cols[i] for i in keep], "zadnji": rows}
        except sqlite3.Error:
            continue
        finally:
            con.close()
    return None


# the deep session's input blocks besides the catalog: (key, fn(tcon, now, dbs) -> JSON-able or None); one more
# summary is one more line here (a None answer or an error leaves its key out)
CONTEXT_BLOCKS = [
    ("strategije_30d", lambda tcon, now, dbs: cdata.strategy_stats(tcon, now, 30)),
    ("pravila_i_stropovi", lambda tcon, now, dbs: cdata.rules(None)),
    ("makro", lambda tcon, now, dbs: cdata.makro(now)),
    ("odbijeni_prijedlozi", lambda tcon, now, dbs: cnotes.rejected_titles(tcon, now=now)),
    ("naucni_izlazi_po_izvoru", learned_exits),
    # 15.11. (konsenzus/): the source consensus walk-forward: holdout per candidate, the decision, the demo so far
    ("konsenzus_izvora", lambda tcon, now, dbs: __import__("konsenzus.view", fromlist=["critic_summary"]).critic_summary()),
    # 15.11. (oscilator/): the oscillator scalp: walk-forward per size (top 10 of day D traded on D+1), the range scalp on
    # the same token-days, the demo so far, the real-money decision
    ("oscilator", lambda tcon, now, dbs: __import__("oscilator.view", fromlist=["critic_summary"]).critic_summary()),
    # 15.11. (veliki/): the big tokens' range: holdout per size without / with BTC crashes, the demo, the decision
    ("veliki_tokeni_range", lambda tcon, now, dbs: __import__("veliki.view", fromlist=["critic_summary"]).critic_summary()),
]


def context(tcon, now, dbs, cat, log=print):
    out = {"vrijeme_utc": time.strftime("%Y-%m-%d %H:%M", time.gmtime(now)), "baze": cat}
    for key, fn in CONTEXT_BLOCKS:
        try:
            v = fn(tcon, now, dbs)
        except Exception as e:  # noqa: BLE001 - one block costs only itself
            log(f"kritičar: dubinski blok {key} nije složen ({type(e).__name__}: {e})", flush=True)
            continue
        if v is not None:
            out[key] = v
    return out


def due(tcon, now, night_fn=None):
    """(run now, why): the first session once, then every EVERY_H hours inside the night window."""
    if not store.kv_get(tcon, "deep_first"):
        return True, "prvi dubinski pregled nakon deploya"
    last = store.kv_get(tcon, "deep_last") or {}
    if now - int(last.get("ts") or 0) < EVERY_H * 3600:
        return False, None
    if night_fn is None:
        from ops import heavy
        night_fn = heavy.night_now
    return (True, "redovni dubinski pregled") if night_fn() else (False, None)


def validate(d):
    sazetak, _st, nalazi, nedostaje = __import__("critic.daily", fromlist=["validate"]).validate(
        {"sazetak": d.get("sazetak") if isinstance(d, dict) else None, "strategije": [],
         "nalazi": (d or {}).get("nalazi"), "nedostaje_mjerenje": (d or {}).get("nedostaje_mjerenje")})
    eks = []
    for x in d.get("eksperimenti") or []:
        if isinstance(x, dict) and str(x.get("naziv") or "").strip():
            eks.append({k: (str(x.get(k) or "").strip()[:500] if k not in ("n_potreban", "dana") else x.get(k))
                        for k in ("naziv", "hipoteza", "kako", "n_potreban", "dana")})
    kc = d.get("koliko_cesto") if isinstance(d.get("koliko_cesto"), dict) else {}
    return sazetak, nalazi, eks[:7], {"preporuka": str(kc.get("preporuka") or "")[:200],
                                      "razlog": str(kc.get("razlog") or "")[:500]}, nedostaje


def run(now=None, log=print, tcon=None, auto=False, send=None, root=None, night_fn=None, sleep=time.sleep):
    """One deep session (auto: only when due()). Returns a small dict."""
    from critic import trades as ctrades
    now = int(now or time.time())
    own = tcon is None
    if own:
        from trade import executor, settings
        tcon = executor.connect(settings.DB)
    try:
        store.ensure(tcon)
        if not ctrades.enabled(tcon):
            return {"skip": "isključen"}
        if not openai_api.has_key():
            ctrades.nokey_line(tcon, now, log)
            return {"skip": "nema ključa"}
        if auto:
            go, why = due(tcon, now, night_fn)
            if not go:
                return {"skip": "nije na redu"}
        store.kv_put(tcon, "deep_first", {"ts": now})   # the first session runs once, whatever happens next
        dbs = databases(root)
        cat = catalog(dbs, tcon, now)
        aliases = Aliases(player_names(os.path.join(root, "league.db") if root else None))
        ctx = context(tcon, now, dbs, cat, log)
        wallets = privacy.owner_wallets(tcon)
        text = privacy.scrub(aliases.hide(prompts.DEEP + "\n\nPodaci (JSON):\n" + json.dumps(
            ctx, ensure_ascii=False, separators=(",", ":"), default=str)), (), extra=wallets)
        if privacy.leaks(text, (), extra=wallets):
            log("kritičar: dubinski pregled nije poslan (privatnost)", flush=True)
            return {"skip": "privatnost"}
        model = openai_api.MODEL_DEEP
        conv = [{"role": "user", "content": text}]
        send = send or openai_api.send
        spent, queries, turns, final = 0.0, 0, 0, None
        prev_in = 0
        while turns < MAX_TURNS:
            chars = len(prompts.SYSTEM) + sum(len(json.dumps(x, ensure_ascii=False)) for x in conv)
            pin, pcached, pout = openai_api.price(model)
            new_chars = max(0, chars - prev_in * 3)
            est_turn = (prev_in * pcached + new_chars / 3.0 * pin + TURN_OUT * pout) / 1e6
            est_final = (chars / 3.0 * pin + FINAL_OUT * pout) / 1e6
            last_turn = queries >= MAX_QUERIES or spent + est_turn + est_final > store.DEEP_USD
            est = est_final if last_turn else est_turn
            if spent + est > store.DEEP_USD or store.refusal(tcon, "deep", est, now, log):
                if not turns:
                    return {"skip": "budžet"}
                log(f"kritičar: dubinski pregled prekinut (strop sesije, potrošeno {spent:.3f} $)", flush=True)
                break
            b = openai_api.body(model, prompts.SYSTEM, conv, prompts.DEEP_SCHEMA, "kriticar_dubinski",
                                FINAL_OUT if last_turn else TURN_OUT, EFFORT, tools=[SQL_TOOL])
            if last_turn:
                b["tool_choice"] = "none"
            try:
                resp = send(b)
            except openai_api.ApiError as e:
                c = openai_api.cost(e.model or model, e.usage) if e.usage else 0.0
                store.book(tcon, "deep", e.model or model, e.usage, c, False, str(e), text, now=now)
                log(f"kritičar: dubinski pregled nije uspio ({e}), upita {queries}, trošak {spent + c:.3f} $", flush=True)
                return {"skip": "greška API-ja", "greska": str(e), "upita": queries}
            turns += 1
            usage = openai_api.usage_of(resp)
            used = resp.get("model") or model
            c = openai_api.cost(used, usage)
            spent += c
            prev_in = usage.get("in") or 0
            calls = openai_api.function_calls(resp)
            store.book(tcon, "deep", used, usage, c, True, None, text, n=len(calls), now=now)
            if not calls:
                final = resp
                break
            for fc in calls:
                conv.append({"type": "function_call", "call_id": fc["call_id"], "name": fc["name"],
                             "arguments": fc["arguments"]})
                if queries >= MAX_QUERIES:
                    out = json.dumps({"error": f"dosegnut je najveći broj upita ({MAX_QUERIES}); daj završni odgovor"})
                else:
                    try:
                        a = json.loads(fc["arguments"] or "{}")
                    except ValueError:
                        a = {}
                    out = run_sql(dbs, str(a.get("db") or ""), str(a.get("query") or ""), aliases) \
                        if fc["name"] == "sql" else json.dumps({"error": "nepoznat alat"})
                    queries += 1
                    sleep(QUERY_PAUSE_S)
                conv.append({"type": "function_call_output", "call_id": fc["call_id"],
                             "output": privacy.scrub(out, (), extra=wallets)})
        if final is None:
            return {"skip": "bez završnog odgovora", "upita": queries, "cost_usd": round(spent, 4)}
        try:
            res = openai_api.parse_json(final, model)
            sazetak, nalazi, eks, kc, nedostaje = validate(res["data"])
        except (openai_api.ApiError, ValueError) as e:
            log(f"kritičar: dubinski pregled neispravan ({e}), upita {queries}, trošak {spent:.3f} $", flush=True)
            return {"skip": "neispravan odgovor", "greska": str(e), "upita": queries}
        ids = []
        for f in nalazi:
            try:
                ids.append(cnotes.store_finding(tcon, f, res["model"]))
            except ValueError as e:
                log(f"kritičar: dubinski nalaz „{f['naslov'][:60]}” nije zapisan ({e})", flush=True)
        from zoneinfo import ZoneInfo
        day = dt.datetime.fromtimestamp(now, ZoneInfo("Europe/Zagreb")).strftime("%d.%m.")
        parts = [sazetak]
        if nalazi:
            parts.append("Nalazi: " + "; ".join(f"[{f['ozbiljnost']}] {f['naslov']}" for f in nalazi))
        if eks:
            parts.append("Eksperimenti: " + "; ".join(f"{e['naziv']}: {e['hipoteza']} (n {e.get('n_potreban')}, "
                                                      f"{e.get('dana')} dana)" for e in eks))
        if kc.get("preporuka"):
            parts.append(f"Koliko često: {kc['preporuka']} ({kc['razlog']})")
        if nedostaje:
            parts.append("Nedostaje mjerenje: " + "; ".join(nedostaje))
        parts.append(f"Upita: {queries}, poziva: {turns}, trošak {spent:.3f} $ ({res['model']}).".replace(".", ",", 1))
        try:
            cnotes.store_summary(tcon, f"{cnotes.LABEL}: Dubinski pregled {day}", "\n\n".join(parts),
                                 {"kriticar": "openai", "vrsta": "dubinski", "model": res["model"], "upita": queries,
                                  "eksperimenti": eks, "koliko_cesto": kc, "nalazi_id": ids})
        except ValueError as e:
            log(f"kritičar: dubinski sažetak nije zapisan ({e})", flush=True)
        store.kv_put(tcon, "deep_last", {"ts": now, "nalaza": len(ids), "upita": queries, "usd": round(spent, 4),
                                         "koliko_cesto": kc.get("preporuka")})
        from critic.daily import log_findings
        log_findings(log, "dubinski", sazetak, nalazi, (), [
            "koliko često: " + f"{kc.get('preporuka')} ({kc.get('razlog')})" if kc.get("preporuka") else "",
            *[f"eksperiment {e.get('naziv')}: {e.get('hipoteza')}" for e in (eks or [])]])
        log(f"kritičar: dubinski pregled spremljen, {len(ids)} nalaza, upita {queries}, trošak {spent:.3f} $ "
            f"({turns} poziva, {res['model']})", flush=True)
        return {"nalaza": len(ids), "upita": queries, "cost_usd": round(spent, 4), "poziva": turns}
    finally:
        if own:
            tcon.close()
