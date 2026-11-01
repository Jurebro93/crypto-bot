"""What launching costs on each path. Approximate numbers checked 1.11.2026, shown as "procjena" on the page.

Sources: Raydium docs (CPMM pool: 0.15 SOL protocol fee + ~0.04 SOL rent, budget ~0.2 SOL), pump.fun fee page
(creating a coin ~0-0.02 SOL, coin graduates to PumpSwap when the bonding curve fills, ~85 SOL / ~$70k market cap).
Meteora pool creation is an estimate (rent + fees ~0.05-0.1 SOL).
"""

PATHS = {
    "pumpfun": {
        "name": "pump.fun (besplatno)",
        "short": "pump.fun",
        "free": True,
        "how": "Token se kreira na pump.fun. Nema vlastitog poola: cijena ide po krivulji, kupci sami dodaju "
               "likvidnost. Kad se krivulja napuni (oko 85 SOL, otprilike $70k tržišne vrijednosti), token sam "
               "prelazi na PumpSwap i likvidnost se zaključava zauvijek.",
        "plus": ["skoro besplatno (samo mrežne naknade)", "likvidnost se ne može povući, kupci to vole",
                 "kreator dobiva mali dio svake trgovine", "naš anti-rug filter ga odmah prolazi (mint i freeze isključeni)"],
        "minus": ["supply je uvijek 1 milijarda, 6 decimala", "snajperski botovi kupuju u prvim sekundama",
                  "većina tokena nikad ne napuni krivulju (manje od 2%)"],
        "fixed_sol": 0.02,
    },
    "meteora": {
        "name": "Meteora pool (plaćeno, vlastita likvidnost)",
        "short": "Meteora",
        "free": False,
        "how": "Sami kreiramo token i pool na Meteori (DAMM) i u njega stavimo SOL + dio tokena. Naknade za "
               "trgovanje mogu biti visoke na početku pa padaju, što smanjuje štetu od snajpera.",
        "plus": ["biramo supply i decimale", "dinamične naknade štite od snajpera", "naknade od trgovanja idu nama"],
        "minus": ["treba vlastiti SOL za likvidnost", "LP tokene treba zaključati ili spaliti, inače izgleda kao rug"],
        "fixed_sol": 0.1,
    },
    "raydium": {
        "name": "Raydium pool (plaćeno, vlastita likvidnost)",
        "short": "Raydium",
        "free": False,
        "how": "Sami kreiramo token i Raydium CPMM pool (0.15 SOL naknada Raydiumu + ~0.04 SOL najma) i u njega "
               "stavimo SOL + dio tokena.",
        "plus": ["najpoznatija burza na Solani, svi botovi i agregatori je vide", "biramo supply i decimale"],
        "minus": ["treba vlastiti SOL za likvidnost", "LP tokene treba spaliti, inače izgleda kao rug",
                  "nema zaštite od snajpera"],
        "fixed_sol": 0.2,
    },
}

MINT_SOL = 0.02          # token mint + Metaplex metadata + revoking mint/freeze authority, all in network rent/fees

# optional paid extras (USD), each with what it buys
EXTRAS = [
    ("DexScreener profil (Enhanced Token Info)", 299, "logo, opis i linkovi na DexScreeneru; ljudi ga traže prije kupnje"),
    ("DexScreener Boost (10x, 12 h)", 99, "token gore na listi trending; kratko traje, ima smisla tek uz val objava"),
    ("Web stranica (vlastita domena)", 15, "domena godišnje; stranica sama besplatno (Netlify/Carrd)"),
]


def launch_cost(p, sol_usd):
    """{rows: [(item, SOL, USD, note)], sol, usd} for one project on its launch path."""
    path = PATHS.get(p.get("launch") or "pumpfun", PATHS["pumpfun"])
    rows = [("Kreiranje tokena i metapodataka", path["fixed_sol"] if p.get("launch") == "pumpfun" else MINT_SOL,
             "mrežne naknade i najam računa")]
    if p.get("launch") != "pumpfun":
        rows.append((f"Kreiranje {path['short']} poola", path["fixed_sol"], "naknada platformi + najam"))
        rows.append(("Likvidnost u poolu", float(p.get("liq_sol") or 0), "ostaje u poolu; s tim se trguje"))
    if p.get("dev_buy_sol"):
        rows.append(("Naša prva kupnja (dev buy)", float(p["dev_buy_sol"]),
                     "kupujemo prvi prije snajpera; ti tokeni su naši"))
    sol = sum(r[1] for r in rows)
    out = [(name, s, s * sol_usd if sol_usd else None, note) for name, s, note in rows]
    mkt = float(p.get("mkt_usd") or 0)
    if mkt:
        out.append(("Marketing (influenceri, boost, objave)", None, mkt, "budžet iz forme, raspodjela u planu ispod"))
    usd = (sol * sol_usd if sol_usd else 0) + mkt
    return {"rows": out, "sol": sol, "usd": usd, "path": path}


def supply_split(p):
    """Where the supply goes: (label, percent, note)."""
    infl, team = float(p.get("infl_pct") or 0), float(p.get("team_pct") or 0)
    if p.get("launch") == "pumpfun":
        rest = 100 - infl - team
        return [("Krivulja na pump.fun (javna prodaja)", rest, "kupuje bilo tko; mi kupujemo dev buyem"),
                ("Influenceri (iz naše kupnje, s rasporedom)", infl, "dijelimo postupno, ne odjednom"),
                ("Tim / trezor (iz naše kupnje)", team, "zaključati na 3-6 mjeseci, javno objaviti adresu")]
    pool = 100 - infl - team
    return [("Pool (likvidnost za trgovanje)", pool, "LP tokeni se spale da nitko ne može povući likvidnost"),
            ("Influenceri (s rasporedom)", infl, "dijelimo postupno, ne odjednom"),
            ("Tim / trezor", team, "zaključati na 3-6 mjeseci, javno objaviti adresu")]


def share_per_player(total_usd, have_usd, players):
    """Suggested donation per player so the vault reaches the launch budget."""
    if not players:
        return 0.0
    return max(0.0, (total_usd or 0) - (have_usd or 0)) / len(players)


def pump_buy_pct(sol):
    """% of the 1 B supply a first buy of `sol` gets on the pump.fun curve (virtual reserves 30 SOL / 1.073 B
    tokens, constant product). 1 SOL ≈ 3.5%, 3 SOL ≈ 9.8%. Before the 1% trading fee."""
    sol = max(0.0, float(sol or 0))
    return 1_073_000_000 * sol / (30 + sol) / 1e9 * 100


def pump_sol_for_pct(pct):
    """SOL the first buy needs to get `pct` % of the supply (inverse of pump_buy_pct)."""
    t = pct / 100 * 1e9
    return 30 * t / (1_073_000_000 - t) if t < 1_073_000_000 else float("inf")
