"""output/bnb_novcanici.md (written by every pass) and the one log line "bnb: ..." with the funnel."""
import os
import time

from bnb import klasa, pogled, store

OUT_DIR = os.environ.get("BNB_OUT_DIR") or os.path.join(store.ROOT, "output")
OUT_NAME = "bnb_novcanici.md"
CLS_HR = {"prije_pumpe": "kupuje prije pumpe", "kandidat": "kandidat (2 pumpe)", "bot": "bot", "snajper": "snajper",
          "kupuje_sve": "kupuje sve", "market_maker": "market maker", "jednokratni": "jednokratni",
          "bez_placanja": "bez plaćene kupnje", "ugovor": "ugovor (adresa s kodom)", "router": "router / burza",
          "relayer": "relayer", "promatra": "promatra se"}


def _t(ts):
    return time.strftime("%d.%m.%Y.", time.gmtime(ts)) if ts else "—"


def line(con, out=None):
    f = pogled.funnel(None) if out is None else (out.get("lijevak") or {})
    head = klasa.funnel_line(f)
    if out:
        head += f"; {out.get('secs', 0):.0f} s" + (f", prekinuto: {out['cut']}" if out.get("cut") else "")
    return head


def markdown(c):
    s = pogled.summary()
    f = pogled.funnel()
    gs = pogled.groups("prije_pumpe", 100)
    ks = pogled.groups("kandidat", 30)
    m = pogled.measurement(50)
    L = ["# BNB Smart Chain: novčanici koji kupuju prije pumpe", "",
         f"Prolaz {time.strftime('%d.%m. %H:%M', time.gmtime(s['updated'])) if s['updated'] else '—'} UTC. "
         "Statistika, ne optužba: adresa na popisu je više puta kupila prije skoka i prodala u skok; ništa ne kaže tko "
         "je ni zašto. Samo analiza i mjerenje: na BSC-u alat ne trguje.", "",
         klasa.funnel_line(f), "",
         f"Tokena u pojasu {s['tokens']}, pumpi {s['pumps']}, pročitano {s['read']}, swapova {s['trades']:,}, "
         f"baza {s['db_mb']} MB.", "", "## Popis (potvrđeni prvi)", "",
         "| adresa | pumpe (simbol, datum, tier) | vodstvo med. min | rezultat $ | potvrđeno |", "|---|---|---|---|---|"]
    for g in gs:
        ps = ", ".join(f"{p['symbol']} {_t(p['t0'])} {'15M+' if p['tier'] == 'pumpa15' else '2-15M'}"
                       for p in g["pumps"][:8])
        L.append(f"| {g['address']} | {ps} | {g['med_lead_min']} | {g['pnl_usd']} | {'da' if g['confirmed'] else 'ne'} |")
    if not gs:
        L.append("| — | | | | |")
    L += ["", "## Kandidati (2 pumpe)", "", "| adresa | pumpe | rezultat $ |", "|---|---|---|"]
    for g in ks:
        L.append(f"| {g['address']} | {', '.join(str(p['symbol']) for p in g['pumps'][:6])} | {g['pnl_usd']} |")
    if not ks:
        L.append("| — | | |")
    kl = f.get("klase") or {}
    L += ["", "Isključeno (razlog): " + (", ".join(f"{CLS_HR.get(k, k)} {v}" for k, v in sorted(kl.items())
                                                   if k not in ("prije_pumpe", "kandidat", "promatra")) or "—"), "",
          "## Mjerenje novih kupnji (postotak nakon troška, bez računa i novca)", "",
          "| izvor | signala | izmjereno | promašeno | otvoreno | prosjek uz 50 $ | uz 250 $ | dobitnih % | medijan "
          "kašnjenja s |", "|---|---|---|---|---|---|---|---|---|"]
    for src, x in (m.get("by_source") or {}).items():
        L.append(f"| {src} | {x['signals']} | {x['measured']} | {x['misses']} | {x['open']} | {x['mean_net_50_pct']} | "
                 f"{x['mean_net_250_pct']} | {x['win_pct']} | {x['median_delay_s']} |")
    L += ["", "## Pretpostavka", "",
          "- vrh pumpe = najviše zatvaranje (satno / dnevno); MC vrha = današnji MC × vrh / zadnje zatvaranje",
          "- besplatni javni RPC čuva logove ~24 dana: starije pumpe su \"izvan dosega\" (nisu pročitane)",
          "- grupa = jedna adresa (spajanje po financijeru treba plaćeni indeks)",
          f"- trošak kruga na BSC-u nikad ispod {c['rt_floor'] * 100:.0f} %", ""]
    return "\n".join(L) + "\n"


def write(con, c):
    os.makedirs(OUT_DIR, exist_ok=True)
    text = markdown(c)
    with open(os.path.join(OUT_DIR, OUT_NAME), "w", encoding="utf-8") as f:
        f.write(text)
    return text
