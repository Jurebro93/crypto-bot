"""Kritičar (OpenAI): the daily algorithm / data-science review, with the critique of the newest analyses folded in as
its section "izvjestaji" (15.11., vlasnik). ADVICE ONLY: every finding is a suggestion note the owner accepts or rejects
on the Autopilot page (nothing applies by itself; the findings carry no proposed_change), plus one daily summary.

Once a Zagreb day from run_sched (job kriticar_dan: at the first check after a start when today has none, then
KRITICAR_DAILY_HOUR:40, 06:40 by default, outside the 01-06 heavy-job window and before the 07:00 morning e-mail), or
on demand: python3 run_critic.py daily --sada. The strong model OPENAI_MODEL_DEEP (gpt-6-astra, reasoning effort
medium; the cheap one when its most would not fit the budget).

What it reads (critic/data.py, all stored by the bot): per strategy n, win rate, median, EV with its 90 % interval,
profit factor, max drawdown, the top 3 wins' share, exits, BTC regime and time of day, demo vs real money; the key
rules and caps; the settings changed in 7 days; the macro state; the data cost per source in 7 days; the newest
reports (EV per flag, range / momentum backtests, "zadnjih 5", the proposals' day); the critic's own record (calls,
cost, hit rates); the titles of its suggestions the owner rejected (not to repeat them).
"""
import datetime as dt
import json
import time

from critic import data as cdata
from critic import notes as cnotes
from critic import openai_api, privacy, prompts
from critic import store

MAX_OUT = 8000
EFFORT = "medium"
MAX_FINDINGS = 7
TZ = "Europe/Zagreb"


def build_payload(tcon, now):
    from ui import pravitrade as pt
    try:
        cfg = pt._cfg(tcon)
    except Exception:  # noqa: BLE001
        cfg = None
    own = store.stats(tcon, 7, now)
    return {
        "vrijeme_utc": time.strftime("%Y-%m-%d %H:%M", time.gmtime(now)),
        "strategije_30d": cdata.strategy_stats(tcon, now, 30),
        "pravila_i_stropovi": cdata.rules(cfg),
        "promjene_postavki_7d": cdata.recent_changes(tcon, now),
        "makro": cdata.makro(now),
        "trosak_podataka_7d": cdata.cost_by_source(now),
        "izvjestaji": cdata.reports(now),
        "kriticar_sam_7d": {k: own.get(k) for k in ("poziva", "ukupno_usd", "presude", "prijedlozi")},
        "odbijeni_prijedlozi": cnotes.rejected_titles(tcon, now=now),
    }


def validate(d):
    """(sazetak, strategije, nalazi, nedostaje) of the answer; raises ValueError when unusable."""
    if not isinstance(d, dict):
        raise ValueError("odgovor nije objekt")
    sazetak = str(d.get("sazetak") or "").strip()
    if not sazetak:
        raise ValueError("nema sažetka")
    strat = []
    for x in d.get("strategije") or []:
        if isinstance(x, dict) and str(x.get("presuda")) in prompts.PRESUDE and str(x.get("ime") or "").strip():
            strat.append({"ime": str(x["ime"]).strip()[:60], "presuda": x["presuda"],
                          "razlog": str(x.get("razlog") or "").strip()[:400]})
    nalazi = []
    for x in d.get("nalazi") or []:
        if not isinstance(x, dict):
            continue
        f = {k: str(x.get(k) or "").strip() for k in ("naslov", "ozbiljnost", "dokaz", "prijedlog", "kako_provjeriti")}
        if f["ozbiljnost"] not in prompts.OZBILJNOST or not f["naslov"] or not f["dokaz"]:
            continue
        f["naslov"] = f["naslov"][:150]
        for k in ("dokaz", "prijedlog", "kako_provjeriti"):
            f[k] = f[k][:1500]
        nalazi.append(f)
        if len(nalazi) >= MAX_FINDINGS:
            break
    nedostaje = [str(x).strip()[:300] for x in d.get("nedostaje_mjerenje") or [] if str(x or "").strip()][:8]
    return sazetak[:1200], strat, nalazi, nedostaje


def summary_text(sazetak, strat, nalazi, nedostaje, own_line):
    parts = [sazetak]
    if strat:
        parts.append("Strategije: " + "; ".join(f"{s['ime']}: {s['presuda']} ({s['razlog']})" for s in strat))
    if nalazi:
        parts.append("Nalazi: " + "; ".join(f"[{f['ozbiljnost']}] {f['naslov']}" for f in nalazi))
    if nedostaje:
        parts.append("Nedostaje mjerenje: " + "; ".join(nedostaje))
    parts.append(own_line)
    return "\n\n".join(parts)


def run(now=None, log=print, tcon=None, call=None, payload_fn=None, force=False):
    """One daily review. Returns a small dict of what happened."""
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
        if not force and store.daily_done(tcon, now):
            return {"skip": "danas već napravljen"}
        payload = (payload_fn or build_payload)(tcon, now)
        mints = set()
        text = prompts.DAILY + "\n\nPodaci (JSON):\n" + json.dumps(payload, ensure_ascii=False, separators=(",", ":"),
                                                                   default=str)
        text = privacy.scrub(text, mints, extra=privacy.owner_wallets(tcon))
        bad = privacy.leaks(text, mints, extra=privacy.owner_wallets(tcon))
        if bad:
            log(f"kritičar: dnevni pregled nije poslan (privatnost: {', '.join(bad)})", flush=True)
            return {"skip": "privatnost"}
        model, _est = store.pick(tcon, "daily", openai_api.MODEL_DEEP, len(text) + len(prompts.SYSTEM), MAX_OUT, now, log)
        if model is None:
            return {"skip": "budžet"}
        fn = call or openai_api.call_json
        try:
            res = fn(model, prompts.SYSTEM, text, prompts.DAILY_SCHEMA, "kriticar_dnevno", MAX_OUT, EFFORT)
        except openai_api.ApiError as e:
            c = openai_api.cost(e.model or model, e.usage) if e.usage else 0.0
            store.book(tcon, "daily", e.model or model, e.usage, c, False, str(e), text, now=now)
            log(f"kritičar: dnevni pregled nije uspio ({e})", flush=True)
            return {"skip": "greška API-ja", "greska": str(e)}
        try:
            sazetak, strat, nalazi, nedostaje = validate(res["data"])
        except ValueError as e:
            store.book(tcon, "daily", res["model"], res["usage"], res["cost_usd"], False, f"neispravan odgovor: {e}",
                       text, now=now)
            log(f"kritičar: dnevni pregled neispravan ({e}), trošak {res['cost_usd']:.4f} $", flush=True)
            return {"skip": "neispravan odgovor", "greska": str(e)}
        call_id = store.book(tcon, "daily", res["model"], res["usage"], res["cost_usd"], True, None, text,
                             n=len(nalazi), now=now)
        ids = []
        for f in nalazi:
            try:
                ids.append(cnotes.store_finding(tcon, f, res["model"]))
            except ValueError as e:
                log(f"kritičar: nalaz „{f['naslov'][:60]}” nije zapisan ({e})", flush=True)
        own_line = store.stats_line(store.stats(tcon, 7, now))
        from zoneinfo import ZoneInfo
        day = dt.datetime.fromtimestamp(now, ZoneInfo(TZ)).strftime("%d.%m.")
        sid = None
        try:
            sid = cnotes.store_summary(tcon, f"{cnotes.LABEL}: dnevni pregled {day}",
                                       summary_text(sazetak, strat, nalazi, nedostaje, own_line),
                                       {"kriticar": "openai", "model": res["model"], "call_id": call_id,
                                        "strategije": strat, "nedostaje_mjerenje": nedostaje, "nalazi_id": ids})
        except ValueError as e:
            log(f"kritičar: dnevni sažetak nije zapisan ({e})", flush=True)
        log_findings(log, "dnevni", sazetak, nalazi, strat)
        log(f"kritičar: dnevni pregled spremljen, {len(ids)} nalaza, {len(strat)} strategija, trošak "
            f"{res['cost_usd']:.4f} $ ({res['usage'].get('in')} ulaz / {res['usage'].get('out')} izlaz tokena, "
            f"{res['model']})", flush=True)
        return {"nalaza": len(ids), "strategija": len(strat), "cost_usd": res["cost_usd"], "summary_id": sid,
                "call_id": call_id}
    finally:
        if own:
            tcon.close()


def log_findings(log, what, sazetak, nalazi, strat=(), extra=()):
    """15.11. (owner: "izvijesti me odmah nakon prvog pregleda"): the review's summary, each finding (severity, title,
    proposal) and each strategy verdict in the log, one line each and capped, so the result can be read and relayed
    without opening the page. Nothing new leaves the server: these lines are the stored notes' own words."""
    try:
        log(f"kritičar: {what} sažetak: {str(sazetak or '')[:600]}", flush=True)
        for f in nalazi or ():
            log(f"kritičar: {what} nalaz [{f.get('ozbiljnost')}] {str(f.get('naslov') or '')[:140]} → "
                f"{str(f.get('prijedlog') or '')[:300]}", flush=True)
        if strat:
            log(f"kritičar: {what} strategije: " + "; ".join(
                f"{s.get('ime')}={s.get('presuda')}" for s in strat if isinstance(s, dict))[:900], flush=True)
        for line in extra or ():
            if line:
                log(f"kritičar: {what} {str(line)[:600]}", flush=True)
    except Exception:  # noqa: BLE001 - a log line never breaks the review
        pass
