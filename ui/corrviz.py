"""Pictures and plain sentences for the Korelacije page: what raises the chance of a 2x (paired bars), each KOL group
as a card (who calls first, who follows and after how many minutes, together vs. alone), wallets that buy before a
call (buy -> call -> sell on a time line) and wallet groups of one owner. Only stored numbers, no new data."""
import math
from urllib.parse import quote

from ui.html import badge, esc, tlink, wlink
from ui.labels import wallet_label

CSS = """<style>
.cz-cards{display:grid;grid-template-columns:repeat(auto-fill,minmax(340px,1fr));gap:12px}
.cz-card{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:12px 14px}
.cz-card h3{margin:0 0 6px;font-size:15px}.cz-say{margin:6px 0 10px;font-size:14px}
.cz-row{display:grid;grid-template-columns:minmax(120px,38%) 1fr;gap:8px;align-items:center;margin:5px 0;font-size:13px}
.cz-bars{display:flex;flex-direction:column;gap:3px}
.cz-bar{display:flex;align-items:center;gap:6px}.cz-bar span.t{width:46px;text-align:right;font-variant-numeric:tabular-nums;font-weight:600}
.cz-bar i{display:block;height:12px;border-radius:3px;min-width:2px}
.cz-yes{background:var(--good)}.cz-no{background:color-mix(in srgb,var(--mut) 45%,transparent)}.cz-late{background:var(--bad)}
.cz-legend{font-size:12px;color:var(--mut);display:flex;gap:14px;margin:4px 0 8px;flex-wrap:wrap}
.cz-legend i{display:inline-block;width:10px;height:10px;border-radius:2px;margin-right:4px;vertical-align:-1px}
.cz-svg{width:100%;height:auto;display:block}.cz-svg text{fill:currentColor;font-size:11px}
.cz-meter{height:8px;border-radius:4px;background:var(--line);overflow:hidden}.cz-meter i{display:block;height:100%}
.cz-small{font-size:12px;color:var(--mut)}
</style>"""

GOOD, WARN, BAD, MUT = "var(--good)", "var(--warn)", "var(--bad)", "var(--mut)"


def _pc(x):
    return "?" if x is None else f"{x * 100:.0f}%"


def _acct(h, short=False):
    if h.startswith("tg:"):
        return f'<a href="https://t.me/{quote(h[3:])}" target=_blank rel=noopener>✈ {esc(h[3:])}</a>'
    if h.startswith("w:"):
        return f'<a href="/kol/{quote(h)}">👛 {esc(h[2:])}</a>'
    return f'<a href="/kol/{quote(h)}">@{esc(h)}</a>'


def bars(yes, no, label_yes, label_no, mx=None):
    """Two horizontal bars on the same scale: with the signal (green) and without (grey)."""
    mx = mx or max(yes or 0, no or 0, 0.01)
    out = []
    for v, cls, lab in ((yes, "cz-yes", label_yes), (no, "cz-no", label_no)):
        w = 0 if v is None else 100 * v / mx
        out.append(f'<div class=cz-bar title="{esc(lab)}"><span class=t>{_pc(v)}</span>'
                   f'<i class={cls} style="width:{w:.0f}%"></i><span class=cz-small>{esc(lab)}</span></div>')
    return '<div class=cz-bars>' + "".join(out) + "</div>"


# ---------------------------------------------------------------- factors

def factors(f):
    """Which signal goes with more 2x: one row per signal, two bars each, best first."""
    rows = f.get("factors") or []
    if not rows:
        return '<div class=empty>Premalo izmjerenih tokena za usporedbu.</div>'
    mx = max(max(r["hit_yes"], r["hit_no"]) for r in rows)
    out = [f'<p class=cz-say>Od {f["n"]:,} pozvanih tokena s poznatim ishodom, {_pc(f["base_hit"])} se udvostručilo u '
           '24 sata. Zelena traka je udio udvostručenih kad je signal bio prisutan, siva kad nije. '
           'Što je zelena duža od sive, to je signal korisniji.</p>',
           '<div class=cz-legend><span><i class=cz-yes></i>sa signalom</span><span><i class=cz-no></i>bez signala</span></div>']
    for r in rows:
        x = r["hit_yes"] / r["hit_no"] if r["hit_no"] else None
        verdict = (badge(f"{x:.1f}× češće", "good") if x and x >= 1.3 else
                   badge("lošije", "bad") if x and x < 0.9 else badge("mala razlika"))
        out.append(f'<div class=cz-row><div><b>{esc(r["factor"][0].upper() + r["factor"][1:])}</b><br>{verdict} '
                   f'<span class=cz-small>{r["n_yes"]:,} tokena sa, {r["n_no"]:,} bez</span></div>'
                   + bars(r["hit_yes"], r["hit_no"], "", "", mx) + "</div>")
    return '<div class=cz-card>' + "".join(out) + "</div>"


# ---------------------------------------------------------------- KOL groups

def verdict(cl):
    """(text, kind, sentence) telling what to do with the group."""
    ht, hs, late, n = cl.get("hit_together"), cl.get("hit_solo"), cl.get("late_share"), cl.get("n_together_measured") or 0
    if late is not None and late >= 0.5:
        return ("Oprez: kasne", "bad", f"Više od pola zajedničkih poziva ({_pc(late)}) dođe tek nakon što je token već "
                                        "pumpao. Ovo više liči na hvalisanje ili izlaz nego na rani poziv.")
    if ht is not None and hs is not None and n >= 8 and ht >= hs + 0.08:
        return ("Ulaz kad se poklope", "good", "Kad više njih zove isti token, ishod je bolji nego kad zove samo jedan. "
                                               "Signal: vođa pozove, a drugi član se javi u idućih pola sata.")
    if ht is not None and hs is not None and n >= 8 and ht < hs - 0.05:
        return ("Ne isplati se", "bad", "Zajednički pozivi prolaze lošije od pojedinačnih: moguće je da zajedno guraju "
                                        "token na koji onda prodaju.")
    if n < 8:
        return ("Malo podataka", "", "Grupa je jasna po vremenu poziva, ali premalo tokena ima izmjeren ishod za ocjenu.")
    return ("Neutralno", "warn", "Zajedno i pojedinačno prolaze slično: grupa postoji, ali sama po sebi ne daje prednost.")


def network(cl, w=300, h=230):
    """Accounts on a circle; a thicker line = they share more of their calls; the orange dot is the one who usually
    calls first."""
    ms = cl["members"][:14]
    if len(ms) < 2:
        return ""
    cx, cy, r = w / 2, h / 2, min(w, h) / 2 - 30
    pos = {m: (cx + r * math.cos(2 * math.pi * i / len(ms) - math.pi / 2),
               cy + r * math.sin(2 * math.pi * i / len(ms) - math.pi / 2)) for i, m in enumerate(ms)}
    lines, dots = [], []
    for a, b, ov, n in cl.get("edges", []):
        if a in pos and b in pos:
            (x1, y1), (x2, y2) = pos[a], pos[b]
            lines.append(f'<line x1="{x1:.0f}" y1="{y1:.0f}" x2="{x2:.0f}" y2="{y2:.0f}" stroke="var(--acc)" '
                         f'stroke-opacity="{min(0.85, 0.15 + ov):.2f}" stroke-width="{0.8 + 5 * ov:.1f}">'
                         f'<title>@{esc(a)} i @{esc(b)}: {n} zajedničkih tokena</title></line>')
    for m, (x, y) in pos.items():
        lead = m == cl.get("leader")
        dots.append(f'<circle cx="{x:.0f}" cy="{y:.0f}" r="{8 if lead else 5}" fill="{"var(--warn)" if lead else "var(--good)"}">'
                    f'<title>@{esc(m)}</title></circle><text x="{x:.0f}" y="{y + (17 if y >= cy else -10):.0f}" '
                    f'text-anchor="middle">{esc(m[:13])}</text>')
    return f'<svg class=cz-svg viewBox="0 0 {w} {h}" role=img>' + "".join(lines) + "".join(dots) + "</svg>"


def sequence(cl, w=320):
    """Time line: who calls first and how many minutes later the others follow (median over shared tokens)."""
    order = [o for o in (cl.get("order") or []) if o[2] >= 2][:10]
    if len(order) < 2:
        return ""
    mx = max(10, max(o[1] for o in order))
    left, right, row = 92, 34, 17
    h = 26 + row * len(order)
    sc = lambda m: left + (w - left - right) * m / mx  # noqa: E731
    ticks = [0, round(mx / 2), round(mx)]
    out = [f'<line x1="{sc(0):.0f}" y1="14" x2="{sc(mx):.0f}" y2="14" stroke="var(--line)"/>']
    for t in ticks:
        out.append(f'<text x="{sc(t):.0f}" y="10" text-anchor="middle">{t} min</text>')
    for i, (hd, m, n) in enumerate(order):
        y = 28 + i * row
        col = "var(--warn)" if i == 0 else "var(--good)"
        out.append(f'<text x="{left - 6}" y="{y + 4}" text-anchor="end">{esc(hd[:13])}</text>'
                   f'<line x1="{sc(0):.0f}" y1="{y}" x2="{sc(m):.0f}" y2="{y}" stroke="var(--line)" stroke-width="2"/>'
                   f'<circle cx="{sc(m):.0f}" cy="{y}" r="5" fill="{col}"><title>@{esc(hd)}: medijan {m:.0f} min nakon '
                   f'prvog poziva, na {n} tokena</title></circle>'
                   f'<text x="{sc(m) + 8:.0f}" y="{y + 4}">+{m:.0f}</text>')
    return f'<svg class=cz-svg viewBox="0 0 {w} {h}" role=img>' + "".join(out) + "</svg>"


def kol_card(cl, g):
    lab, kind, why = verdict(cl)
    others = cl["size"] - 1
    lead = cl.get("leader")
    name = g.get("ime") or (f"Grupa oko @{lead}" if lead else "KOL grupa")
    say = (f'{_acct(lead)} najčešće zove prvi ({_pc(cl.get("leader_share"))} puta), a {others} '
           f'{"račun ga slijedi" if others == 1 else "računa ga slijede"} u prosjeku za '
           f'{cl["spread_min"]:.0f} min. Zajedno su zvali {cl["tokens"]} tokena.' if lead else "")
    late = cl.get("late_share")
    parts = [f'<div class=cz-card id="{cl["id"]}"><h3>{esc(name)} {badge(lab, kind)}</h3>',
             f'<p class=cz-say>{say} {esc(why)}</p>' if say else f'<p class=cz-say>{esc(why)}</p>']
    if g.get("tumacenje"):
        parts.append(f'<p class=cz-say><b>AI:</b> {esc(g["tumacenje"])}</p>')
    if g.get("kako_iskoristiti"):
        parts.append(f'<p class=cz-say><b>Kako iskoristiti:</b> {esc(g["kako_iskoristiti"])}</p>')
    parts.append('<div class=cz-row><div><b>Koliko tokena se udvostruči</b></div>'
                 + bars(cl.get("hit_together"), cl.get("hit_solo"), "zajedno", "sam") + "</div>")
    if late is not None:
        parts.append(f'<div class=cz-row><div><b>Pozivi nakon pumpe</b><br><span class=cz-small>manje je bolje</span></div>'
                     f'<div><div class=cz-meter><i class=cz-late style="width:{100 * late:.0f}%"></i></div>'
                     f'<span class=cz-small>{_pc(late)} zajedničkih poziva dođe kasno</span></div></div>')
    seq = sequence(cl)
    if seq:
        parts.append('<p class=cz-small style="margin:10px 0 2px">Redoslijed: tko zove prvi (narančasto) i koliko '
                     'minuta kasnije se javljaju ostali</p>' + seq)
    net = network(cl)
    if net:
        parts.append('<details><summary class=cz-small>Mreža računa (deblja linija = više zajedničkih tokena)</summary>'
                     + net + "</details>")
    ex = cl.get("examples") or []
    if ex:
        parts.append('<p class=cz-small style="margin:8px 0 2px">Zadnji zajednički pozivi:</p><p>' + " · ".join(
            f'{tlink(e["token"], e.get("symbol"))} <span class=cz-small>{e["n"]} računa'
            + (f', {e["max24"] * 100:+.0f}%' if e.get("max24") is not None else "") + "</span>" for e in ex[:5]) + "</p>")
    if cl.get("wallets"):
        parts.append(f'<p class=cz-small>Walleti koji kupuju prije njihovih poziva: '
                     f'{", ".join(wlink(w) for w in cl["wallets"][:5])}</p>')
    return "".join(parts) + "</div>"


def kol_cards(clusters, ai_groups):
    if not clusters:
        return '<div class=empty>Još nema dovoljno zajedničkih poziva za grupu.</div>'
    return '<div class=cz-cards>' + "".join(kol_card(cl, ai_groups.get(cl["id"], {})) for cl in clusters[:8]) + "</div>"


# ---------------------------------------------------------------- wallet -> account

def link_strip(x, w=320, h=54):
    """Buy (before the call) -> call (0) -> sell (after): where the wallet sits around the call."""
    lead = max(1.0, x.get("lead_min") or 0)
    span = max(60.0, lead * 1.3)
    left, right = 14, 14
    sc = lambda m: left + (w - left - right) * (m + span) / (2 * span)  # noqa: E731
    sold = x.get("sold_into") or 0
    out = [f'<line x1="{left}" y1="28" x2="{w - right}" y2="28" stroke="var(--line)" stroke-width="2"/>',
           f'<circle cx="{sc(-lead):.0f}" cy="28" r="7" fill="var(--good)"/>'
           f'<text x="{sc(-lead):.0f}" y="14" text-anchor="middle">kupi −{lead:.0f} min</text>',
           f'<line x1="{sc(0):.0f}" y1="16" x2="{sc(0):.0f}" y2="40" stroke="var(--acc)" stroke-width="3"/>'
           f'<text x="{sc(0):.0f}" y="52" text-anchor="middle">poziv</text>']
    if sold:
        out.append(f'<circle cx="{sc(span * 0.55):.0f}" cy="28" r="7" fill="var(--bad)"/>'
                   f'<text x="{sc(span * 0.55):.0f}" y="14" text-anchor="middle">prodaje ({sold}×)</text>')
    return f'<svg class=cz-svg viewBox="0 0 {w} {h}" role=img>' + "".join(out) + "</svg>"


def link_cards(links):
    if not links:
        return '<div class=empty>Još nema walleta koji se ponavljaju prije poziva istog računa.</div>'
    best = {}
    for x in links:                # one card per wallet: its strongest account
        if x["wallet"] not in best:
            best[x["wallet"]] = x
    cards = []
    for x in list(best.values())[:8]:
        others = sorted({y["handle"] for y in links if y["wallet"] == x["wallet"]} - {x["handle"]})
        s = x.get("strength") or 0
        kind, lab = ("bad", "jaka veza") if s >= 0.4 else ("warn", "srednja veza") if s >= 0.2 else ("", "slaba veza")
        say = (f'Ovaj wallet je na {x["tokens"]} od {x["of_calls"]} tokena koje je pozvao {_acct(x["handle"])} kupio '
               f'u prosjeku {x["lead_min"]:.0f} min prije poziva'
               + (f', a na {x["sold_into"]} ih je prodao nakon poziva (izvukao {x["sol_out"]:.1f} SOL od uloženih '
                  f'{x["sol_in"]:.1f})' if x.get("sold_into") else "") + ".")
        if others:
            say += f' Isto radi i kod: {", ".join(_acct(o) for o in others[:4])}.'
        if "sniper" in (x.get("labels") or []):
            say += " Označen je kao snajper, pa dio ovoga može biti slučajnost."
        cards.append(f'<div class=cz-card><h3>{wlink(x["wallet"])} → {_acct(x["handle"])} {badge(lab, kind)}</h3>'
                     f'<p class=cz-say>{say}</p>{link_strip(x)}</div>')
    return '<div class=cz-cards>' + "".join(cards) + "</div>"


# ---------------------------------------------------------------- owner groups

REASON = {"izvor novca": "novac im stiže s istog walleta", "rug klaster": "rug provjera ih je stavila u isti klaster",
          "kupnja u istoj sekundi": "kupuju isti token u istoj sekundi"}


def group_cards(groups, ai_groups):
    if not groups:
        return '<div class=empty>Još nema walleta povezanih istim vlasnikom.</div>'
    cards = []
    for g in groups[:8]:
        a = ai_groups.get(g["id"], {})
        why = ", ".join(f"{REASON.get(k, k)} ({v}×)" for k, v in g["reasons"].items())
        say = f'{g["size"]} walleta koji izgledaju kao jedna osoba ili ekipa: {why}.'
        if g["shared_tokens"]:
            say += f' Zajedno su kupili {g["shared_tokens"]} istih tokena.'
        if g["created"]:
            say += f' Neki od njih je kreirao {g["created"]} tokena (dev).'
        if g["handles"]:
            say += f' Kupuju prije poziva računa {", ".join(_acct(h) for h in g["handles"][:3])}: moguća insider ekipa.'
        if g.get("realized_sol"):
            say += f' Zajednička zarada {g["realized_sol"]:+.1f} SOL.'
        labs = " ".join(badge(f"{wallet_label(k)} {v}", "bad" if k in ("rugger", "insider", "dev", "bundler") else "")
                        for k, v in g["labels"].items())
        kind = "good" if g["score"] >= 70 else "warn" if g["score"] >= 50 else ""
        sb = badge(f"organiziranost {g['score']}", kind)
        dots = "".join(f'<circle cx="{14 + (i % 12) * 22}" cy="{12 + (i // 12) * 22}" r="7" fill="var(--acc)" '
                       f'fill-opacity=".7"><title>{esc(w)}</title></circle>' for i, w in enumerate(g["wallets"][:36]))
        rows = (min(len(g["wallets"]), 36) - 1) // 12 + 1
        cards.append(f'<div class=cz-card id="{g["id"]}"><h3>{esc(a.get("ime") or "Walleti " + g["wallets"][0][:4] + "…")} '
                     f'{sb}</h3><p class=cz-say>{say}</p>'
                     + (f'<p class=cz-say><b>AI:</b> {esc(a["tumacenje"])}</p>' if a.get("tumacenje") else "")
                     + f'<svg class=cz-svg viewBox="0 0 280 {rows * 22 + 4}" style="max-width:280px">{dots}</svg>'
                     + (f'<p>{labs}</p>' if labs else "")
                     + f'<p class=cz-small>{" ".join(wlink(w) for w in g["wallets"][:4])}</p></div>')
    return '<div class=cz-cards>' + "".join(cards) + "</div>"
