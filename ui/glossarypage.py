"""/pojmovnik (every term on one searchable page) and /api/pojam (the ⓘ pop-up)."""
from ui import glossary as G
from ui.html import esc


def _paras(text):
    return "".join(f"<p>{esc(p)}</p>" for p in (text or "").split("\n\n") if p.strip())


def _links(t):
    out = []
    if t.get("primjer"):
        out.append(f'<div class=gl-ex><b>Primjer:</b> {esc(t["primjer"])}</div>')
    if t.get("gdje"):
        out.append("<div class=gl-where><b>Gdje ga vidiš:</b> " + " · ".join(
            f'<a href="{esc(h)}">{esc(n)}</a>' for h, n in t["gdje"]) + "</div>")
    rel = [G.get(k) for k in t.get("vidi", [])]
    rel = [r for r in rel if r]
    if rel:
        out.append("<div class=gl-rel><b>Povezani pojmovi:</b> " + " ".join(
            f'<a class=gl-chip href="/pojmovnik#{r["k"]}" data-gk="{r["k"]}">{esc(r["name"])}</a>' for r in rel) + "</div>")
    return "".join(out)


def fragment(k, label="", here=""):
    """Body of the ⓘ pop-up: the term, what this particular column/label means (if it says something else) and the
    full explanation. Unknown key -> the short text the page sent along."""
    t = G.get(k) if k else None
    if not t:
        return (f"<h3>{esc(label or 'Objašnjenje')}</h3>{_paras(here)}"
                "<p class=mut><a href=/pojmovnik>Svi pojmovi u Pojmovniku →</a></p>")
    b = [f'<div class=gl-cat>{esc(G.CAT_NAME.get(t["cat"], ""))}</div><h3>{esc(t["name"])}</h3>',
         f'<p class=gl-short>{esc(t["short"])}</p>']
    if here and here.strip() != t["short"].strip():
        b.append(f'<div class=gl-here><b>{esc(label or "Ovdje")}:</b> {esc(here)}</div>')
    b.append(_paras(t["long"]) + _links(t))
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
             f'<a href="#k-{k}">{esc(n)} <span class=mut>{len(by.get(k, []))}</span></a>' for k, n, _ in CATS_ORDER()
             if by.get(k)) + "</nav>",
         f'<p class=mut id=glcount>{len(terms)} pojmova.</p>']
    for k, n, d in CATS_ORDER():
        items = by.get(k)
        if not items:
            continue
        if k != "stranice":
            items = sorted(items, key=lambda t: G.norm(t["name"]))
        b.append(f'<section class=gl-sec id="k-{k}"><h2>{esc(n)}</h2><p class=tdesc>{esc(d)}</p>')
        for t in items:
            al = [a for a in t["alias"] if G.norm(a) != G.norm(t["name"])]
            b.append(f'<article class=gl-term id="{t["k"]}" data-s="{esc(G.norm(" ".join([t["name"], t["short"], *al])))}">'
                     f'<h3>{esc(t["name"])}<a class=gl-a href="#{t["k"]}" aria-label="Poveznica">#</a></h3>'
                     + (f'<div class="mut gl-al">Zove se i: {esc(", ".join(al[:6]))}</div>' if al else "")
                     + f'<p class=gl-short>{esc(t["short"])}</p>' + _paras(t["long"]) + _links(t) + "</article>")
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
