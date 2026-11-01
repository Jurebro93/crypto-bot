"""Turns usage.db into warnings: on pace to blow the monthly budget, a sudden spike (leak), exponential growth,
spend the bot did not make (something else uses the key), and retry storms.

Pure functions over the stored rows, so the dashboard can call evaluate() on every page view and
run_usage.py can keep a history of when each warning first appeared.
"""
import calendar
import datetime as dt
import json
import os
import statistics
import time

CONFIG = os.path.join(os.path.dirname(__file__), "budget.json")
H, D = 3600, 86400


def config():
    with open(CONFIG) as f:
        cfg = json.load(f)
    if os.environ.get("HELIUS_MONTHLY_CREDITS"):
        cfg["helius"]["monthly"] = int(os.environ["HELIUS_MONTHLY_CREDITS"])
    return cfg


def fmt(service, x):
    if service == "apify":
        return f"${x:,.2f}"
    return f"{x / 1e6:,.2f}M" if x >= 1e6 else f"{x / 1e3:,.1f}k" if x >= 1e3 else f"{x:,.0f}"


def cycle(day, now):
    """(start, end) of the billing cycle that starts on `day` of each month, UTC."""
    t = dt.datetime.fromtimestamp(now, dt.timezone.utc)

    def at(y, m):
        return dt.datetime(y, m, min(day, calendar.monthrange(y, m)[1]), tzinfo=dt.timezone.utc)
    start = at(t.year, t.month)
    if start > t:
        start = at(t.year - (t.month == 1), 12 if t.month == 1 else t.month - 1)
    nxt = at(start.year + (start.month == 12), 1 if start.month == 12 else start.month + 1)
    return int(start.timestamp()), int(nxt.timestamp())


def hourly(con, service, since, by_script=False):
    """{hour or (hour, script): [calls, errors, amount]} from the meter."""
    out = {}
    for hr, sc, calls, errs, amt in con.execute(
            "SELECT hour, script, SUM(calls), SUM(errors), SUM(amount) FROM usage WHERE service=? AND hour>=? "
            "GROUP BY hour, script", (service, since)):
        k = (hr, sc) if by_script else hr
        c = out.setdefault(k, [0, 0, 0.0])
        c[0] += calls
        c[1] += errs
        c[2] += amt
    return out


def counted(con, service, t0, t1):
    return con.execute("SELECT COALESCE(SUM(amount),0) FROM usage WHERE service=? AND hour>=? AND hour<?",
                       (service, t0 // H * H, t1)).fetchone()[0]


def snapshots(con, service, since):
    return con.execute("SELECT ts, used, lim, cycle_start, cycle_end FROM account WHERE service=? AND ts>=? ORDER BY ts",
                       (service, since)).fetchall()


def status(con, service, cfg, now=None):
    """Numbers for one service: used this cycle (account if known, else own count), limit, burn rate, projection."""
    now = now or time.time()
    c = cfg[service]
    snaps = snapshots(con, service, now - 40 * D)
    last = snaps[-1] if snaps and now - snaps[-1][0] < 6 * H else None
    if last and last[3]:
        start, end = last[3], last[4] or cycle(c["cycle_day"], now)[1]
    else:
        start, end = cycle(c["cycle_day"], now)
    own = counted(con, service, start, now + H)
    used = last[1] if last else own
    budget = c["monthly"]
    # burn rate per day without one-off bursts and without stretching a few hours of data to a day (_window_rates)
    rate, src = steady_rate(con, service, now, start, last)
    left_s = max(0, end - now)
    projected = used + rate * left_s / D
    runs_out = now + (budget - used) / rate * D if rate > 0 and used < budget else None
    return {"service": service, "unit": c["unit"], "used": used, "own": own, "budget": budget,
            "account_limit": last[2] if last else None, "account_ts": last[0] if last else None,
            "start": start, "end": end, "rate_day": rate, "rate_src": src, "projected": projected,
            "runs_out": runs_out, "fair_day": budget * D / max(D, end - start)}


BUCKET_H, LOOKBACK_H = 6, 24


def _window_rates(points, now):
    """Steady spend per day from cumulative (ts, used) points, oldest first: the last 24 h (a whole day, so quiet
    night hours do not fool it) cut into 6 h pieces, each capped at 3x a normal piece, so one burst (a backfill, a
    first pass over many tokens) counts as a normal piece instead of being stretched over the month. Anything older
    than a day is not today's pace (01.11.2026: a busy 31.10. kept the forecast at "budget gone 06.11." while the
    real pace was 220k/day). Bursts have their own warnings. Returns [(rate per day, hours)], empty under 3 h."""
    if len(points) < 2:
        return []
    t_first, end = points[0][0], points[-1]

    def at(t):
        return max((p for p in points if p[0] <= t), key=lambda p: p[0], default=points[0])[1]
    edges, t = [end[0]], end[0]
    while t - BUCKET_H * H > max(t_first, now - LOOKBACK_H * H):
        t -= BUCKET_H * H
        edges.append(t)
    edges.append(max(t_first, now - LOOKBACK_H * H, edges[-1] - BUCKET_H * H))
    edges = sorted(set(edges))
    span = edges[-1] - edges[0]
    if span < 3 * H:
        return []
    inc = [max(0.0, at(b) - at(a)) for a, b in zip(edges, edges[1:])]
    lens = [b - a for a, b in zip(edges, edges[1:])]
    if len(inc) >= 3:
        per_h = sorted(i / max(1, ln / H) for i, ln in zip(inc, lens))
        normal = max(statistics.median(per_h), statistics.mean(per_h[:-1]))
        inc = [min(i, 3 * normal * ln / H) for i, ln in zip(inc, lens)]
    return [(sum(inc) * D / span, round(span / H))]


def steady_rate(con, service, now, start, last):
    """(credits or USD per day, source label). Account readings when there are any, else our own counter."""
    if last:
        pts = [(s[0], s[1]) for s in snapshots(con, service, max(start, now - 74 * H)) if s[3] == last[3]]
        rates = _window_rates(pts, now)
        if rates:
            return rates[0][0], f"račun, zadnjih {rates[0][1]} h bez jednokratnih skokova"
    meter_from = con.execute("SELECT MIN(hour) FROM usage WHERE service=?", (service,)).fetchone()[0]
    if meter_from is None:
        return 0.0, "nema podataka"
    pts, acc = [], 0.0
    for hr, amt in con.execute("SELECT hour, SUM(amount) FROM usage WHERE service=? AND hour>=? GROUP BY hour ORDER BY hour",
                               (service, max(meter_from, start, now - 74 * H))):
        if not pts:
            pts.append((hr, 0.0))
        acc += amt
        pts.append((min(hr + H, now), acc))
    rates = _window_rates(pts, now)
    if not rates:
        return 0.0, "premalo podataka (bot broji kraće od 3 h)"
    return rates[0][0], f"brojač bota, zadnjih {rates[0][1]} h bez jednokratnih skokova"


CATEGORY = {"rpc": "obični RPC pozivi", "enhancedApi": "Enhanced API", "das": "DAS (holderi, podaci o tokenu)",
            "webhooks": "webhook događaji", "walletApi": "Wallet API", "archival": "arhivski upiti",
            "photon": "Photon", "preConfirmations": "pre-potvrde", "laserstreamGrpc": "LaserStream",
            "laserstreamWebsocket": "LaserStream websocket", "other": "ostalo"}


def _credits(extra):
    try:
        c = (json.loads(extra or "{}") or {}).get("credits") or {}
        return {k: float(v) for k, v in c.items() if isinstance(v, (int, float))}
    except (ValueError, AttributeError):
        return {}


def category_gaps(con, t0, t1):
    """[(category, account − bot, account, bot)] between two Helius account readings, biggest gap first. The
    Admin API splits usage into categories (rpc, das, webhooks, ...); our meter's methods map onto the same ones."""
    rows = con.execute("SELECT ts, extra FROM account WHERE service='helius' AND ts IN (?, ?) ORDER BY ts", (t0, t1)).fetchall()
    if len(rows) < 2:
        return []
    a, b = _credits(rows[0][1]), _credits(rows[-1][1])
    if not b:
        return []
    from usage import meter
    mine = {}
    for m, amt in con.execute("SELECT method, SUM(amount) FROM usage WHERE service='helius' AND hour>=? AND hour<? "
                              "GROUP BY method", (t0 // H * H, t1)):
        k = meter.helius_category(m)
        mine[k] = mine.get(k, 0) + amt
    out = []
    for k in set(b) | set(mine):
        acc = max(0.0, b.get(k, 0) - a.get(k, 0))
        out.append((k, acc - mine.get(k, 0), acc, mine.get(k, 0)))
    return sorted(out, key=lambda r: -r[1])


def _script(k):
    try:
        from ui.labels import script
        return script(k)
    except Exception:
        return k


def evaluate(con, cfg=None, now=None):
    """List of {key, service, level: bad|warn, title, detail}, worst first."""
    cfg = cfg or config()
    now = now or time.time()
    out = []
    for service in ("helius", "apify"):
        c, st = cfg[service], status(con, service, cfg, now)
        f = lambda x: fmt(service, x)  # noqa: E731
        name = "Helius" if service == "helius" else "Apify"
        b = st["budget"]
        # 1. budget pace
        if st["used"] >= b * 0.95:
            out.append(("bad", f"{service}:spent", f"{name}: budžet skoro potrošen",
                        f"Potrošeno {f(st['used'])} od {f(b)} ovaj ciklus."))
        elif st["projected"] > b * 1.05:   # 5% margin: no warning flapping on and off around the limit
            day = dt.datetime.fromtimestamp(st["runs_out"], dt.timezone.utc).strftime("%d.%m.") if st["runs_out"] else "?"
            out.append(("bad" if st["projected"] > b * 1.2 else "warn", f"{service}:pace",
                        f"{name}: ovim tempom budžet nestaje {day}",
                        f"Potrošeno {f(st['used'])} od {f(b)}; tempo {f(st['rate_day'])}/dan (izvor: {st['rate_src']}), "
                        f"ravnomjerno bi bilo {f(st['fair_day'])}/dan. Projekcija do kraja ciklusa: {f(st['projected'])}."))
        # 2. leak / spike per script
        by = hourly(con, service, now - 27 * H, by_script=True)
        first_seen = dict(con.execute("SELECT script, MIN(hour) FROM usage WHERE service=? GROUP BY script", (service,)))
        hour_quota = b / 720
        cur = now // H * H
        for sc_key in {k[1] for k in by}:
            sc = _script(sc_key)
            recent = sum(v[2] for (hr, s), v in by.items() if s == sc_key and hr >= cur - H)
            base = sum(v[2] for (hr, s), v in by.items() if s == sc_key and cur - 25 * H <= hr < cur - H) / 24
            errs = sum(v[1] for (hr, s), v in by.items() if s == sc_key and hr >= cur - H)
            if recent > hour_quota * 2 * c["hour_max_x"]:
                out.append(("bad", f"{service}:leak:{sc_key}", f"{name}: {sc} troši naglo",
                            f"Zadnja 2 h {f(recent)}, a ravnomjerna kvota je {f(hour_quota * 2)} za 2 h. Moguće curenje "
                            "(petlja koja ponavlja pozive ili cache ne radi)."))
            elif (recent > c["spike_floor"] and first_seen.get(sc_key, cur) <= cur - 25 * H
                  and recent > base * 2 * c["spike_x"]):
                out.append(("warn", f"{service}:spike:{sc_key}", f"{name}: {sc} troši {recent / max(base * 2, 1e-9):.0f}x više nego inače",
                            f"Zadnja 2 h {f(recent)}, prosjek za 2 h u zadnja 24 h {f(base * 2)}."))
            if errs > c["error_calls_hour"] * 2:
                out.append(("warn", f"{service}:errors:{sc_key}", f"{name}: {sc} dobiva puno grešaka",
                            f"{errs} odbijenih poziva u zadnja 2 h. Ako ih servis odbija zbog limita, "
                            "krediti su potrošeni."))
        # 3. exponential growth of daily totals
        days = [counted(con, service, cur - (i + 1) * D, cur - i * D) for i in range(4, -1, -1)]  # oldest .. last 24 h
        growth = [days[i + 1] / days[i] for i in range(4) if days[i] > 0]
        if len(growth) >= 3 and all(g >= 1.5 for g in growth[-3:]) and days[-1] > st["fair_day"] * 0.5:
            out.append(("warn", f"{service}:exp", f"{name}: potrošnja raste eksponencijalno",
                        "Dnevno (zadnjih 5 dana): " + " → ".join(f(d) for d in days) + ". Svaki dan bar 1.5x više."))
        elif any(days[:-1]) and days[-1] > max(st["fair_day"], 2 * statistics.mean(days[:-1])) \
                and days[-1] > c["spike_floor"]:  # double the usual day and above the even daily share
            out.append(("warn", f"{service}:day", f"{name}: zadnja 24 h duplo više nego inače",
                        f"Zadnja 24 h {f(days[-1])}, prethodni dani prosječno {f(statistics.mean(days[:-1]))}, "
                        f"ravnomjerno {f(st['fair_day'])}/dan."))
        # 4. spend the bot did not make: the account grew more than our own count over the same window
        snaps = [s for s in snapshots(con, service, now - 26 * H) if s[3] == st["start"]]
        if len(snaps) >= 2 and snaps[-1][0] - snaps[0][0] >= 3 * H:
            acc = snaps[-1][1] - snaps[0][1]
            mine = counted(con, service, snaps[0][0], snaps[-1][0])
            if acc - mine > c["unexplained_floor"] and acc > mine * 1.5:
                hrs = (snaps[-1][0] - snaps[0][0]) / H
                where = ""
                if service == "helius":
                    gaps = category_gaps(con, snaps[0][0], snaps[-1][0])
                    if gaps:
                        where = "Razlika po vrsti poziva (račun − bot): " + ", ".join(
                            f"{CATEGORY.get(k, k)} {f(g)}" for k, g, _, _ in gaps[:3] if g > 0) + ". "
                out.append(("warn", f"{service}:outside", f"{name}: troši se i izvan bota",
                            f"Račun je u zadnjih {hrs:.0f} h narastao {f(acc)}, a bot je izbrojao samo {f(mine)}. " + where
                            + ("Možda Apify nešto pokreće sam od sebe (u Apify konzoli pogledaj Runs)."
                               if service == "apify" else "Isti ključ možda koristi još neka aplikacija "
                               "(npr. analiza pokrenuta izvan servera).")))
    out.sort(key=lambda a: a[0] != "bad")
    return [{"level": lv, "key": k, "service": k.split(":")[0], "title": t, "detail": d} for lv, k, t, d in out]


def remember(con, alerts, now=None):
    """Keep first/last time each warning was seen (history on the dashboard)."""
    now = int(now or time.time())
    for a in alerts:
        con.execute("""INSERT INTO alerts (key, service, level, title, detail, first_ts, last_ts) VALUES (?,?,?,?,?,?,?) ON CONFLICT (key) DO UPDATE SET level=excluded.level,
            title=excluded.title, detail=excluded.detail, last_ts=excluded.last_ts,
            first_ts=CASE WHEN alerts.last_ts < ? THEN excluded.first_ts ELSE alerts.first_ts END""",
                    (a["key"], a["service"], a["level"], a["title"], a["detail"], now, now, now - 3 * H))
    con.commit()


def to_log(con, alerts, now=None, every=D):
    """The warnings worth a line in the server log: new ones, ones that got worse (warn -> bad), and the rest once a
    day. The check runs every 15 min, so without this one ongoing warning filled the log ~100 times a day."""
    now = int(now or time.time())
    cols = {r[1] for r in con.execute("PRAGMA table_info(alerts)")}
    for c in ("logged_ts", "logged_level"):
        if c not in cols:
            con.execute(f"ALTER TABLE alerts ADD COLUMN {c} {'INTEGER' if c == 'logged_ts' else 'TEXT'}")
    out = []
    for a in alerts:
        row = con.execute("SELECT logged_ts, logged_level FROM alerts WHERE key=?", (a["key"],)).fetchone()
        lts, llv = row if row else (None, None)
        if lts is None or now - lts >= every or (a["level"] == "bad" and llv != "bad"):
            out.append(a)
            con.execute("UPDATE alerts SET logged_ts=?, logged_level=? WHERE key=?", (now, a["level"], a["key"]))
    con.commit()
    return out
