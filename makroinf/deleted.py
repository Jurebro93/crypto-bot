"""Is a stored macro call still on X? (the critic: "brisanja bez lažnih optužbi"). Every post with a macro call is
looked up by id (twitterapi.io, like kol/deleted.py) at base + 1 d, + 7 d and + 30 d, base = max(post time, the time
we fetched it): we can only see what disappears AFTER we had it (backwards there is no reliable detection; a falling
statuses_count is no proof and is not used).

States (deletions.state):
  exists              found at the last check
  pending             missing once: checked again after RECHECK_H before anything is concluded
  confirmed_deleted   missing twice in a row while the account itself is reachable and public
  unavailable         missing, and the account could not be read to tell why (kept apart from deleted)
  account_protected / account_suspended   the account is private / gone: its posts are not "deleted"
  api_error           the answer was empty for a whole batch (an API hiccup, never "all deleted"): tried again
No automatic penalty; the page says "naknadno nedostupno", never "skriva promašaje". The <5 min flash rule of
kol/deleted.py is not used here (macro calls are measured over days).
15.11. navečer (the expansion to 300-500 accounts, ~18 months of history each): a post we fetched more than 30 days
after it was written (the backfill's history) is checked once, at base + 30 d (stage 2), not three times: what
disappears after we had it is still found, a month later, at a third of the cost; the daily posts keep +1 / +7 / +30.
"""
import time

from makroinf import store, xapi

STAGES_D = (1, 7, 30)
RECHECK_H = 6
HISTORY_D = 30   # fetched later than this after the post: history, one check at +30 d
D = 86400


def sync(con):
    """A deletions row for every macro post that has none (base = max(post time, fetched))."""
    con.execute("""INSERT OR IGNORE INTO deletions (id, handle, base_ts, stage, state)
        SELECT t.id, t.handle, MAX(t.ts, t.fetched_ts), CASE WHEN t.fetched_ts - t.ts > ? THEN 2 ELSE 0 END, NULL
        FROM tweets t JOIN accounts a ON a.handle = t.handle WHERE t.macro = 1 AND a.status IN ('aktivan',
        'neaktivan')""", (HISTORY_D * D,))
    con.commit()


def due(con, now, limit=500):
    """[(id, handle, state)] whose next stage is due, or pending ones whose recheck is due."""
    rows = store.q(con, """SELECT id, handle, base_ts, stage, state, first_miss_ts FROM deletions
        WHERE state IS NULL OR state IN ('exists', 'pending', 'api_error', 'unavailable')
        ORDER BY base_ts""")
    out = []
    for i, h, base, stage, st, miss in rows:
        if st == "pending":
            if now - (miss or 0) >= RECHECK_H * 3600:
                out.append((i, h, st))
        elif stage < len(STAGES_D) and now >= base + STAGES_D[stage] * D:
            out.append((i, h, st))
        if len(out) >= limit:
            break
    return out


def _account_state(con, handle, c, now, get, cache):
    if handle in cache:
        return cache[handle]
    try:
        u = xapi.user(con, handle, store.phase(con, "twapi"), c, now, get)
    except xapi.CapReached:
        raise
    except Exception:  # noqa: BLE001
        u = None
    if u is None:
        st = None
    elif u.get("unavailable"):
        st = "account_suspended"
    elif u.get("protected") or u.get("isProtected"):
        st = "account_protected"
    else:
        st = "ok"
    cache[handle] = st
    return st


def check(con, c, now=None, get=None, log=print, batch=100, limit=500):
    """One round over due ids. Returns {"checked", "exists", "pending", "deleted", "other", "cap"}."""
    now = int(now or time.time())
    sync(con)
    out = {"checked": 0, "exists": 0, "pending": 0, "deleted": 0, "other": 0, "cap": None}
    if not xapi.has_key(get):
        out["cap"] = "nema ključa"
        return out
    ids = due(con, now, limit)
    acct = {}
    for k in range(0, len(ids), batch):
        part = ids[k:k + batch]
        try:
            present = {str(t.get("id")) for t in xapi.by_ids(con, [i for i, _h, _s in part],
                                                             store.phase(con, "twapi"), c, now, get)}
        except xapi.CapReached as e:
            out["cap"] = str(e)
            break
        except Exception as e:  # noqa: BLE001
            log(store.PREFIX + f"provjera brisanja: {type(e).__name__}: {str(e)[:100]}")
            break
        if not present and len(part) >= 5:
            con.executemany("UPDATE deletions SET state = 'api_error', n_err = n_err + 1, last_check = ? WHERE id = ?",
                            [(now, i) for i, _h, _s in part])
            log(store.PREFIX + f"provjera brisanja: prazan odgovor za {len(part)} objava (greška API-ja), ponovno kasnije")
            continue
        for i, h, st in part:
            out["checked"] += 1
            if i in present:
                con.execute("UPDATE deletions SET stage = MIN(stage + 1, ?), state = 'exists', n_miss = 0, "
                            "last_check = ? WHERE id = ?", (len(STAGES_D), now, i))
                out["exists"] += 1
                continue
            try:
                ast = _account_state(con, h, c, now, get, acct)
            except xapi.CapReached as e:
                out["cap"] = str(e)
                break
            if ast in ("account_suspended", "account_protected"):
                new = ast
            elif ast is None:
                new = "unavailable"
            elif st == "pending":
                new = "confirmed_deleted"
            else:
                new = "pending"
            con.execute("UPDATE deletions SET state = ?, n_miss = n_miss + 1, first_miss_ts = COALESCE(first_miss_ts, ?), "
                        "last_check = ? WHERE id = ?", (new, now, now, i))
            key = {"confirmed_deleted": "deleted", "pending": "pending"}.get(new, "other")
            out[key] += 1
        con.commit()
        if out["cap"]:
            break
    return out


def states(con, handle=None):
    """{tweet id: state} of the checked posts (all, or one account's)."""
    sql = "SELECT id, state FROM deletions WHERE state IS NOT NULL"
    args = ()
    if handle:
        sql += " AND handle = ?"
        args = (handle,)
    return {i: s for i, s in store.q(con, sql, args)}
