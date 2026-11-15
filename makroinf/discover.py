"""The expansion to 300-500 macro accounts BY THE OWNER'S ORDER (15.11.2026. navečer, in the chat: "I želim veliku
listu makroinfluencera, sve ih dodati u bazu i sve ih pratiti na dnevnom nivou ... pratiti ih 300, 400, 500 ovih
najredovitijih. Ima i ovaj Marty Party ... Ima onaj Adam, influencer koji ima statistike te razne").

The quality gate of the expansion (makroinf/quality.gate: the classification check must pass first) is OVERRIDDEN by
this explicit order: record_order() writes it once (kv nalog_prosirenje, the runs table, a log line with his words and
the state of the check), opens the gate through quality.force_by_order (the DEMO input of the index is NOT opened by
it: index.input_state still needs a passed check or his separate force) and sets the expansion's one-off caps
(twitterapi 40 $, OpenAI 15 $, store.left "prosirenje"). config expand_by_order = False stops it.

Discovery (kv "otkrivanje" holds the step, every step resumes after a deploy; twitterapi under the expansion cap):
  pratitelji   who our measured accounts follow (followings, disc_follow_pages pages of 200 each, ~0,002 $ a page);
               round 2 (only when round 1 found too few): one page of each account round 1 added
  spominjanja  who our accounts mention or quote most in their stored posts (local, free)
  pretraga     user search for macro / BTC / crypto analysts (SEARCHES)
  adam         the owner's "Adam ... statistike": the three best candidates stored as needs_owner_confirm; the clearly
               best one (strong evidence: a statistics / data account, 50k+ followers, active, >= 20 % market posts,
               well ahead of the second) is measured as source vlasnik_kandidat until he confirms or removes it
  profili      profiles of the most mentioned accounts we only know by name (user info)
  proba        one page of the newest posts of the best-scored eligible candidates (100k+ followers, a crypto / macro
               bio or followed by 3+ of ours, no promo / bot bio, not an exchange or a project): active in 30 days,
               >= 20 % market posts, <= 50 % promo posts; its posts are stored (src proba) and reused by the backfill
  odabir       the passing candidates by REGULARITY (market posts a day of their newest posts, capped at 8), the most
               regular first, until expand_n (500) accounts are measured
estimate() is the cost before anything is spent (logged with the order and stored in kv procjena); phase_spend() is
what each phase really cost (the hourly line and the owner's card).
"""
import json
import math
import re
import time

from makroinf import fetch, quality, racuni, store, xapi

D = 86400
PH = "prosirenje"
ORDER = {"id": "prosirenje-1511-navecer", "kada": "15.11.2026. navečer", "tko": "vlasnik (nalog u chatu)",
         "citat": "I želim veliku listu makroinfluencera, sve ih dodati u bazu i sve ih pratiti na dnevnom nivou i "
                  "akumulirati njihova mišljenja, postove, svaki dan skrepat njihove nove postove ... pratiti ih 300, "
                  "400, 500 ovih najredovitijih."}
SEARCHES = ("crypto macro analyst", "bitcoin macro", "crypto analyst", "bitcoin analyst", "crypto trader",
            "on-chain analyst", "bitcoin on-chain", "crypto market data", "crypto statistics", "bitcoin charts",
            "altcoin analyst", "crypto economist", "macro investor bitcoin", "crypto research", "ethereum analyst",
            "solana trader", "crypto technical analysis", "bitcoin cycle")
ADAM = "Adam (statistike)"
# Pretpostavka (no request made from the sandbox): the best known accounts of an "Adam" who posts market statistics
ADAM_PRIOR = (("KobeissiLetter", 3.0, "The Kobeissi Letter (Adam Kobeissi): svakodnevne statistike i grafovi tržišta"),
              ("AdamBLiv", 2.0, "Adam Livingston: statistike i grafovi BTC-a"),
              ("adamscochran", 1.0, "Adam Cochran: analize tržišta s podacima"))
ADAM_SEARCHES = ("Adam market statistics", "Adam crypto data", "Adam bitcoin charts")
STATS_BIO = re.compile(r"stat|data|chart|research|letter|analy|metric|on-?chain|macro|quant", re.I)
PROMO_BIO = re.compile(r"giveaway|airdrop hunter|dm (me )?for (promo|collab|business|ads)|paid promo|promotion|"
                       r"follow ?back|\bf4f\b|100x gem|vip (group|signals)|signals? group|join (my|our) (telegram|discord)",
                       re.I)
NOT_PERSON = re.compile(r"official (account|twitter|page|x)|\bexchange\b|\bwallet\b|\bprotocol\b|\bfoundation\b|"
                        r"\blayer ?[12]\b|\bdex\b|\bnft collection\b|\bmainnet\b|\btestnet\b", re.I)
PROMO_POST = re.compile(r"giveaway|airdrop|referral|use (my )?code|sign ?up (here|now|with)|join (now|my|our)|"
                        r"discount|deposit bonus|link in bio|\bpromo\b|sponsored|\bad\b:", re.I)
PRICE = {"post": 0.00015, "user": 0.00018, "follow_page": 0.002, "min_req": 0.00015}
DEFAULT_FILL = 0.75          # Pretpostavka until measured: share of depth_posts an account really has in 18 months
DEFAULT_CLS_POST = 0.00006   # Pretpostavka until measured: OpenAI $ per classified post (pilot ~0,04 $ / 1000)
DEFAULT_DAY_POSTS = 4.0      # Pretpostavka until measured: new market posts per account a day


# ---------- the owner's order ------------------------------------------------------------------------------------------

def ordered(con, c=None):
    """The order is in force (recorded and not stopped by config)."""
    c = c or store.config()
    return bool(c.get("expand_by_order")) and bool(store.kv(con, "nalog_prosirenje"))


def record_order(con, c=None, now=None, log=print):
    """Once: the owner's order is recorded, the quality gate overridden by it, the expansion caps set, the estimate
    logged. True while the order is in force."""
    c = c or store.config()
    now = int(now or time.time())
    if not c.get("expand_by_order"):
        return False
    if store.kv(con, "nalog_prosirenje"):
        return True
    q = store.kv_json(con, "provjera", {}) or {}
    rec = {"id": ORDER["id"], "ts": now, "kada": ORDER["kada"], "tko": ORDER["tko"], "citat": ORDER["citat"],
           "provjera_nadjacana": not q.get("passed"),
           "provjera": {"passed": bool(q.get("passed")), "why": q.get("why") or "još nije odrađena"},
           "cilj": int(c["expand_n"]), "najmanje": int(c["expand_min"]),
           "strop_twapi_usd": float(c["expand_twapi_usd"]), "strop_openai_usd": float(c["expand_openai_usd"])}
    quality.force_by_order(con, ORDER["tko"], ORDER["id"], now)
    store.kv(con, "nalog_prosirenje", rec)
    store.kv(con, "prosirenje", {"ts": now, "twapi_usd": float(c["expand_twapi_usd"]),
                                 "openai_usd": float(c["expand_openai_usd"]), "who": ORDER["tko"], "nalog": ORDER["id"]})
    con.execute("INSERT INTO runs VALUES (?,?,?)", (now, "nalog_prosirenje", json.dumps(rec, ensure_ascii=False)))
    est = estimate(con, c, now)
    store.kv(con, "procjena", est)
    con.commit()
    gate = ("provjera klasifikacije NIJE prošla (" + rec["provjera"]["why"] + "): vrata proširenja nadjačana vlasnikovim "
            "izričitim nalogom" if rec["provjera_nadjacana"] else "provjera klasifikacije prošla")
    log(store.PREFIX + f"proširenje po nalogu vlasnika ({ORDER['kada']}: „{ORDER['citat'][:90]}…”): {gate}; cilj "
                       f"{rec['cilj']} računa (najmanje {rec['najmanje']}), strop twitterapi {_usd(rec['strop_twapi_usd'])}, "
                       f"OpenAI {_usd(rec['strop_openai_usd'])}; ulaz indeksa u demo ostaje na svojim vratima")
    log(estimate_line(est, c))
    return True


# ---------- the estimate (before the money) and the spend per phase ----------------------------------------------------

def _measured(con, c):
    """(fill of depth_posts, OpenAI $ a classified post, new market posts per account a day) from what is stored,
    the defaults (Pretpostavka) where nothing is measured yet."""
    cap = int(c.get("depth_posts") or 500)
    full = [fetch.depth(con, h) for (h,) in store.q(con, """SELECT handle FROM accounts a WHERE status = 'aktivan' AND
        EXISTS (SELECT 1 FROM fetch_log f WHERE f.handle = a.handle AND f.unit LIKE 'mj:%')""")]
    fill = min(1.0, (sum(min(x, cap) for x in full) / len(full)) / cap) if len(full) >= 5 else DEFAULT_FILL
    n_cls = (store.q(con, "SELECT COUNT(*) FROM tweets WHERE cls_ts IS NOT NULL AND cls_v NOT IN ('predfiltar', "
                          "'propusteno')") or [[0]])[0][0]
    usd = sum(store.spent(con, "openai", ph) for ph in ("pilot", "dan", PH)) - store.spent(con, "openai", "dan",
                                                                                           what="teme")
    per = (usd / n_cls) if n_cls >= 500 and usd > 0 else DEFAULT_CLS_POST
    r = store.q(con, "SELECT COUNT(*), COUNT(DISTINCT handle) FROM tweets WHERE src = 'dnevno' AND ts >= ?",
                (int(time.time()) - 7 * D,))
    day_posts = (r[0][0] / r[0][1] / 7) if r and r[0][1] and r[0][0] >= 50 else DEFAULT_DAY_POSTS
    return fill, per, day_posts


def estimate(con, c=None, now=None, n_new=None):
    """The expected cost of the order before anything is spent: {"twapi": {...}, "openai": {...}, "dan": {...},
    "pretpostavke": [...]} in USD (prices of kol/twapi and the measured rates of this database)."""
    c = c or store.config()
    have = len(racuni.active(con, include_new=True))
    target = int(c["expand_n"])
    n_new = max(0, target - have) if n_new is None else int(n_new)
    fill, per_cls, day_posts = _measured(con, c)
    pp = int(c["page_posts"])
    srcs = max(1, have)
    disc = (srcs * int(c["disc_follow_pages"]) * PRICE["follow_page"]
            + (len(SEARCHES) + len(ADAM_SEARCHES)) * 20 * PRICE["user"]
            + (int(c["disc_mention_lookups"]) + len(ADAM_PRIOR)) * PRICE["user"])
    probe = min(int(c["disc_probe_max"]), max(n_new * 2, 0)) * pp * PRICE["post"]
    depth_posts = int(c["depth_posts"]) * fill
    last_new = (int(c["last_pages"]) - 1) * pp            # the probe page is the first of the last 200
    deep_new = n_new * (last_new + depth_posts) * PRICE["post"]
    old_rows = store.q(con, "SELECT handle FROM accounts WHERE status = 'aktivan'")
    deep_old = 0.0
    for (h,) in old_rows:
        left_mj = len([u for u in fetch.units_left(con, c, h, now or time.time()) if u[0].startswith("mj:")])
        room = max(0, int(c["depth_posts"]) - fetch.depth(con, h))
        deep_old += min(room, left_mj * pp) * PRICE["post"]
        if fetch.units_left(con, c, h, now or time.time())[:1] == [("zadnjih+", None, None)]:
            deep_old += 100 * PRICE["post"]
    tw = {"otkrivanje": round(disc, 2), "proba": round(probe, 2), "dubina_novi": round(deep_new, 2),
          "dubina_postojeci": round(deep_old, 2)}
    tw["ukupno"] = round(sum(tw.values()), 2)
    kw_new = n_new * (depth_posts + last_new * 0.5)       # the last 200: about half are market posts (pilot)
    kw_old = deep_old / PRICE["post"]
    oa = {"klasifikacija": round((kw_new + kw_old) * per_cls, 2)}
    oa["ukupno"] = oa["klasifikacija"]
    n_day = have + n_new
    dan = {"twapi_dnevno": round(n_day * max(PRICE["min_req"], day_posts * PRICE["post"]), 2),
           "twapi_brisanja": round(min(2000, n_day * day_posts * 0.4) * PRICE["post"], 2),
           "twapi_profili": round(n_day / max(1, int(c["profile_every_d"])) * PRICE["user"], 2),
           "openai_klasifikacija": round(n_day * day_posts * per_cls, 2),
           "openai_teme": float(c["narr_openai_usd"])}
    dan["twapi_ukupno"] = round(dan["twapi_dnevno"] + dan["twapi_brisanja"] + dan["twapi_profili"], 2)
    dan["openai_ukupno"] = round(dan["openai_klasifikacija"] + dan["openai_teme"], 2)
    return {"ts": int(now or time.time()), "racuna_sada": have, "novih": n_new, "cilj": target, "twapi": tw,
            "openai": oa, "dan": dan, "stropovi": {"twapi": float(c["expand_twapi_usd"]),
                                                   "openai": float(c["expand_openai_usd"]),
                                                   "dan_twapi": float(c["day_twapi_usd"]),
                                                   "dan_openai": float(c["day_openai_usd"])},
            "mjereno": {"popunjenost_dubine": round(fill, 3), "openai_po_objavi": round(per_cls, 7),
                        "dnevnih_objava_po_racunu": round(day_posts, 2)},
            "pretpostavke": [f"popunjenost dubine {fill:.0%} od {c['depth_posts']} tržišnih objava",
                             f"OpenAI {per_cls * 1000:.3f} $ na 1000 objava",
                             f"{day_posts:.1f} novih tržišnih objava po računu dnevno",
                             "cijene twitterapi.io: 0,15 $ / 1000 objava, 0,18 $ / 1000 profila"]}


def _usd(x):
    return f"{(x or 0):.2f} $".replace(".", ",")


def estimate_line(e, c=None):
    c = c or store.config()
    tw, oa, dn, cap = e["twapi"], e["openai"], e["dan"], e["stropovi"]
    over = []
    if tw["ukupno"] > cap["twapi"]:
        over.append("twitterapi iznad stropa: dubina ide redom (najredovitiji prvi), ostatak pod dnevnim stropom")
    if oa["ukupno"] > cap["openai"]:
        over.append("OpenAI iznad stropa: povijest se razvrstava redom, ostatak pod dnevnim stropom")
    return (store.PREFIX + f"procjena proširenja (prije troška): {e['racuna_sada']} → {e['cilj']} računa (+{e['novih']}); "
            f"twitterapi ~{_usd(tw['ukupno'])} (otkrivanje {_usd(tw['otkrivanje'])}, proba {_usd(tw['proba'])}, dubina "
            f"novih {_usd(tw['dubina_novi'])}, postojećih {_usd(tw['dubina_postojeci'])}) uz strop {_usd(cap['twapi'])}; "
            f"OpenAI ~{_usd(oa['ukupno'])} uz strop {_usd(cap['openai'])}; dnevno ~{_usd(dn['twapi_ukupno'])} / "
            f"{_usd(cap['dan_twapi'])} twitterapi, ~{_usd(dn['openai_ukupno'])} / {_usd(cap['dan_openai'])} OpenAI"
            + (f"; {'; '.join(over)}" if over else "") + f" (Pretpostavka: {', '.join(e['pretpostavke'][:3])})")


WORK = {("twitterapi", PH): {"praćeni": "otkrivanje", "pretraga računa": "otkrivanje", "profil": "otkrivanje",
                             "proba": "proba", "zadnjih": "dubina", "zadnjih+": "dubina", "mj": "dubina"},
        ("openai", PH): {"klasifikacija": "klasifikacija", "klasifikacija (neupotrebljivo)": "klasifikacija"},
        ("twitterapi", "dan"): {"dnevno": "dnevni dohvat", "provjera brisanja": "brisanja", "profil": "profili",
                                "zadnjih": "dubina (dnevni strop)", "zadnjih+": "dubina (dnevni strop)",
                                "mj": "dubina (dnevni strop)"},
        ("openai", "dan"): {"klasifikacija": "razvrstavanje (dnevno)", "teme": "teme dana"}}


def phase_spend(con, day_=None):
    """{phase of the work: usd} of the expansion (all time) and of the day (day_, default all days)."""
    out = {}
    for src, ph, what, usd in store.q(con, "SELECT src, phase, what, SUM(usd) FROM spend WHERE phase IN (?, 'dan')"
                                           + (" AND (phase = ? OR day = ?)" if day_ else "") + " GROUP BY src, phase, what",
                                      (PH, PH, day_) if day_ else (PH,)):
        k = WORK.get((src, ph), {}).get(what) or f"{ph}: {what}"
        out[k] = round(out.get(k, 0.0) + float(usd or 0), 4)
    return out


def phase_line(con, now=None):
    now = int(now or time.time())
    sp = phase_spend(con, store.day(now))
    if not sp:
        return store.PREFIX + "trošak po fazi: još ništa"
    order = ("otkrivanje", "proba", "dubina", "klasifikacija", "dnevni dohvat", "brisanja", "profili",
             "dubina (dnevni strop)", "razvrstavanje (dnevno)", "teme dana")
    keys = [k for k in order if k in sp] + sorted(k for k in sp if k not in order)
    return store.PREFIX + "trošak po fazi (proširenje ukupno, dnevno danas): " + ", ".join(
        f"{k} {_usd(sp[k])}" for k in keys)


# ---------- discovery steps ---------------------------------------------------------------------------------------------

def _state(con):
    return store.kv_json(con, "otkrivanje", {}) or {}


def _upsert(con, u, now, seed=None):
    """A candidate from a profile payload (followings / search / user info): the canonical handle or None."""
    h = u.get("userName") or u.get("screen_name") or u.get("username")
    if not h or not racuni.HANDLE.fullmatch(h):
        return None
    fol = racuni._f(u, "followers", "followersCount", "followers_count")
    sts = racuni._f(u, "statusesCount", "statuses_count", "tweetsCount")
    raw = {k: u.get(k) for k in ("userName", "name", "id", "followers", "followersCount", "followers_count",
                                 "statusesCount", "statuses_count", "createdAt", "protected", "isProtected",
                                 "description") if u.get(k) is not None}
    raw.setdefault("userName", h)
    con.execute("""INSERT INTO disc (handle, name, followers, statuses, bio, seed, status, ts, raw) VALUES
        (?,?,?,?,?,?,'kandidat',?,?) ON CONFLICT(handle) DO UPDATE SET name = COALESCE(excluded.name, name),
        followers = COALESCE(excluded.followers, followers), statuses = COALESCE(excluded.statuses, statuses),
        bio = COALESCE(excluded.bio, bio), seed = COALESCE(seed, excluded.seed), raw = COALESCE(excluded.raw, raw)""",
                (h, u.get("name"), fol, sts, (u.get("description") or "")[:300] or None, seed, int(now),
                 json.dumps(raw, ensure_ascii=False)))
    return h


def _known(con):
    return {h.lower() for (h,) in store.q(con, "SELECT handle FROM accounts")}


def _followings(con, c, now, get, log, deadline, st):
    """Round 1: every measured account (the most regular first), disc_follow_pages pages; round 2: the accounts round 1
    added, one page. True when done (False: the deadline)."""
    prog = st.setdefault("pratitelji", {})
    if st.get("krug", 1) == 1:
        srcs = [h for h, _s in racuni.by_regularity(con, ("aktivan",))]
        pages = int(c["disc_follow_pages"])
    else:
        srcs = [h for (h,) in store.q(con, "SELECT handle FROM accounts WHERE source = 'prosirenje' AND status = "
                                           "'aktivan' ORDER BY COALESCE(regularity, -1) DESC")]
        pages = 1
    for h in srcs:
        done, cur = prog.get(h, [0, ""])
        while done < pages and cur is not None:
            if deadline and time.time() > deadline:
                st["pratitelji"] = prog
                return False
            try:
                users, cur = xapi.followings_page(con, h, PH, c, now, get, cursor=cur or "")
            except xapi.CapReached:
                st["pratitelji"] = prog
                raise
            except Exception as e:  # noqa: BLE001 - this account's followings are skipped
                log(store.PREFIX + f"otkrivanje: praćeni @{h}: {type(e).__name__}: {str(e)[:80]}")
                cur = None
                break
            for u in users:
                hh = _upsert(con, u, now)
                if hh:
                    con.execute("INSERT OR IGNORE INTO disc_edge VALUES (?,?,?)", (h.lower(), hh.lower(), "follow"))
            done += 1
            prog[h] = [done, cur]
            st["pratitelji"] = prog
            store.kv(con, "otkrivanje", st)
            con.commit()
        prog[h] = [pages, None]
    st["pratitelji"] = prog
    return True


def _mentions(con):
    """Local: who our measured accounts mention / quote (edges kind mention, one per account pair)."""
    known = _known(con)
    for h, text, qh in store.q(con, """SELECT t.handle, t.text, t.quoted_handle FROM tweets t JOIN accounts a ON
            a.handle = t.handle WHERE a.status IN ('aktivan', 'neaktivan')"""):
        names = set(re.findall(r"@([A-Za-z0-9_]{1,15})", text or ""))
        if qh:
            names.add(qh)
        for m in names:
            if m.lower() in known or m.lower() == h.lower():
                continue
            con.execute("INSERT OR IGNORE INTO disc_edge VALUES (?,?,?)", (h.lower(), m.lower(), "mention"))
    # a mentioned account we have no profile for yet: a name-only row (profili looks the best of them up)
    for (m,) in store.q(con, "SELECT dst FROM disc_edge WHERE kind = 'mention' GROUP BY dst HAVING COUNT(*) >= 2"):
        con.execute("INSERT OR IGNORE INTO disc (handle, status, ts) VALUES (?, 'kandidat', ?)", (m, int(time.time())))
    con.commit()


def _search(con, c, now, get, log, deadline, st):
    done = set(st.get("pretraga") or [])
    for qtext in SEARCHES:
        if qtext in done:
            continue
        if deadline and time.time() > deadline:
            return False
        try:
            users = xapi.user_search(con, qtext, PH, c, now, get)
        except xapi.CapReached:
            raise
        except Exception as e:  # noqa: BLE001
            log(store.PREFIX + f"otkrivanje: pretraga „{qtext}”: {type(e).__name__}: {str(e)[:80]}")
            users = []
        for u in users:
            hh = _upsert(con, u, now)
            if hh:
                con.execute("INSERT OR IGNORE INTO disc_edge VALUES (?,?,?)", (qtext, hh.lower(), "search"))
        done.add(qtext)
        st["pretraga"] = sorted(done)
        store.kv(con, "otkrivanje", st)
        con.commit()
    return True


def _lookups(con, c, now, get, log, deadline):
    """Profiles of the most mentioned name-only candidates (user info)."""
    rows = store.q(con, """SELECT d.handle, COUNT(e.src) n FROM disc d JOIN disc_edge e ON lower(e.dst) = lower(d.handle)
        AND e.kind = 'mention' WHERE d.followers IS NULL AND d.status = 'kandidat' GROUP BY d.handle
        ORDER BY n DESC, d.handle LIMIT ?""", (int(c["disc_mention_lookups"]),))
    for h, _n in rows:
        if deadline and time.time() > deadline:
            return False
        try:
            u = xapi.user(con, h, PH, c, now, get)
        except xapi.CapReached:
            raise
        except Exception:  # noqa: BLE001
            u = None
        if not u or u.get("unavailable"):
            con.execute("UPDATE disc SET status = 'odbijen', why = 'profil nedostupan' WHERE handle = ?", (h,))
        else:
            hh = _upsert(con, u, now)
            if hh and hh != h:   # the case of the handle as X writes it
                con.execute("DELETE FROM disc WHERE handle = ?", (h,))
        con.commit()
    return True


def _score(con, c):
    """Free filter and score of every candidate not probed yet: status kandidat -> spreman / odbijen (why)."""
    known = _known(con)
    ed = {}
    for dst, kind, n in store.q(con, "SELECT lower(dst), kind, COUNT(*) FROM disc_edge GROUP BY lower(dst), kind"):
        ed.setdefault(dst, {})[kind] = n
    for h, fol, bio, seed in store.q(con, "SELECT handle, followers, bio, seed FROM disc WHERE status IN ('kandidat', "
                                          "'spreman')"):
        e = ed.get(h.lower(), {})
        nf, nm, ns = e.get("follow", 0), e.get("mention", 0), e.get("search", 0)
        bio = bio or ""
        why = None
        if h.lower() in known:
            why = "već u bazi"
        elif fol is None:
            why = "bez profila"
        elif fol < int(c["min_followers"]):
            why = f"ispod {int(c['min_followers']) // 1000}k pratitelja"
        elif PROMO_BIO.search(bio):
            why = "promo / bot opis"
        elif NOT_PERSON.search(bio) and nf < 5:
            why = "projekt / burza, ne analitičar"
        elif not (racuni.CRYPTO_BIO.search(bio) or STATS_BIO.search(bio)) and nf < 3 and nm < 3:
            why = "opis nije kripto / makro"
        sc = nf + 0.7 * nm + 0.5 * min(ns, 2) + (1.0 if (racuni.CRYPTO_BIO.search(bio) or STATS_BIO.search(bio)) else 0) \
            + (math.log10(fol) / 10 if fol else 0)
        con.execute("UPDATE disc SET n_follow = ?, n_mention = ?, n_search = ?, score = ?, status = ?, why = ? WHERE "
                    "handle = ?", (nf, nm, ns, round(sc, 3), "odbijen" if why else "spreman", why, h))
    con.commit()


def probe_one(con, c, h, now, get, ph=PH):
    """One page of the account's newest posts (stored, src proba): {"n", "last_ts", "posts_day", "market_share",
    "promo_share", "regularity"}."""
    _new, _seen = fetch._pages(con, c, f"from:{h} -filter:retweets", 1, ph, h, "proba", now, get)
    rows = store.q(con, "SELECT ts, kw, text, fetched_ts FROM tweets WHERE handle = ? AND src IN ('proba', 'zadnjih') "
                        "ORDER BY ts DESC LIMIT 20", (h,))
    if not rows:
        return {"n": 0}
    end = max(int(r[3] or r[0]) for r in rows)
    span = max(1.0, (end - rows[-1][0]) / D)
    pd = len(rows) / span
    share = sum(1 for r in rows if r[1]) / len(rows)
    promo = sum(1 for r in rows if PROMO_POST.search(r[2] or "")) / len(rows)
    return {"n": len(rows), "last_ts": rows[0][0], "posts_day": round(pd, 3), "market_share": round(share, 3),
            "promo_share": round(promo, 3), "regularity": round(min(pd * share, fetch.REG_CAP), 3)}


def _verdict(p, c, now):
    if p["n"] < 3:
        return "premalo objava"
    if p["last_ts"] < now - int(c["active_days"]) * D:
        return f"bez objave u {c['active_days']} dana"
    if p["market_share"] < float(c["min_market_share"]):
        return f"tržišnih objava {p['market_share']:.0%} (< {float(c['min_market_share']):.0%})"
    if p["promo_share"] > float(c["max_promo_share"]):
        return f"promo objava {p['promo_share']:.0%}"
    return None


def _probe(con, c, now, get, log, deadline, need):
    """Probe the best-scored ready candidates until enough pass (2x the need, at most disc_probe_max probes)."""
    probed = (store.q(con, "SELECT COUNT(*) FROM disc WHERE probe_ts IS NOT NULL AND COALESCE(seed, '') <> 'adam'")
              or [[0]])[0][0]
    passing = (store.q(con, "SELECT COUNT(*) FROM disc WHERE status = 'probano'") or [[0]])[0][0]
    rows = store.q(con, """SELECT handle FROM disc WHERE status = 'spreman' AND probe_ts IS NULL AND (n_follow >= ? OR
        n_mention >= 2 OR n_search >= 1) ORDER BY score DESC, followers DESC""", (int(c["disc_probe_min_followed"]),))
    for (h,) in rows:
        if probed >= int(c["disc_probe_max"]) or passing >= 2 * need:
            break
        if deadline and time.time() > deadline:
            return False
        try:
            p = probe_one(con, c, h, now, get)
        except xapi.CapReached:
            raise
        except Exception as e:  # noqa: BLE001
            log(store.PREFIX + f"otkrivanje: proba @{h}: {type(e).__name__}: {str(e)[:80]}")
            con.execute("UPDATE disc SET probe_ts = ?, status = 'odbijen', why = 'proba nije uspjela' WHERE handle = ?",
                        (int(now), h))
            con.commit()
            continue
        probed += 1
        why = _verdict(p, c, now)
        passing += 0 if why else 1
        con.execute("""UPDATE disc SET probe_ts = ?, n_probe = ?, last_ts = ?, posts_day = ?, market_share = ?,
            promo_share = ?, regularity = ?, status = ?, why = ? WHERE handle = ?""",
                    (int(now), p["n"], p.get("last_ts"), p.get("posts_day"), p.get("market_share"), p.get("promo_share"),
                     p.get("regularity"), "odbijen" if why else "probano", why, h))
        con.commit()
    return True


def _add(con, c, h, now, source, note):
    r = store.q(con, "SELECT name, bio, raw FROM disc WHERE handle = ?", (h,))
    name, bio, raw = r[0] if r else (h, "", "{}")
    try:
        u = json.loads(raw or "{}")
    except ValueError:
        u = {}
    con.execute("INSERT OR IGNORE INTO accounts (handle, name, category, source, status, owner_seed, added_ts, note) "
                "VALUES (?,?,?,?,?,?,?,?)", (h, name or h, racuni.guess_category(bio or ""), source, "novo", 0, now, note))
    if u:
        racuni.apply_profile(con, h, u, c, now)
    reg = store.q(con, "SELECT posts_day, market_share, regularity FROM disc WHERE handle = ?", (h,))
    if reg:
        con.execute("UPDATE accounts SET posts_day = ?, market_share = ?, regularity = ? WHERE handle = ?", (*reg[0], h))
    con.execute("UPDATE disc SET status = 'dodan' WHERE handle = ?", (h,))


def _select(con, c, now, log):
    """Add the most regular passing candidates until expand_n accounts are measured. Returns the handles added."""
    have = len(racuni.active(con, include_new=True))
    need = max(0, int(c["expand_n"]) - have)
    rows = store.q(con, """SELECT handle, n_follow, n_mention, n_search, posts_day, market_share, regularity FROM disc
        WHERE status = 'probano' ORDER BY regularity DESC, followers DESC, handle LIMIT ?""", (need,))
    added = []
    for h, nf, nm, ns, pd, ms, reg in rows:
        src = ", ".join(x for x in (f"prati ga {nf} naših" if nf else "", f"spominje ga {nm} naših" if nm else "",
                                    "pretraga" if ns else "") if x)
        _add(con, c, h, now, "prosirenje", f"otkriven ({src}); {reg:.1f} tržišnih objava dnevno, {ms:.0%} objava o "
                                           "tržištu; kategorija iz opisa (Pretpostavka)")
        added.append(h)
    con.commit()
    return added


# ---------- the owner's "Adam" ------------------------------------------------------------------------------------------

def _adam(con, c, now, get, log):
    """Candidates for the owner's "Adam ... statistike": the prior accounts and user search; the three best stored as
    needs_owner_confirm; the clearly best one measured until he confirms or removes it. Returns the handle included or
    None."""
    own = racuni.owner_file()
    if (own.get("potvrdi") or {}).get(ADAM):   # he already chose: racuni.seed adds his pick
        return None
    if not store.q(con, "SELECT 1 FROM accounts WHERE handle = ?", (f"?{ADAM}",)):
        con.execute("INSERT INTO accounts (handle, name, category, source, status, why, owner_seed, added_ts) VALUES "
                    "(?,?,?,?,?,?,?,?)", (f"?{ADAM}", ADAM, "makro", "vlasnik", "needs_owner_confirm",
                                          "vlasnik: „Adam, influencer koji ima statistike”; kandidati čekaju potvrdu", 1,
                                          now))
    prior = {h.lower(): (w, why) for h, w, why in ADAM_PRIOR}
    found = {}
    for h, _w, _why in ADAM_PRIOR:
        try:
            u = xapi.user(con, h, PH, c, now, get)
        except xapi.CapReached:
            raise
        except Exception:  # noqa: BLE001
            u = None
        if u and not u.get("unavailable"):
            hh = _upsert(con, u, now, seed="adam")
            if hh:
                found[hh] = u
    for qtext in ADAM_SEARCHES:
        try:
            users = xapi.user_search(con, qtext, PH, c, now, get)
        except xapi.CapReached:
            raise
        except Exception:  # noqa: BLE001
            users = []
        for u in users:
            h = u.get("userName") or u.get("screen_name") or ""
            if "adam" in f"{h} {u.get('name') or ''}".lower():
                hh = _upsert(con, u, now, seed="adam")
                if hh:
                    found.setdefault(hh, u)
    scored = []
    for h, u in found.items():
        bio = u.get("description") or ""
        fol = racuni._f(u, "followers", "followersCount", "followers_count") or 0
        try:
            p = probe_one(con, c, h, now, get)
        except xapi.CapReached:
            raise
        except Exception:  # noqa: BLE001
            p = {"n": 0}
        verdict = _verdict(p, c, now) if p.get("n") else "bez objava"
        w, why = prior.get(h.lower(), (0.0, "pretraga: ime Adam"))
        stats = bool(STATS_BIO.search(bio))
        # the prior (who is known to be an "Adam" posting statistics) x1.5, a statistics / data bio, the reach
        # (log10 of the followers), the share of market posts x2; the name only for a candidate found by search
        sc = 1.5 * w + (2.0 if stats else 0) + math.log10(max(fol, 1)) + 2 * (p.get("market_share") or 0) \
            + (1.0 if not w and "adam" in f"{h} {u.get('name') or ''}".lower() else 0)
        ok = verdict is None and fol >= int(c["seed_min_followers"]) and stats
        scored.append((sc, h, u, fol, bio, why, ok, verdict, p))
        con.execute("UPDATE disc SET probe_ts = ?, n_probe = ?, last_ts = ?, posts_day = ?, market_share = ?, "
                    "promo_share = ?, regularity = ?, score = ?, status = 'adam', why = ? WHERE handle = ?",
                    (int(now), p.get("n"), p.get("last_ts"), p.get("posts_day"), p.get("market_share"),
                     p.get("promo_share"), p.get("regularity"), round(sc, 3), verdict, h))
    scored.sort(key=lambda x: -x[0])
    top = scored[:3]
    best = None
    if top and top[0][6] and (len(top) == 1 or top[0][0] - top[1][0] >= 1.5):
        best = top[0][1]
    for sc, h, u, fol, bio, why, ok, verdict, p in top:
        detail = (f"{why}; {fol:,} pratitelja; " + (f"{p.get('market_share', 0):.0%} objava o tržištu, "
                                                    f"{p.get('posts_day', 0):.1f} objava dnevno" if p.get("n") else
                                                    "bez objava u probi") + (f"; {verdict}" if verdict else ""))
        con.execute("INSERT OR REPLACE INTO candidates (handle, for_name, name, followers, bio, why, ts, status) VALUES "
                    "(?,?,?,?,?,?,?,?)", (h, ADAM, u.get("name"), fol, bio[:200], detail, now,
                                          "ukljucen_ceka_potvrdu" if h == best else "needs_owner_confirm"))
    if best and not store.q(con, "SELECT 1 FROM accounts WHERE lower(handle) = lower(?)", (best,)):
        _add(con, c, best, now, "vlasnik_kandidat", f"najbolji kandidat za „{ADAM}” (jasna prednost; Pretpostavka): "
                                                    "vlasnik potvrđuje ili miče u racuni_vlasnik.json")
    con.commit()
    log(store.PREFIX + f"kandidati za „{ADAM}”: " + (", ".join(f"@{x[1]} ({x[3]:,})" for x in top) or "nijedan")
        + (f"; uključen @{best} (jasno najbolji, čeka potvrdu vlasnika)" if best else "; nijedan jasno najbolji, svi čekaju "
           "potvrdu vlasnika"))
    return best


# ---------- the state machine -------------------------------------------------------------------------------------------

def step(con, c=None, now=None, get=None, log=print, deadline=None):
    """Advance discovery as far as the deadline and the expansion cap allow. Returns {"step", "dodano", "cap"}."""
    c = c or store.config()
    now = int(now or time.time())
    st = _state(con)
    out = {"step": st.get("step") or "pratitelji", "dodano": 0, "cap": None}
    if st.get("step") == "gotovo":
        return out
    if not xapi.has_key(get):
        out["cap"] = "nema ključa"
        return out
    st.setdefault("step", "pratitelji")
    st.setdefault("krug", 1)
    if st["step"] == "pratitelji" and not st.get("t0"):
        st["t0"] = now
        log(store.PREFIX + f"otkrivanje računa počinje (krug {st['krug']}): praćeni naših računa, spominjanja, "
                           "pretraga analitičara, vlasnikov Adam; zatim proba i odabir po redovitosti")
    try:
        while st["step"] != "gotovo":
            if deadline and time.time() > deadline:
                break
            s = st["step"]
            if s == "pratitelji":
                if not _followings(con, c, now, get, log, deadline, st):
                    break
                st["step"] = "spominjanja" if st["krug"] == 1 else "ocjena"
            elif s == "spominjanja":
                _mentions(con)
                st["step"] = "pretraga"
            elif s == "pretraga":
                if not _search(con, c, now, get, log, deadline, st):
                    break
                st["step"] = "adam"
            elif s == "adam":
                st["adam"] = _adam(con, c, now, get, log)
                st["step"] = "profili"
            elif s == "profili":
                if not _lookups(con, c, now, get, log, deadline):
                    break
                st["step"] = "ocjena"
            elif s == "ocjena":
                _score(con, c)
                st["step"] = "proba"
            elif s == "proba":
                need = max(0, int(c["expand_n"]) - len(racuni.active(con, include_new=True)))
                if not _probe(con, c, now, get, log, deadline, need):
                    break
                st["step"] = "odabir"
            elif s == "odabir":
                added = _select(con, c, now, log)
                out["dodano"] += len(added)
                st.setdefault("dodano", []).extend(added)
                total = len(racuni.active(con, include_new=True))
                if total < int(c["expand_min"]) and st["krug"] < 2 and added:
                    st.update(krug=2, step="pratitelji")
                    log(store.PREFIX + f"otkrivanje: {total} računa (< {c['expand_min']}): drugi krug, praćeni "
                                       "novododanih računa")
                else:
                    st["step"] = "gotovo"
                    st["kraj"] = now
                    log(done_line(con, c, st))
            store.kv(con, "otkrivanje", st)
            con.commit()
    except xapi.CapReached as e:
        out["cap"] = str(e)
        log(store.PREFIX + f"otkrivanje: {e}; odabir iz onoga što je probano")
        added = _select(con, c, now, log)
        out["dodano"] += len(added)
        st.setdefault("dodano", []).extend(added)
        st.update(step="gotovo", kraj=now, strop=str(e))
        log(done_line(con, c, st))
    store.kv(con, "otkrivanje", st)
    con.commit()
    out["step"] = st["step"]
    return out


def done_line(con, c, st):
    n = dict(store.q(con, "SELECT status, COUNT(*) FROM disc GROUP BY status"))
    probed = (store.q(con, "SELECT COUNT(*) FROM disc WHERE probe_ts IS NOT NULL") or [[0]])[0][0]
    total = len(racuni.active(con, include_new=True))
    mp = store.q(con, "SELECT handle, status, why FROM accounts WHERE lower(handle) = 'martypartymusic'")
    mp_txt = (f"Marty Party @{mp[0][0]}: {mp[0][1]}" + (f" ({mp[0][2]})" if mp[0][2] else "")) if mp else \
        "Marty Party: nije u bazi"
    return (store.PREFIX + f"otkrivanje gotovo: {sum(n.values())} kandidata, probano {probed} (prošlo "
            f"{n.get('probano', 0) + n.get('dodan', 0)}), odbijeno {n.get('odbijen', 0)}; dodano "
            f"{len(st.get('dodano') or [])}, mjeri se {total} računa (cilj {c['expand_n']}); {mp_txt}; Adam: "
            + (f"@{st['adam']} uključen, čeka potvrdu" if st.get("adam") else "kandidati čekaju potvrdu")
            + (f"; {st['strop']}" if st.get("strop") else ""))


def in_progress(con, c=None):
    """The order still has work under its own caps: discovery not done, history units left before the twitterapi
    cap, or history posts to classify before the OpenAI cap (then run_makroinf.py asks for the next round in a
    minute; the rest under the daily caps goes at the normal pace)."""
    from makroinf import classify
    c = c or store.config()
    if not ordered(con, c):
        return False
    if (_state(con).get("step") or "") != "gotovo":
        return True
    if not store.kv(con, "prosirenje_dubina_gotova") and not store.kv(con, "prosirenje_strop_twapi"):
        return True
    return bool(not store.kv(con, "prosirenje_strop_openai") and
                classify.pending(con, 1, expansion=None, which="povijest"))


def summary(con):
    """For the owner's card and MCP: the order, the discovery state, the estimate and the spend per phase."""
    st = _state(con)
    n = dict(store.q(con, "SELECT status, COUNT(*) FROM disc GROUP BY status"))
    return {"nalog": store.kv_json(con, "nalog_prosirenje"), "korak": st.get("step"), "krug": st.get("krug"),
            "kandidata": sum(n.values()), "po_stanju": n, "dodano": len(st.get("dodano") or []),
            "adam": st.get("adam"), "procjena": store.kv_json(con, "procjena"), "trosak_po_fazi": phase_spend(con),
            "dubina_gotova": store.kv(con, "prosirenje_dubina_gotova")}
