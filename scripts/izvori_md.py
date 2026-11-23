"""Write docs/seo/izvori_2311.md from ui/blogsources.py: every outside source, where it is used, what it supports and
the day it was checked. Run after changing ui/blogsources.py: python3 scripts/izvori_md.py
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from ui import blogsources as BS  # noqa: E402

OUT = os.path.join(ROOT, "docs", "seo", "izvori_2311.md")


def main():
    used = BS.used()
    lines = [
        "# Vanjski izvori na uredničkim stranicama (23. 11. 2026.)",
        "",
        "Generirano iz `ui/blogsources.py` (`python3 scripts/izvori_md.py`). Svaki URL je dohvaćen 23. 11. 2026.,",
        "stranica se učitala i pročitano je da podržava tvrdnju uz koju stoji. Poveznica koja se nije mogla provjeriti nije",
        "dodana (npr. solana.com/docs, sec.gov i eur-lex.europa.eu iz ovog okruženja vraćaju provjeru preglednika ili 403).",
        "Vanjske poveznice renderiraju se kao i ostatak stranice: `rel=\"nofollow noopener\" target=_blank`.",
        "Test `tests/test_urednicki_izvori_offline.py` ruši se ako blog ili rječnik vodi na URL koji nije u ovoj tablici.",
        "",
        f"Ukupno izvora: {len(BS.S)}; blog postova s izvorima: {len(BS.POSTS)}; pojmova u rječniku s izvorima: "
        f"{len(BS.GLOSS)}.",
        "",
        "| # | URL | Izdavač | Gdje se koristi | Što podržava | Provjereno |",
        "|---|-----|---------|-----------------|--------------|------------|",
    ]
    for i, (k, (url, pub, _title, sup_en, _sup_hr)) in enumerate(BS.S.items(), 1):
        where = ", ".join(used[k]) or "(samo u tekstu)"
        lines.append(f"| {i} | {url} | {pub} | {where} (+ /hr/ inačice) | {sup_en} | {BS.VERIFIED} |")
    lines += ["", "Napomena: na /blog/... i /glossary/... popisu iznad uvijek je i hrvatska inačica iste stranice "
              "(/hr/blog/..., /hr/rjecnik/...) s istim izvorima.", ""]
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    print("ok", OUT, len(BS.S))


if __name__ == "__main__":
    main()
