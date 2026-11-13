"""Mirni zajednički elementi ekrana: redak, hero, presuda, segment, točka stanja i hrvatski zapis brojeva.

10.11. (Jure): odobren miran izgled iz prijedloga (audit/2026-11-10/ui-prijedlozi.md, odjeljak 2; makete u
audit/2026-11-10/makete/*.html). Svaki ekran počinje jednim odgovorom (hero), ispod su reci "ime + jedan razlog +
jedan broj", a sve ostalo je na dodir. Ovaj modul je jedino mjesto gdje se te kockice slažu, da svih pet ekrana
izgleda isto; CSS je ui/html.MS_CSS (klase s prefiksom "ms-", vrijednosti prepisane iz maketa).

Pravila za pozivatelje:
  * Sav tekst koji se preda funkcijama se escapea. Gotov HTML (npr. dot(...) ili row(...)) je tipa Html i NE escapea
    se ponovno; za spajanje teksta i takvih komada koristi cat(...), ne "+" (str + Html je običan str i escapea se).
  * Brojevi po pravilu 8: decimalni zarez, razmak (nbsp) za tisućice, jedinica iza broja ("0,100 SOL", "412k $",
    "+18 %"), pravi minus "−". Funkcije num/sol/usd/pct/share/ago vraćaju običan str (escapea se kad uđe u row).
  * Redak koji otvara pop-up tokena (mint=...) treba ui.html.modal() jednom na stranici (postojeći pop-up dokaza).
  * Boja: tone(x) daje "pos"/"neg" za brojeve s predznakom; "warn" samo za upozorenje (rug, probno); "mut" za sivo.
  * Širina kao u maketama: tijelo stranice u <div class="ms-page"> (760 px) ili "ms-page ms-wide" (980 px, stranice
    detalja s dva stupca na računalu); bez toga se stranica širi do 1400 px kao danas.
"""
import html as _html
import time

MINUS = "−"          # pravi minus, kao u maketama ("−0,042 SOL")
NBSP = " "           # tisućice i razmak prije jedinice ne lome redak
DASH = "–"                # nepoznata vrijednost
TONES = ("pos", "neg", "warn", "mut", "acc")
DOTS = ("good", "warn", "bad", "acc")


class Html(str):
    """Gotov, siguran HTML: funkcije ovog modula ga ne escapeaju ponovno."""
    __slots__ = ()


def raw(s):
    """Označi već sigurni HTML (npr. iz postojećih pomoćnika poput ui.html.tlink) da se ne escapea."""
    return Html("" if s is None else s)


def h(x):
    """Escapeaj tekst; Html ostaje kakav jest. None -> ""."""
    if isinstance(x, Html):
        return x
    return Html(_html.escape("" if x is None else str(x)))


def cat(*parts, sep=""):
    """Spoji komade (tekst se escapea, Html ostaje) u jedan Html. None i "" se preskaču.
    Primjer: cat(dot("warn", "samo brzo"), " · 30 poziva")"""
    return Html(h(sep).join(h(p) for p in parts if p not in (None, "")))


def _tone(t):
    return t if t in TONES else ""


def _href(u):
    """Samo unutarnje poveznice, sidra i http(s): javascript: i slično se odbacuje."""
    if not u:
        return None
    s = str(u)
    return s if s.startswith(("/", "#", "?", "https://", "http://")) else None


# ---------- brojevi (pravilo 8) -------------------------------------------------------------------------------------

def num(x, dec=0, sign=False):
    """Broj s decimalnim zarezom i razmakom za tisućice: num(3638) -> "3 638", num(0.1, 3) -> "0,100".
    dec: broj decimala. sign=True: "+" ispred pozitivnog (negativni uvijek dobiju "−"). Nula nema predznak.
    None ili nečitljivo -> "–"."""
    try:
        v = float(x)
    except (TypeError, ValueError):
        return DASH
    if v != v:                                  # NaN
        return DASH
    s = f"{abs(v):,.{dec}f}".replace(",", NBSP).replace(".", ",")
    zero = float(f"{abs(v):.{dec}f}") == 0
    pre = "" if zero else MINUS if v < 0 else "+" if sign else ""
    return pre + s


def sol(x, dec=3, sign=False):
    """Iznos u SOL-u: sol(0.1) -> "0,100 SOL", sol(-0.042, sign=True) -> "−0,042 SOL", sol(2, 2) -> "2,00 SOL"."""
    n = num(x, dec, sign)
    return n if n == DASH else f"{n}{NBSP}SOL"


def usd(x, sign=False):
    """Dolari kratko, za mcap, likvidnost i zaradu: 412000 -> "412k $", 96000 -> "96k $", 9500 -> "9,5k $",
    1234567 -> "1,2M $", 850 -> "850 $", 2.5e9 -> "2,5B $". Od 10k naviše bez decimale (pravilo 8: zaokruženo
    koliko odluka treba). sign=True: "+77 $" / "−185 $"."""
    try:
        v = float(x)
    except (TypeError, ValueError):
        return DASH
    a = abs(v)
    if a >= 1e9:
        body = num(a / 1e9, 1) + "B"
    elif a >= 1e6 or round(a / 1e3) >= 1000:
        body = num(a / 1e6, 0 if a >= 1e8 else 1) + "M"
    elif a >= 1e4:
        body = num(a / 1e3, 0) + "k"
    elif a >= 1e3:
        body = num(a / 1e3, 1) + "k"
    else:
        body = num(a, 0)
    zero = body in ("0",)
    pre = "" if zero else MINUS if v < 0 else "+" if sign else ""
    return f"{pre}{body}{NBSP}$"


def pct(x, dec=0, sign=True, frac=False):
    """Postotak: pct(18) -> "+18 %", pct(-45.7, 1) -> "−45,7 %", pct(70, sign=False) -> "70 %".
    frac=True kad je x udio (0.18 -> "+18 %"). Nula bez predznaka. None -> "–"."""
    try:
        v = float(x) * (100 if frac else 1)
    except (TypeError, ValueError):
        return DASH
    return f"{num(v, dec, sign)}{NBSP}%"


def share(k, n):
    """"21 od 30" (koliko od koliko); n 0/None -> "–"."""
    if not n:
        return DASH
    return f"{num(k)} od {num(n)}"


def ago(ts, now=None):
    """Vrijeme kao "prije 3 min", "prije 2 h", "prije 3 d"; manje od minute ili u budućnosti -> "upravo sada".
    ts: unix sekunde. None/0 -> "–"."""
    if not ts:
        return DASH
    d = (time.time() if now is None else now) - float(ts)
    if d < 60:
        return "upravo sada"
    if d < 3600:
        return f"prije {int(d // 60)} min"
    if d < 86400:
        return f"prije {int(d // 3600)} h"
    return f"prije {int(d // 86400)} d"


def tone(x):
    """Boja broja s predznakom: "pos" za > 0, "neg" za < 0, "" za 0 ili None (pravilo 4: zeleno/crveno samo za to)."""
    try:
        v = float(x)
    except (TypeError, ValueError):
        return ""
    return "pos" if v > 0 else "neg" if v < 0 else ""


# ---------- elementi ------------------------------------------------------------------------------------------------

def dot(kind="", word=None):
    """Točka stanja od 8 px i riječ (pravilo 5: stanje je riječ ili točka, bez emojija):
    dot("good", "dokazan") -> "● dokazan". kind: "good" (zeleno), "warn" (narančasto), "bad" (crveno), "acc"
    (naglasak), "" (sivo). word može biti tekst ili Html; bez word samo točka."""
    k = kind if kind in DOTS else ""
    return Html(f'<span class="ms-dot{" " + k if k else ""}" aria-hidden="true"></span>' + (h(word) if word else ""))


def top(title, sub=None, icon_href=None, icon_label="Traži"):
    """Naslov ekrana (34 px) i jedan sporedni redak ispod (15 px). icon_href: okrugla ikona povećala desno
    (npr. "/trazi"), samo na mobitelu. Vraća Html."""
    ico = ""
    if _href(icon_href):
        ico = (f'<a class="ms-ico" href="{h(_href(icon_href))}" aria-label="{h(icon_label)}">'
               '<svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="11" cy="11" r="6.5"/>'
               '<path d="M20 20l-4.2-4.2"/></svg></a>')
    out = f'<div class="ms-top"><h1 class="ms-h1">{h(title)}</h1>{ico}</div>'
    if sub:
        out += f'<p class="ms-sub">{h(sub)}</p>'
    return Html(out)


def hero(answer, why=None, label=None, facts=None, href=None, mint=None, foot=None, big=False, unit=None):
    """Jedan odgovor ekrana (pravilo 1): veliko ime ili broj i jedna rečenica zašto.

    answer: ime ili broj (tekst/Html), npr. "GIGAFROG" ili "2,00".
    why:    jedna rečenica zašto (tekst/Html).
    label:  sitni natpis iznad, npr. "Najbolji ulaz sada".
    facts:  jedan redak činjenica ispod imena, npr. cat(dot("good", "dokazan"), " · ocjena 58").
    href:   cijeli panel vodi na tu stranicu (dobiva strelicu). mint: umjesto toga otvara pop-up tokena (modal()).
    foot:   redak na dnu panela odvojen crtom, npr. "Ulog u demu 25–50 $ · još je u zoni ulaza".
    big:    True = goli veliki broj (48 px, bez panela), za vrijednost walleta; tada unit ide sitnije iza broja
            ("2,00" + unit "SOL"), a why je sivi redak ispod ("≈ 323 $ · danas 0,00 SOL").
    Vraća Html."""
    if big:
        u = f"<small>{h(unit)}</small>" if unit else ""
        return Html('<div class="ms-hero">' + (f'<div class="ms-lbl">{h(label)}</div>' if label else "")
                    + f'<div class="ms-big">{h(answer)}{u}</div>'
                    + (f'<div class="ms-line">{h(why)}</div>' if why else "") + "</div>")
    link = _href(href)
    inner = ((f'<div class="ms-lbl">{h(label)}</div>' if label else "")
             + f'<div class="ms-name"><span>{h(answer)}</span>'
             + ('<span class="ms-chev" aria-hidden="true"></span>' if (link or mint) else "") + "</div>"
             + (f'<div class="ms-facts">{h(facts)}</div>' if facts else "")
             + (f"<p>{h(why)}</p>" if why else "")
             + (f'<div class="ms-go">{h(foot)}</div>' if foot else ""))
    if link:
        return Html(f'<a class="ms-panel" href="{h(link)}">{inner}</a>')
    if mint:
        return Html(f'<div class="ms-panel ms-tap" role="button" tabindex="0" data-mint="{h(mint)}">{inner}</div>')
    return Html(f'<div class="ms-panel">{inner}</div>')


def verdict(word, sentence=None, label=None, facts=None, kind=None):
    """Panel presude na vrhu stranice detalja (token, influencer, novčanik): sitni natpis, presuda velikim slovima,
    jedan redak činjenica s točkom stanja, jedna rečenica s brojkama.

    word:     presuda, npr. "Samo za brzi izlaz" (tekst/Html).
    sentence: jedna rečenica, npr. "U prvom satu 21 od 30 poziva dođe do +10 %. Ako držiš dan, 28 od 30 je u minusu."
    label:    npr. "Presuda za zadnjih 14 dana".
    facts:    npr. "samo brzo · 30 poziva · ocjena 58"; ako je zadan kind, ispred ide točka te boje.
    kind:     boja točke ("good"/"warn"/"bad"/"acc"/""), npr. ui.kolsummary.VERDICT_DOT[key].
    Vraća Html."""
    f = cat(dot(kind or ""), facts) if (facts and kind is not None) else facts
    return Html('<div class="ms-panel ms-verdict">' + (f'<div class="ms-lbl">{h(label)}</div>' if label else "")
                + f'<div class="ms-name">{h(word)}</div>'
                + (f'<div class="ms-facts">{h(f)}</div>' if f else "")
                + (f"<p>{h(sentence)}</p>" if sentence else "") + "</div>")


def row(name, reason=None, value=None, sub=None, href=None, mint=None, rank=None, value_tone=None, sub_tone=None,
        reason_tone=None, title=None, muted=False):
    """Jedan redak popisa (pravilo 2): lijevo ime i jedan redak razloga, desno jedan broj i ispod najviše jedan
    sporedni, pa strelica. Cijeli redak je jedan dodir.

    name:   ime (simbol, @račun, kratka adresa), tekst/Html; 17 px, debljina 600.
    reason: jedan redak razloga (15 px, sivo), npr. "3 smart walleta među prvim kupcima" ili cat(dot("good"), "dokazan").
    value:  jedan broj desno (17 px, 600), već formatiran: npr. pct(18), usd(412000), "83".
    sub:    najviše jedan sporedni broj ispod value (15 px, sivo), npr. "268k $" ili "ocjena".
    href:   redak vodi na tu stranicu (npr. "/kol/ime"). mint: redak otvara postojeći pop-up tokena
            (/api/evidence/<mint>; stranica treba ui.html.modal()). Bez oba: redak bez strelice.
    rank:   mjesto na ljestvici (broj lijevo, sivo), npr. 1.
    value_tone / sub_tone / reason_tone: "pos", "neg", "warn", "mut" ili "acc" (tone(x) za brojeve s predznakom).
    title:  tooltip cijelog retka (računalo).
    muted:  sivi brojevi (npr. skupina "Premalo poziva").
    Vraća Html (stavi ga u rows([...]))."""
    vt, st, rt = _tone(value_tone), _tone(sub_tone), _tone(reason_tone)
    left = ((f'<span class="ms-rk">{h(rank)}</span>' if rank not in (None, "") else "")
            + f'<div class="ms-m"><div class="ms-t">{h(name)}</div>'
            + (f'<div class="ms-s{" " + rt if rt else ""}">{h(reason)}</div>' if reason not in (None, "") else "")
            + "</div>")
    right = ""
    if value not in (None, "") or sub not in (None, ""):
        right = ('<div class="ms-e">'
                 + (f'<div class="ms-v{" " + vt if vt else ""}">{h(value)}</div>' if value not in (None, "") else "")
                 + (f'<div class="ms-s{" " + st if st else ""}">{h(sub)}</div>' if sub not in (None, "") else "")
                 + "</div>")
    link = _href(href)
    tap = bool(link or mint)
    chev = '<span class="ms-chev" aria-hidden="true"></span>' if tap else ""
    cls = "ms-row" + (" ms-mut" if muted else "") + (" ms-tap" if mint and not link else "")
    t = f' title="{h(title)}"' if title else ""
    if link:
        return Html(f'<a class="{cls}" href="{h(link)}"{t}>{left}{right}{chev}</a>')
    if mint:
        return Html(f'<div class="{cls}" role="button" tabindex="0" data-mint="{h(mint)}"{t}>{left}{right}{chev}</div>')
    return Html(f'<div class="{cls}"{t}>{left}{right}</div>')


def rows(items, empty=None, cls=None):
    """Popis redaka: items su gotovi row(...) ili dictovi s argumentima za row (npr. {"name": "ARIA", "value": "83"}).
    empty: jedna rečenica kad je popis prazan (inače ""). cls: dodatna klasa popisa. Vraća Html (<ul class=ms-list>)."""
    out = []
    for it in items or ():
        r = row(**it) if isinstance(it, dict) else h(it)
        out.append(f"<li>{r}</li>")
    if not out:
        return Html(f'<p class="ms-hint">{h(empty)}</p>') if empty else Html("")
    return Html(f'<ul class="ms-list{" " + h(cls) if cls else ""}">{"".join(out)}</ul>')


def section(title, link_text=None, href=None, sid=None):
    """Naslov sekcije (22 px) s najviše jednom poveznicom desno, npr. section("Zadnji pozivi", "Svih 76", "/kol/x/pozivi").
    sid: id za sidro. Vraća Html."""
    a = f'<a href="{h(_href(href))}">{h(link_text)}</a>' if (link_text and _href(href)) else ""
    i = f' id="{h(sid)}"' if sid else ""
    return Html(f'<h2 class="ms-h2"{i}><span>{h(title)}</span>{a}</h2>')


def hint(text):
    """Najviše jedna rečenica objašnjenja na dnu popisa (pravilo 6), 15 px, sivo. Vraća Html."""
    return Html(f'<p class="ms-hint">{h(text)}</p>')


def colhead(left, right):
    """Zaglavlje stupaca iznad popisa (13 px), npr. colhead("Influencer", "1 h · 24 h"). Vraća Html."""
    return Html(f'<div class="ms-colhead"><span>{h(left)}</span><span>{h(right)}</span></div>')


def seg(items, cur):
    """Segmentirani izbor preko cijele širine (jedan po ekranu), npr. seg([("/tokens", "Novi"),
    ("/tokens/jaki", "Jaki"), ("/dugorocno", "Dugoročni")], "/tokens"). items: [(href, natpis)]; upaljen je onaj
    čiji je href jednak cur. Obične poveznice, pa radi i na spremljenim stranicama. Vraća Html."""
    out = []
    for href, label in items:
        link = _href(href) or "#"
        on = ' class="on" aria-current="page"' if href == cur else ""
        out.append(f'<a href="{h(link)}"{on}>{h(label)}</a>')
    return Html(f'<nav class="ms-seg">{"".join(out)}</nav>')
