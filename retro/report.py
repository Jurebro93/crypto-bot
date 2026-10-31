"""output/retro-stats.json -> output/retro-report.md: the tables the written report quotes (Croatian)."""
import json
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

NAMES = {
    "age_min": "starost (min)", "n_trades": "broj trgovina", "n_buys": "broj kupnji", "uniq_buyers": "različitih kupaca",
    "uniq_sellers": "različitih prodavača", "sell_buy_ratio": "prodaje/kupnje", "buy_sol": "kupljeno SOL",
    "net_sol": "neto SOL u krivulji", "mcap_sol": "mcap (SOL)", "median_buy_sol": "medijan kupnje (SOL)",
    "small_buy_frac": "udio kupnji < 0.05 SOL", "big_buy_frac": "udio kupnji ≥ 2 SOL", "holders": "holdera",
    "top1_pct": "najveći holder %", "top10_pct": "top10 holdera %", "dev_buy_pct": "dev kupio % supplyja",
    "dev_hold_pct": "dev drži %", "dev_sold_frac": "dev prodao udio svoje pozicije", "dev_sold_any": "dev prodao išta",
    "bundle_wallets": "bundle walleta (isti slot)", "bundle_pct": "bundle % supplyja", "snipe3_wallets": "sniperi (≤3 slota)",
    "snipe3_pct": "sniperi % supplyja", "churn_frac": "udio kupaca koji su već prodali", "heavy_wallet_frac": "udio walleta s ≥5 trgovina",
    "last5_buy_share": "udio kupnji u zadnjih 5 min", "dev_prior_creates": "dev: prijašnjih tokena", "dev_fresh": "dev: svjež wallet",
    "has_twitter": "ima X", "has_website": "ima web", "has_telegram": "ima Telegram", "n_socials": "broj mreža",
    "tw_is_status": "X link je tweet (ne profil)", "desc_len": "duljina opisa", "spike_share": "udio rasta u zadnjih 10% vremena (skokovitost)",
    "up_steps": "udio koraka prema gore (postupnost)", "max_dd_pct": "najveći pad od vrha %", "vol": "volatilnost puta",
    "top3_buy_share": "udio SOL-a od 3 najveća kupca", "hours_to_band": "sati do tog mcap-a", "grad_min": "minuta do graduacije",
    "vol6h_usd": "volumen 6 h prije ($)", "vol_last1h_share": "udio volumena u zadnjem satu", "mayhem": "pump.fun mayhem (protokol trguje)",
    "proto_vol_frac": "udio protokolskog volumena", "smart_wallets": "poznatih smart walleta među kupcima",
}
POINTS = {"A15": "15 min nakon kreacije (nasumični pump.fun tokeni)", "G": "trenutak graduacije",
          "B100000": "prvi prelazak $100k mcap", "B1000000": "prvi prelazak $1M mcap", "B10000000": "prvi prelazak $10M mcap"}


def _f(x, d=2):
    if x is None:
        return "–"
    if isinstance(x, float):
        return f"{x:.{d}f}"
    return str(x)


def _pct(x):
    return "–" if x is None else f"{100 * x:.1f}%"


def render(stats):
    out = ["# Retrospektiva: što su imali tokeni koji su skočili", ""]
    pop = stats.get("population", {})
    out += [f"SOL = ${stats['sol_usd']:.0f}. Nasumični tokeni: {pop.get('rand_tokens')} (graduiralo {pop.get('rand_graduated')}), "
            f"graduirani uzorak: {pop.get('grad_tokens')}. Preskočeno (ne-SOL quote / bez cijene): {pop.get('skipped', {}).get('non_sol_or_unpriced', 0)}.", ""]
    for point, p in stats["points"].items():
        out += [f"## Točka odluke: {POINTS.get(point, point)} (n={p['n']})", ""]
        if p["bands"]:
            out += ["Što znači 'skok' po rasponu mcap-a (najveći multiplikator u 7 dana nakon točke):", "",
                    "| mcap raspon | n | ≥2x | ≥3x | ≥5x | ≥10x | ≥100x | medijan | p90 |", "|---|---|---|---|---|---|---|---|---|"]
            for b in p["bands"]:
                out.append(f"| ${b['lo'] / 1000:.0f}k–${b['hi'] / 1000:.0f}k | {b['n']} | {_pct(b['p2'])} | {_pct(b['p3'])} | "
                           f"{_pct(b['p5'])} | {_pct(b['p10'])} | {_pct(b['p100'])} | {_f(b['median'])}x | {_f(b['p90'])}x |")
            out.append("")
        for target, t in p["targets"].items():
            out += [f"### Cilj ≥{target}x: {t['winners']} od {t['n']} ({_pct(t['base_rate'])})", ""]
            feats = sorted(t["features"].items(), key=lambda kv: -abs(kv[1]["auc"] - 0.5))[:14]
            out += ["Signali rangirani po AUC (0.5 = bez signala; >0.5 veća vrijednost = češći skok, <0.5 obrnuto):", "",
                    "| signal | AUC | medijan pobjednici | medijan ostali |", "|---|---|---|---|"]
            for k, f in feats:
                out.append(f"| {NAMES.get(k, k)} | {f['auc']:.2f} | {_f(f['med_win'])} | {_f(f['med_rest'])} |")
            out.append("")
            out += ["Koliko bi tvrdi rez koštao (udio budućih pobjednika koje bi izbacio vs. udio ostalih):", "",
                    "| pravilo | izbacuje pobjednika | izbacuje ostalih | stopa skoka ako prođe | stopa skoka ako se reže |",
                    "|---|---|---|---|---|"]
            for r in t["filters"]:
                out.append(f"| {r['rule']} | {_pct(r['cut_winners'])} ({r['winners_lost']}) | {_pct(r['cut_rest'])} | "
                           f"{_pct(r['rate_if_kept'])} | {_pct(r['rate_if_cut'])} |")
            out.append("")
            m = t.get("model")
            if m:
                out += [f"Logistički model (trening na starijoj polovici, test na novijoj, {m['train']}/{m['test']}): "
                        f"AUC {m['auc_test']:.2f}, top 10% po modelu pogađa {_pct(m['precision_top10'])} vs. baza {_pct(m['base_test'])}.",
                        "Najjače težine: " + ", ".join(f"{NAMES.get(c, c)} {w:+.2f}" for c, w in m["weights"][:8]), ""]
    return "\n".join(out)


def main(outdir=None):
    outdir = outdir or os.path.join(ROOT, "output")
    with open(os.path.join(outdir, "retro-stats.json")) as f:
        stats = json.load(f)
    path = os.path.join(outdir, "retro-report.md")
    with open(path, "w") as f:
        f.write(render(stats))
    return path


if __name__ == "__main__":
    print(main())
