"""The accounts: the seed (~50 diverse macro accounts incl. the owner's), the owner's own file racuni_vlasnik.json
(add / remove / confirm), handle resolution through twitterapi.io (followers >= min_followers: 100k, 30k since the
owner's order of 16.11.; active in the last 30 days; an account the owner named or confirmed is measured whatever
its followers), the daily profile snapshot (followers, statuses_count) and the candidates for names whose handle is
unknown.

Never guessed silently: an owner name without a known handle and an owner seed whose handle does not resolve
get CANDIDATES from twitterapi.io user search, stored as needs_owner_confirm; nothing is measured for them until the
owner writes the handle into racuni_vlasnik.json "potvrdi" (or "dodaj").

Categories: ta (TA / trader), makro (makro / on-chain), edukacija (YouTube / edukacija), memecoin (memecoin KOL),
vijesti (novinar / agregator). Statuses: aktivan, odbijen (with why), neaktivan (no post in 30 days), uklonjen
(the owner), needs_owner_confirm, kandidat.
"""
import json
import os
import re
import time

from makroinf import store, xapi

CATS = {"ta": "TA / trader", "makro": "makro / on-chain", "edukacija": "YouTube / edukacija",
        "memecoin": "memecoin KOL", "vijesti": "vijesti / agregator"}
OWNER_FILE = os.path.join(store.ROOT, "makroinf", "racuni_vlasnik.json")

# (handle or None, name, category, owner's own pick). Handles of well-known public accounts; each is checked by
# twitterapi.io user info before anything is measured (a wrong / renamed handle is "odbijen", an owner pick gets
# candidates instead).
SEED = (
    # the owner's (15.11.: "Dr. Profit, InvestAnswers (+ krug s kojim nastupa), PlanB, Hani"; Hani = @honey_xbt, the
    # owner's own confirmation 15.11.: no candidates for that name)
    ("DrProfitCrypto", "Dr. Profit", "ta", True),
    ("InvestAnswers", "InvestAnswers", "edukacija", True),
    ("100trillionUSD", "PlanB", "makro", True),
    ("honey_xbt", "Hani", "ta", True),
    # 15.11. navečer, the owner: "Ima i ovaj Marty Party, on isto dobre stvari objavljuje" (handle Pretpostavka: checked
    # by the profile endpoint like every seed; if it does not resolve, candidates for the name wait for the owner)
    ("martypartymusic", "Marty Party", "makro", True),
    # TA / traders
    ("rektcapital", "Rekt Capital", "ta", False),
    ("CryptoMichNL", "Michaël van de Poppe", "ta", False),
    ("CredibleCrypto", "Credible Crypto", "ta", False),
    ("CryptoKaleo", "Kaleo", "ta", False),
    ("Pentosh1", "Pentoshi", "ta", False),
    ("CryptoCapo_", "il Capo Of Crypto", "ta", False),
    ("ali_charts", "Ali Martinez", "ta", False),
    ("DaanCrypto", "Daan Crypto Trades", "ta", False),
    ("PeterLBrandt", "Peter Brandt", "ta", False),
    ("CryptoDonAlt", "DonAlt", "ta", False),
    ("AltcoinSherpa", "Altcoin Sherpa", "ta", False),
    ("SmartContracter", "Bluntz", "ta", False),
    ("CryptoTony__", "Crypto Tony", "ta", False),
    ("TechDev_52", "TechDev", "ta", False),
    # macro / on-chain
    ("intocryptoverse", "Benjamin Cowen", "makro", False),
    ("woonomic", "Willy Woo", "makro", False),
    ("RaoulGMI", "Raoul Pal", "makro", False),
    ("CryptoHayes", "Arthur Hayes", "makro", False),
    ("ki_young_ju", "Ki Young Ju", "makro", False),
    ("krugermacro", "Alex Krüger", "makro", False),
    ("PeterSchiff", "Peter Schiff", "makro", False),
    ("APompliano", "Anthony Pompliano", "makro", False),
    ("glassnode", "glassnode", "makro", False),
    # YouTube / education
    ("LarkDavis", "Lark Davis", "edukacija", False),
    ("AltcoinDailyio", "Altcoin Daily", "edukacija", False),
    ("CryptoRover", "Crypto Rover", "edukacija", False),
    ("IvanOnTech", "Ivan on Tech", "edukacija", False),
    ("TheMoonCarl", "The Moon", "edukacija", False),
    ("scottmelker", "The Wolf Of All Streets", "edukacija", False),
    ("cryptomanran", "Ran Neuner", "edukacija", False),
    ("CryptoWendyO", "Wendy O", "edukacija", False),
    ("coinbureau", "Coin Bureau", "edukacija", False),
    # memecoin KOLs
    ("blknoiz06", "Ansem", "memecoin", False),
    ("MustStopMurad", "Murad", "memecoin", False),
    ("notthreadguy", "threadguy", "memecoin", False),
    ("frankdegods", "Frank", "memecoin", False),
    ("gainzy222", "Gainzy", "memecoin", False),
    ("ZssBecker", "Becker", "memecoin", False),
    ("Orangie", "Orangie", "memecoin", False),
    ("CryptoGodJohn", "CryptoGodJohn", "memecoin", False),
    # news / aggregators
    ("WatcherGuru", "Watcher.Guru", "vijesti", False),
    ("DeItaone", "Walter Bloomberg", "vijesti", False),
    ("lookonchain", "Lookonchain", "vijesti", False),
    ("WuBlockchain", "Wu Blockchain", "vijesti", False),
    ("BitcoinMagazine", "Bitcoin Magazine", "vijesti", False),
    ("tier10k", "db (tier10k)", "vijesti", False),
)
# handles the owner confirmed himself (15.11.: Hani = @honey_xbt; 16.11.: "https://x.com/Adam_Tehc" = the "Adam ...
# statistike" he meant, racuni_vlasnik.json potvrdi): never replaced by candidates, whatever X answers
OWNER_CONFIRMED = frozenset({"honey_xbt", "adam_tehc"})
CIRCLE_OF = ("InvestAnswers",)   # the owner: "+ people he regularly appears with" (mentions / quotes in his posts)
HANDLE = re.compile(r"[A-Za-z0-9_]{1,15}")
GUESS_CAT = (("vijesti", r"news|breaking|alert|journalist|reporter"), ("memecoin", r"meme|degen|pump|shitcoin"),
             ("makro", r"macro|on-?chain|economist|analyst|research|fund|statistic|data"),
             ("edukacija", r"youtube|podcast|show|educat|course|channel"))
CRYPTO_BIO = re.compile(r"crypto|bitcoin|btc|trad|chart|market|macro|invest|defi|web3|blockchain|altcoin", re.I)


def owner_file(path=None):
    try:
        with open(path or OWNER_FILE, encoding="utf-8") as f:
            d = json.load(f)
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def seed(con, now=None, path=None, log=None):
    """Insert the seed and the owner's file (once per handle; the owner's removals always win). Returns the number of
    accounts added this time. log: a line when the owner's confirmation of a name settles the candidate that was
    measured in the meantime."""
    now = int(now or time.time())
    n = 0
    own = owner_file(path)
    confirm = {k: v for k, v in (own.get("potvrdi") or {}).items() if v}
    rows = list(SEED) + [(x.get("handle"), x.get("name") or x.get("handle"), x.get("category") or "ta", True)
                         for x in own.get("dodaj") or [] if isinstance(x, dict)]
    for h, name, cat, mine in rows:
        h = confirm.get(name) or h
        if not h:   # an owner name without a known handle: a placeholder row, candidates come from user search
            key = f"?{name}"
            if not store.q(con, "SELECT 1 FROM accounts WHERE handle = ?", (key,)):
                con.execute("INSERT INTO accounts (handle, name, category, source, status, why, owner_seed, added_ts) "
                            "VALUES (?,?,?,?,?,?,?,?)", (key, name, cat, "vlasnik", "needs_owner_confirm",
                                                         "handle nepoznat: kandidati iz pretrage, vlasnik potvrđuje", 1, now))
                n += 1
            continue
        h = h.lstrip("@")
        if not HANDLE.fullmatch(h):
            continue
        if mine:   # the owner named the handle: a placeholder of that name and its other candidates go
            con.execute("DELETE FROM accounts WHERE handle = ?", (f"?{name}",))
            con.execute("UPDATE candidates SET status = CASE WHEN lower(handle) = lower(?) THEN 'potvrden' ELSE "
                        "'odbijen' END WHERE for_name = ?", (h, name))
        if store.q(con, "SELECT 1 FROM accounts WHERE lower(handle) = lower(?)", (h,)):
            continue
        con.execute("INSERT INTO accounts (handle, name, category, source, status, owner_seed, added_ts) VALUES "
                    "(?,?,?,?,?,?,?)", (h, name, cat if cat in CATS else "ta", "vlasnik" if mine else "sjeme", "novo",
                                        1 if mine else 0, now))
        n += 1
    named = {name for _h, name, _c, _m in rows}
    for name, h in confirm.items():   # a candidate included before his answer (discover.py) goes when he picks another
        h = str(h).lstrip("@")
        if not HANDLE.fullmatch(h):
            continue
        if name not in named:   # a name only discovery asked about (the owner's "Adam"): his pick is his account
            con.execute("DELETE FROM accounts WHERE handle = ?", (f"?{name}",))
            if store.q(con, "SELECT 1 FROM accounts WHERE lower(handle) = lower(?)", (h,)):
                con.execute("UPDATE accounts SET source = 'vlasnik', owner_seed = 1, note = ? WHERE lower(handle) = "
                            "lower(?)", (f"vlasnik potvrdio za „{name}”", h))
            else:
                con.execute("INSERT INTO accounts (handle, name, category, source, status, owner_seed, added_ts, note) "
                            "VALUES (?,?,?,?,?,?,?,?)", (h, name, "makro", "vlasnik", "novo", 1, now,
                                                         f"vlasnik potvrdio za „{name}”"))
                n += 1
        # 16.11. (the owner, on the candidate measured until his answer): "may stay as a normal account if it passes the
        # normal filters on its own, otherwise remove it"
        for (kh,) in store.q(con, "SELECT handle FROM accounts WHERE source = 'vlasnik_kandidat' AND status <> 'uklonjen' "
                                  "AND lower(handle) <> lower(?) AND lower(handle) IN (SELECT lower(handle) FROM "
                                  "candidates WHERE for_name = ?)", (h, name)):
            why = _on_its_own(con, kh, now)
            if why is None:
                con.execute("UPDATE accounts SET source = 'prosirenje', note = ? WHERE handle = ?",
                            (f"bio kandidat za „{name}” (vlasnik potvrdio @{h}); ostaje kao običan račun jer sam prolazi "
                             "uobičajene filtre", kh))
            else:
                con.execute("UPDATE accounts SET status = 'uklonjen', why = ? WHERE handle = ?",
                            (f"vlasnik potvrdio drugog kandidata; sam ne prolazi uobičajene filtre: {why}"[:200], kh))
            if log:
                log(store.PREFIX + f"vlasnik potvrdio @{h} za „{name}”: dotadašnji kandidat @{kh} "
                    + ("ostaje kao običan račun (sam prolazi uobičajene filtre)" if why is None else f"maknut ({why})")
                    + "; ostali kandidati za to ime skinuti s čekanja")
        con.execute("UPDATE candidates SET status = CASE WHEN lower(handle) = lower(?) THEN 'potvrden' ELSE 'odbijen' "
                    "END WHERE for_name = ?", (str(h).lstrip("@"), name))
    for h in own.get("makni") or []:
        con.execute("UPDATE accounts SET status = 'uklonjen', why = 'vlasnik maknuo' WHERE lower(handle) = lower(?)",
                    (str(h).lstrip("@"),))
    con.commit()
    return n


def _on_its_own(con, h, now):
    """None when the account passes the normal filters of the expansion on what is stored (discover.normal_verdict),
    else the reason."""
    try:
        from makroinf import discover
        return discover.normal_verdict(con, store.config(), h, now)
    except Exception as e:  # noqa: BLE001 - no verdict: it does not stay
        return f"provjera nije uspjela ({type(e).__name__})"


def active(con, include_new=False):
    """[(handle, category, source)] of the measured accounts."""
    sts = ("aktivan", "novo") if include_new else ("aktivan",)
    return store.q(con, f"SELECT handle, category, source FROM accounts WHERE status IN ({','.join('?' * len(sts))}) "
                        "ORDER BY owner_seed DESC, added_ts, handle", sts)


def guess_category(bio):
    """The account category from its bio (Pretpostavka; "ta" when nothing matches)."""
    return next((k for k, pat in GUESS_CAT if re.search(pat, bio or "", re.I)), "ta")


def by_regularity(con, statuses=("aktivan",)):
    """[(handle, status)] of the measured accounts, the owner's first, then the most regular (market posts a day of
    the newest posts, fetch.regularity), the unmeasured last."""
    sts = tuple(statuses)
    return store.q(con, f"SELECT handle, status FROM accounts WHERE status IN ({','.join('?' * len(sts))}) AND handle "
                        "NOT LIKE '?%' ORDER BY owner_seed DESC, COALESCE(regularity, -1) DESC, added_ts, handle", sts)


def _f(u, *keys):
    for k in keys:
        if u.get(k) is not None:
            try:
                return int(u.get(k))
            except (TypeError, ValueError):
                return None
    return None


def apply_profile(con, h, u, c, now, owner_seed=False):
    """Store one profile answer; returns the new status."""
    if u is None:
        return None
    if u.get("unavailable"):
        st, why = "odbijen", f"X: {(u.get('unavailableReason') or 'račun nedostupan')[:80]}"
        con.execute("UPDATE accounts SET status = ?, why = ?, resolved_ts = ? WHERE handle = ?", (st, why, now, h))
        return st
    fol = _f(u, "followers", "followersCount", "followers_count")
    sts = _f(u, "statusesCount", "statuses_count", "tweetsCount")
    prot = 1 if (u.get("protected") or u.get("isProtected")) else 0
    st, why = "aktivan", None
    src = (store.q(con, "SELECT source FROM accounts WHERE handle = ?", (h,)) or [[None]])[0][0]
    minf = int(c.get("seed_min_followers") or c["min_followers"]) if src == "vlasnik_kandidat" else int(c["min_followers"])
    if prot:
        st, why = "odbijen", "zaštićen račun"
    elif src == "vlasnik_kandidat" and fol is not None and fol < minf:
        st, why = "odbijen", f"ispod {minf // 1000}k pratitelja ({fol:,})"
    elif src != "vlasnik_kandidat" and fol is not None and fol < int(c["min_followers"]):
        k = int(c["min_followers"]) // 1000   # the owner's own pick is measured whatever its followers
        st, why = ("aktivan", f"vlasnikov izbor, ispod {k}k pratitelja") if owner_seed else \
            ("odbijen", f"ispod {k}k pratitelja ({fol:,})")
    con.execute("UPDATE accounts SET name = COALESCE(?, name), user_id = ?, followers = ?, statuses = ?, "
                "created_at = ?, resolved_ts = ?, protected = ?, status = CASE WHEN status IN ('novo', 'aktivan', "
                "'odbijen', 'neaktivan') THEN ? ELSE status END, why = ? WHERE handle = ?",
                (u.get("name"), str(u.get("id") or u.get("userId") or "") or None, fol, sts, u.get("createdAt"), now,
                 prot, st, why, h))
    con.execute("INSERT OR REPLACE INTO profile_d VALUES (?,?,?,?)", (h, store.day(now), fol, sts))
    return st


def resolve(con, c, now=None, get=None, log=print, ph=None, limit=None):
    """Profiles of the new accounts (and every account once in profile_every_d days: followers / statuses_count; with
    500 accounts a daily snapshot would be a tenth of the daily cap for a number that barely moves). Owner picks that
    do not resolve get candidates (find_candidates). Returns the number of profiles read."""
    now = int(now or time.time())
    if not xapi.has_key(get):
        return 0
    since = store.day(now - (max(1, int(c.get("profile_every_d") or 1)) - 1) * 86400)
    rows = store.q(con, """SELECT a.handle, a.name, a.owner_seed, a.status FROM accounts a WHERE a.handle NOT LIKE '?%'
        AND a.status IN ('novo', 'aktivan', 'neaktivan') AND NOT EXISTS (SELECT 1 FROM profile_d p WHERE p.handle =
        a.handle AND p.day >= ?) ORDER BY (a.status = 'novo') DESC, a.owner_seed DESC, a.added_ts""", (since,))
    n = 0
    for h, name, mine, _st in rows[:limit] if limit else rows:
        try:
            u = xapi.user(con, h, ph or store.phase(con, "twapi"), c, now, get)
        except xapi.CapReached as e:
            log(store.PREFIX + f"profili: {e}")
            break
        except Exception as e:  # noqa: BLE001 - one account must not stop the round
            log(store.PREFIX + f"profil @{h}: {type(e).__name__}: {str(e)[:100]}")
            continue
        n += 1
        st = apply_profile(con, h, u, c, now, bool(mine))
        if u is None:
            continue
        if st == "odbijen" and mine and h.lower() in OWNER_CONFIRMED:
            log(store.PREFIX + f"vlasnikov potvrđeni račun @{h} nije dostupan ({u.get('unavailableReason') or 'zaštićen'}); "
                               "bez kandidata, čeka vlasnika")
        elif st == "odbijen" and mine:
            find_candidates(con, c, name or h, now, get, log, ph)
    pend = store.q(con, "SELECT handle, name FROM accounts WHERE handle LIKE '?%' AND status = 'needs_owner_confirm'")
    for key, name in pend:   # a search a week at most per name (an empty answer must not repeat every round)
        if not store.q(con, "SELECT 1 FROM candidates WHERE for_name = ?", (name,)) and \
                now - float(store.kv(con, f"kandidati:{name}") or 0) >= 7 * 86400:
            store.kv(con, f"kandidati:{name}", str(now))
            find_candidates(con, c, name, now, get, log, ph)
    con.commit()
    return n


def find_candidates(con, c, name, now=None, get=None, log=print, ph=None, limit=8):
    """Candidates for an owner name (user search "<name>" and "<name> crypto"): accounts with a crypto bio or 10k+
    followers, by followers. Stored as needs_owner_confirm; never added to the measured set by themselves."""
    now = int(now or time.time())
    seen = {}
    for qtext in (name, f"{name} crypto"):
        try:
            users = xapi.user_search(con, qtext, ph or store.phase(con, "twapi"), c, now, get)
        except xapi.CapReached as e:
            log(store.PREFIX + f"kandidati: {e}")
            break
        except Exception as e:  # noqa: BLE001
            log(store.PREFIX + f"kandidati za {name}: {type(e).__name__}: {str(e)[:100]}")
            continue
        for u in users:
            h = u.get("userName") or u.get("screen_name")
            if not h or h in seen:
                continue
            fol = _f(u, "followers", "followersCount", "followers_count") or 0
            bio = (u.get("description") or "")[:200]
            if fol < 10_000 and not CRYPTO_BIO.search(bio):
                continue
            seen[h] = (u.get("name"), fol, bio, "kripto opis" if CRYPTO_BIO.search(bio) else "10k+ pratitelja")
    for h, (nm, fol, bio, why) in sorted(seen.items(), key=lambda kv: -kv[1][1])[:limit]:
        con.execute("INSERT OR IGNORE INTO candidates (handle, for_name, name, followers, bio, why, ts) VALUES "
                    "(?,?,?,?,?,?,?)", (h, name, nm, fol, bio, why, now))
    con.commit()
    if seen:
        log(store.PREFIX + f"kandidati za „{name}”: " + ", ".join(
            f"@{h} ({v[1]:,})" for h, v in sorted(seen.items(), key=lambda kv: -kv[1][1])[:limit])
            + " — čekaju potvrdu vlasnika (racuni_vlasnik.json potvrdi)")
    return len(seen)


def candidates(con):
    return [dict(zip(("handle", "for_name", "name", "followers", "bio", "why", "ts", "status"), r))
            for r in store.q(con, "SELECT handle, for_name, name, followers, bio, why, ts, status FROM candidates "
                                  "ORDER BY for_name, followers DESC")]


def circle(con, c, now=None, get=None, log=print, ph=None):
    """The owner's "+ people he regularly appears with" for CIRCLE_OF: the accounts these mention / quote most in
    their stored posts (>= circle_min_mentions), min_followers+ followers, at most circle_max; added as source krug:<who>
    (the owner can remove them in racuni_vlasnik.json). Returns the handles added."""
    now = int(now or time.time())
    added = []
    for who in CIRCLE_OF:
        if store.kv(con, f"krug:{who}"):
            continue
        rows = store.q(con, "SELECT text, quoted_handle FROM tweets WHERE lower(handle) = lower(?)", (who,))
        if len(rows) < 50:   # not fetched yet
            continue
        cnt = {}
        for text, qh in rows:
            for m in set(re.findall(r"@([A-Za-z0-9_]{1,15})", text or "")):
                cnt[m.lower()] = cnt.get(m.lower(), 0) + 1
            if qh:
                cnt[qh.lower()] = cnt.get(qh.lower(), 0) + 1
        known = {h.lower() for (h,) in store.q(con, "SELECT handle FROM accounts")}
        top = [h for h, k in sorted(cnt.items(), key=lambda kv: -kv[1])
               if k >= int(c["circle_min_mentions"]) and h not in known and h != who.lower()][:12]
        for h in top:
            if len(added) >= int(c["circle_max"]):
                break
            try:
                u = xapi.user(con, h, ph or store.phase(con, "twapi"), c, now, get)
            except xapi.CapReached:
                break
            except Exception:  # noqa: BLE001
                continue
            if not u or u.get("unavailable"):
                continue
            fol = _f(u, "followers", "followersCount", "followers_count") or 0
            if fol < int(c["min_followers"]):
                continue
            hh = u.get("userName") or h
            con.execute("INSERT OR IGNORE INTO accounts (handle, name, category, source, status, owner_seed, added_ts, "
                        "note) VALUES (?,?,?,?,?,?,?,?)", (hh, u.get("name") or hh, "edukacija", f"krug:{who}", "novo",
                                                           0, now, f"{cnt[h]} spominjanja u objavama @{who}"))
            apply_profile(con, hh, u, c, now)
            added.append(hh)
        store.kv(con, f"krug:{who}", json.dumps({"ts": now, "added": added}))
        con.commit()
        if added:
            log(store.PREFIX + f"krug @{who}: dodano {', '.join('@' + a for a in added)} (najčešće spominjani, "
                               f"{int(c['min_followers']) // 1000}k+)")
    return added


def mark_inactive(con, c, now=None):
    """aktivan -> neaktivan when the newest stored post is older than active_days (owner picks keep a note only)."""
    now = int(now or time.time())
    lim = now - int(c["active_days"]) * 86400
    for h, mine, last in store.q(con, "SELECT a.handle, a.owner_seed, (SELECT MAX(ts) FROM tweets t WHERE t.handle = "
                                      "a.handle) FROM accounts a WHERE a.status = 'aktivan'"):
        if last is None:
            continue
        con.execute("UPDATE accounts SET last_post_ts = ? WHERE handle = ?", (last, h))
        done = store.q(con, "SELECT 1 FROM fetch_log WHERE handle = ? AND unit = 'zadnjih'", (h,))
        if done and last < lim:
            if mine:
                con.execute("UPDATE accounts SET why = 'vlasnikov izbor; bez objave u zadnjih 30 dana' WHERE handle = ?",
                            (h,))
            else:
                con.execute("UPDATE accounts SET status = 'neaktivan', why = 'bez objave u zadnjih 30 dana' WHERE "
                            "handle = ?", (h,))
    con.commit()


def languages(con):
    """accounts.lang = the most common post language of each account."""
    for h, in store.q(con, "SELECT handle FROM accounts WHERE status = 'aktivan'"):
        r = store.q(con, "SELECT lang, COUNT(*) n FROM tweets WHERE handle = ? AND lang IS NOT NULL AND lang NOT IN "
                         "('zxx', 'und', 'qme', 'qam', 'art') GROUP BY lang ORDER BY n DESC LIMIT 1", (h,))
        if r:
            con.execute("UPDATE accounts SET lang = ? WHERE handle = ?", (r[0][0], h))
    con.commit()
