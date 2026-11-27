"""Invented, deterministic nicknames for persons (27.11., vlasnik: "daj svakoj izmišljeno ime po onome po čemu je
poznata, nešto zanimljivo da ima svoj profil").

The name is built ONLY from a fixed vocabulary below (a role from the person's behaviour + a theme from the tokens it
trades), chosen by a hash of the person id, so it is stable for the same person and data. It never contains a real
person's name, an X handle, a wallet address or anything offensive: words are picked from these lists and nothing
else. osobe/profil.py keeps the first name a person got (os_names), so a name does not change from night to night.
"""
import hashlib

ROLES = {
    "ranoranilac": ("Ranoranilac", "Prorok svijeće", "Onaj koji stigne prvi"),
    "bundler": ("Dirigent snopa", "Majstor svežnja", "Pletač blokova"),
    "hobotnica": ("Hobotnica", "Gospodar novčanika", "Tisuću ruku"),
    "munja": ("Munjeviti", "Brzi prst", "Treptaj"),
    "strpljivi": ("Strpljivi ribar", "Mirni čuvar", "Dugi dah"),
    "zlatoruki": ("Zlatoruki", "Kralj izlaza", "Tihi berač"),
    "optimist": ("Vječni optimist", "Hrabri kupac", "Lovac na dno"),
    "tihi": ("Tihi promatrač", "Sjena s lanca", "Noćni putnik"),
}
THEMES = {
    "pas": "s psećim tokenima", "macka": "iz mačjeg kvarta", "zaba": "iz žabljeg jezera", "ai": "među robotima",
    "politika": "s političkim memeima", "elon": "s Elonovim memeima", "hrana": "iz meme kuhinje",
    "svemir": "sa svemirskim tokenima", "anime": "iz anime ulice", "mjesovito": "s mješovitim memeima",
}
TAGS = ("Jantar", "Kobalt", "Safir", "Bura", "Jugo", "Maestral", "Lavanda", "Koralj", "Smaragd", "Opal", "Kristal",
        "Zora", "Sumrak", "Galeb", "Borovnica", "Kadulja", "Tramontana", "Svitac", "Komet", "Oblutak")

# token name / symbol words -> theme (lower case, substring of the symbol or the name)
THEME_WORDS = {
    "pas": ("dog", "doge", "shib", "inu", "wif", "bonk", "pup", "pupp", "shiba", "corgi", "hound", "woof"),
    "macka": ("cat", "kitty", "meow", "mew", "popcat", "neko", "kitten"),
    "zaba": ("pepe", "frog", "toad", "ribbit", "kek"),
    "ai": ("ai", "gpt", "agent", "bot", "neural", "robo", "llm"),
    "politika": ("trump", "maga", "biden", "melania", "usa", "vote", "kamala"),
    "elon": ("elon", "musk", "doge father", "x ai"),
    "hrana": ("pizza", "burger", "taco", "bread", "cheese", "banana", "milk", "coffee"),
    "svemir": ("moon", "mars", "rocket", "space", "star", "galaxy", "astro"),
    "anime": ("anime", "chan", "kun", "senpai", "waifu", "sama"),
}


def _h(*parts):
    return int(hashlib.sha1("|".join(str(p) for p in parts).encode()).hexdigest(), 16)


def theme_of(text):
    """The theme of one token from its symbol and name, or None."""
    t = (text or "").lower()
    if not t:
        return None
    for theme, words in THEME_WORDS.items():
        for w in words:
            if len(w) <= 3:
                # short words only as a whole token part ("ai" in "AIXBT" yes, but not "rain" or "mainnet")
                if t == w or t.startswith(w) or t.endswith(w):
                    return theme
            elif w in t:
                return theme
    return None


def role_of(tr):
    """tr: the person's traits (osobe/profil.traits) -> a ROLES key, in this order of what is most notable."""
    if (tr.get("pre_pump") or 0) >= 2 and (tr.get("sold_into") or 0) >= 2:
        return "ranoranilac"
    if (tr.get("bundles") or 0) >= 2:
        return "bundler"
    if (tr.get("n_wallets") or 0) >= 6:
        return "hobotnica"
    if (tr.get("pnl_sol") or 0) >= 50:
        return "zlatoruki"
    if tr.get("style") in ("bot", "scalper", "sniper"):
        return "munja"
    if (tr.get("median_hold_min") or 0) >= 24 * 60:
        return "strpljivi"
    if (tr.get("pnl_sol") or 0) <= -5:
        return "optimist"
    return "tihi"


def make(pid, tr, taken=frozenset()):
    """A nickname for person `pid` with traits `tr`, not in `taken` (names other persons already have)."""
    role = role_of(tr)
    theme = tr.get("theme") if tr.get("theme") in THEMES else "mjesovito"
    words = ROLES[role]
    base = f"{words[_h(pid, role) % len(words)]} {THEMES[theme]}"
    if base not in taken:
        return base
    start = _h(pid, "tag")
    for i in range(len(TAGS)):
        name = f"{base} · {TAGS[(start + i) % len(TAGS)]}"
        if name not in taken:
            return name
    n = 2
    while f"{base} · {TAGS[start % len(TAGS)]} {n}" in taken:
        n += 1
    return f"{base} · {TAGS[start % len(TAGS)]} {n}"
