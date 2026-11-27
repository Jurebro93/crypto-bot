"""/pojmovnik (every term on one searchable page) and /api/pojam (the ⓘ pop-up)."""
from ui import glossary as G
from ui.html import esc

# 27.11. (vlasnik: nitko ne smije iz aplikacije izvući recept obrade podataka): for every viewer but an admin the
# glossary keeps the plain one-line answer and drops the long "how it is computed" text of the scoring categories;
# the learning/system and the removed events categories, and the pages the viewer cannot open, are admin-only.
# On /pojmovnik this is class adm-only (run_ui strips it from a non-admin's copy); /api/pojam gets `full`.
DETAIL_CATS = {"ocjene", "kol", "walleti", "grupe", "dugo"}
ADMIN_CATS = {"eventi", "sustav"}


def _admin_only(t):
    """True for a term only an admin may read at all."""
    if t["cat"] in ADMIN_CATS:
        return True
    if t["cat"] == "stranice" and t.get("href"):
        from league import roles
        return roles.deny_get(t["href"], "osnovni") is not None
    return False


def _paras(text):
    return "".join(f"<p>{esc(p)}</p>" for p in (text or "").split("\n\n") if p.strip())


def _example(t):
    return f'<div class=gl-ex><b>Primjer:</b> {esc(t["primjer"])}</div>' if t.get("primjer") else ""


def _body(t, full=True):
    """The long explanation and the example; for a scoring term wrapped adm-only (full=None) or left out (False)."""
    inner = _paras(t["long"]) + _example(t)
    if t["cat"] not in DETAIL_CATS or full is True:
        return inner
    return f"<div class=adm-only>{inner}</div>" if full is None and inner else ""


def _links(t, full=True):
    """Where to see it and the related terms; full=None: admin-only related terms carry adm-only, False: left out."""
    out = []
    if t.get("gdje"):
        out.append("<div class=gl-where><b>Gdje ga vidiš:</b> " + " · ".join(
            f'<a href="{esc(h)}">{esc(n)}</a>' for h, n in t["gdje"]) + "</div>")
    rel = [G.get(k) for k in t.get("vidi", [])]
    rel = [r for r in rel if r and (full is not False or not _admin_only(r))]
    if rel:
        out.append("<div class=gl-rel><b>Povezani pojmovi:</b> " + " ".join(
            f'<a class="gl-chip{" adm-only" if full is None and _admin_only(r) else ""}" href="/pojmovnik#{r["k"]}" '
            f'data-gk="{r["k"]}">{esc(r["name"])}</a>' for r in rel) + "</div>")
    return "".join(out)


def fragment(k, label="", here="", full=True):
    """Body of the ⓘ pop-up: the term, what this particular column/label means (if it says something else) and the
    full explanation. Unknown key -> the short text the page sent along. full=False (not an admin): without the
    long text of the scoring terms and without the admin-only terms."""
    t = G.get(k) if k else None
    if t and not full and _admin_only(t):
        t = None
    if not t:
        return (f"<h3>{esc(label or 'Objašnjenje')}</h3>{_paras(here)}"
                "<p class=mut><a href=/pojmovnik>Svi pojmovi u Pojmovniku →</a></p>")
    b = [f'<div class=gl-cat>{esc(G.CAT_NAME.get(t["cat"], ""))}</div><h3>{esc(t["name"])}</h3>',
         f'<p class=gl-short>{esc(t["short"])}</p>']
    if here and here.strip() != t["short"].strip():
        b.append(f'<div class=gl-here><b>{esc(label or "Ovdje")}:</b> {esc(here)}</div>')
    b.append(_body(t, full) + _links(t, full))
    b.append(f'<p class=mut style="margin-top:12px"><a href="/pojmovnik#{t["k"]}">Otvori u Pojmovniku →</a></p>')
    return "".join(b)


def page(qs):
    terms = G.all_terms()
    by = {}
    for t in terms:
        by.setdefault(t["cat"], []).append(t)
    b = ["<h1>Pojmovnik</h1><p class=lead>Svaki pojam, broj, stupac i stranica u alatu, objašnjeni običnim riječima. "
         "Isto objašnjenje otvara i svaki <span class=tip tabindex=0 data-gk=confidence data-tip='Primjer: klikni da otvoriš objašnjenje pojma Confidence.'>ⓘ</span> u aplikaciji. Upiši riječ u tražilicu "
         "ili klikni kategoriju.</p>",
         '<div class=gl-top><input id=glq type=search placeholder="Traži pojam, npr. likvidnost, moć poziva, rug…" '
         'autocomplete=off></div><nav class=gl-cats>' + "".join(
             f'<a href="#k-{k}"{" class=adm-only" if k in ADMIN_CATS else ""}>{esc(n)} '
             f'<span class=mut>{len(by.get(k, []))}</span></a>' for k, n, _ in CATS_ORDER()
             if by.get(k)) + "</nav>",
         f'<p class=mut id=glcount>{len(terms)} pojmova.</p>']
    for k, n, d in CATS_ORDER():
        items = by.get(k)
        if not items:
            continue
        if k != "stranice":
            items = sorted(items, key=lambda t: G.norm(t["name"]))
        b.append(f'<section class="gl-sec{" adm-only" if k in ADMIN_CATS else ""}" id="k-{k}"><h2>{esc(n)}</h2>'
                 f'<p class=tdesc>{esc(d)}</p>')
        for t in items:
            # 27.11.: internal key names (smart_sell_eksplozija, trade_ok) still find the term, but are not shown
            al = [a for a in t["alias"] if G.norm(a) != G.norm(t["name"]) and "_" not in a]
            b.append(f'<article class="gl-term{" adm-only" if _admin_only(t) else ""}" id="{t["k"]}" data-s="{esc(G.norm(" ".join([t["name"], t["short"], *al])))}">'
                     f'<h3>{esc(t["name"])}<a class=gl-a href="#{t["k"]}" aria-label="Poveznica">#</a></h3>'
                     + (f'<div class="mut gl-al">Zove se i: {esc(", ".join(al[:6]))}</div>' if al else "")
                     + f'<p class=gl-short>{esc(t["short"])}</p>' + _body(t, None) + _links(t, None) + "</article>")
        b.append("</section>")
    b.append("""<script>(()=>{const q=document.getElementById('glq'),c=document.getElementById('glcount'),
arts=[...document.querySelectorAll('.gl-term')],secs=[...document.querySelectorAll('.gl-sec')];
const n=s=>s.toLowerCase().normalize('NFD').replace(/[\\u0300-\\u036f]/g,'').replace(/đ/g,'d');
const run=()=>{const v=n(q.value.trim());let k=0;arts.forEach(a=>{const ok=!v||n(a.dataset.s).includes(v);a.hidden=!ok;if(ok)k++});
 secs.forEach(s=>s.hidden=!s.querySelector('.gl-term:not([hidden])'));c.textContent=v?('Pronađeno: '+k):(arts.length+' pojmova.')};
q.addEventListener('input',run);
const hl=()=>{const t=document.getElementById(decodeURIComponent(location.hash.slice(1)));if(t&&t.classList.contains('gl-term')){
 document.querySelectorAll('.gl-term.hl').forEach(x=>x.classList.remove('hl'));t.classList.add('hl')}};
addEventListener('hashchange',hl);hl()})();</script>""")
    return "Pojmovnik", "".join(b)


def CATS_ORDER():
    return G.CATS
