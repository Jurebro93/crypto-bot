"""Small interactive calculators for blog posts (plain HTML + a few lines of JS, readable without JS too).

- tax(lang):       Croatian crypto tax for an individual (12% on gains held under two years, same-year losses, €2 rule)
- company(lang):   tax on a crypto gain held privately vs through a d.o.o. (10%/18% profit tax + 12% dividend tax)
- slippage(lang):  fewer tokens than quoted for a buy size in a constant-product pool
Each returns one <figure>; numbers update as the reader types. Rates are the same as in the posts' text.
"""
CSS = """
.calc{margin:28px 0;border:1px solid var(--line);border-radius:18px;padding:18px 20px;background:var(--soft)}
.calc figcaption b{font-size:17px;display:block}.calc figcaption span{color:var(--mut);font-size:14px}
.calc .ci{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:12px;margin:14px 0}
.calc label{font-size:13.5px;font-weight:600;color:var(--mut);display:block}
.calc input,.calc select{width:100%;margin-top:4px;border:1px solid var(--line);border-radius:12px;padding:10px 12px;
font:inherit;font-size:16px;background:#fff;color:var(--fg)}
.calc .co{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:10px}
.calc .co div{background:#fff;border:1px solid var(--line);border-radius:14px;padding:12px 14px}
.calc .co b{display:block;font-size:24px;letter-spacing:-.02em;font-variant-numeric:tabular-nums}
.calc .co span{color:var(--mut);font-size:13px}.calc .co .hi b{color:#2a78d6}
.calc .cn{color:var(--mut);font-size:13.5px;margin:10px 0 0}
.calc .cb{display:grid;gap:8px;margin-top:6px}.calc .cb div{display:grid;grid-template-columns:minmax(120px,38%) 1fr;gap:10px;
align-items:center;font-size:14.5px}.calc .cb i{display:block;height:16px;border-radius:0 4px 4px 0;background:#2a78d6;
min-width:2px;transition:width .2s}.calc .cb i.g{background:#b8c0cc}.calc .cb em{font-style:normal;font-weight:650;
font-variant-numeric:tabular-nums;margin-left:8px}.calc .cb p{margin:0;display:flex;align-items:center}
@media(max-width:560px){.calc .cb div{grid-template-columns:1fr}}
"""

_FMT = ("<script>function crF(l,v,c){return new Intl.NumberFormat(l=='hr'?'hr-HR':'en-IE',"
        "{style:'currency',currency:c||'EUR',maximumFractionDigits:0}).format(v)}</script>")

T = {
    "en": dict(
        t_h="Crypto tax calculator (Croatia)", t_sub="Individuals, Croatian tax resident. Amounts in euros.",
        buy="Bought for (€)", sell="Sold or spent for (€)", held="Months held", loss="Other losses this year (€)",
        gain="Gain", tax="Tax to pay (12%)", keep="You keep",
        ex="Held over two years: no tax.", small="Tax of €2 or less: nothing to file.",
        nogain="No gain: nothing to pay, and the loss can offset other gains this year.",
        ok="Report on JOPPD in ePorezna and pay by the end of February next year.",
        c_h="Private or through a company?", c_sub="Tax until the gain reaches the owner's pocket. Simplified.",
        cgain="Crypto gain (€)", rev="Company's yearly revenue", r1="Up to €1 million (10% profit tax)",
        r2="Over €1 million (18% profit tax)",
        p2="Privately, held over 2 years", p1="Privately, held under 2 years", d="d.o.o., then paid out as dividend",
        s_h="Slippage calculator", s_sub="How many fewer tokens you get than the quoted price, before fees.",
        size="Buy size ($)", liq="Pool liquidity ($)", lose="Fewer tokens", cost="Hidden cost",
        s_ok="Under 2% of the pool: fine.", s_warn="Over 2% of the pool: split the buy or pick a deeper pool.",
    ),
    "hr": dict(
        t_h="Kalkulator poreza na kripto (Hrvatska)", t_sub="Fizičke osobe, porezni rezidenti Hrvatske. Iznosi u eurima.",
        buy="Kupljeno za (€)", sell="Prodano ili potrošeno za (€)", held="Mjeseci držanja",
        loss="Drugi gubici ove godine (€)", gain="Dobit", tax="Porez za platiti (12%)", keep="Ostaje ti",
        ex="Držano dulje od dvije godine: nema poreza.", small="Porez 2 € ili manje: ništa se ne prijavljuje.",
        nogain="Nema dobiti: ništa se ne plaća, a gubitak umanjuje druge dobiti ove godine.",
        ok="Prijavi na JOPPD-u u ePoreznoj i plati do kraja veljače sljedeće godine.",
        c_h="Privatno ili preko firme?", c_sub="Porez dok dobit ne stigne do vlasnika. Pojednostavljeno.",
        cgain="Kripto dobit (€)", rev="Godišnji prihod firme", r1="Do 1 milijun € (porez na dobit 10%)",
        r2="Iznad 1 milijun € (porez na dobit 18%)",
        p2="Privatno, držano dulje od 2 godine", p1="Privatno, držano kraće od 2 godine", d="d.o.o., pa isplata dividende",
        s_h="Kalkulator slippagea", s_sub="Koliko manje tokena dobiješ od prikazane cijene, prije naknada.",
        size="Iznos kupnje ($)", liq="Likvidnost bazena ($)", lose="Manje tokena", cost="Skriveni trošak",
        s_ok="Ispod 2% bazena: u redu.", s_warn="Iznad 2% bazena: podijeli kupnju ili odaberi dublji bazen.",
    ),
}


def _in(i, label, val, step="1"):
    return f"<label>{label}<input id={i} type=number inputmode=decimal min=0 step={step} value={val}></label>"


def tax(lang="en"):
    t, k = T[lang], "tx" + lang
    return (f"<figure class=calc id={k}><figcaption><b>{t['t_h']}</b><span>{t['t_sub']}</span></figcaption>"
            f"<div class=ci>{_in(k + 'b', t['buy'], 1000)}{_in(k + 's', t['sell'], 1500)}{_in(k + 'm', t['held'], 8)}"
            f"{_in(k + 'l', t['loss'], 0)}</div><div class=co><div><b id={k}g>€500</b><span>{t['gain']}</span></div>"
            f"<div class=hi><b id={k}t>€60</b><span>{t['tax']}</span></div><div><b id={k}k>€1,440</b>"
            f"<span>{t['keep']}</span></div></div><p class=cn id={k}n>{t['ok']}</p></figure>" + _FMT +
            f"<script>(function(){{var k='{k}',L='{lang}',T={{ex:{_js(t['ex'])},sm:{_js(t['small'])},"
            f"ng:{_js(t['nogain'])},ok:{_js(t['ok'])}}};function g(x){{return Math.max(0,parseFloat("
            "document.getElementById(k+x).value)||0)}function u(){var b=g('b'),s=g('s'),m=g('m'),l=g('l'),gain=s-b,"
            "tax=0,n=T.ok;if(m>24){n=T.ex}else if(gain<=0){n=T.ng}else{tax=Math.max(0,gain-l)*0.12;if(tax<=2){tax=0;"
            "n=T.sm}}document.getElementById(k+'g').textContent=crF(L,gain);document.getElementById(k+'t').textContent="
            "crF(L,tax);document.getElementById(k+'k').textContent=crF(L,s-tax);document.getElementById(k+'n')."
            "textContent=n}['b','s','m','l'].forEach(function(x){document.getElementById(k+x).addEventListener('input',u)"
            "});u()})()</script>")


def company(lang="en"):
    t, k = T[lang], "co" + lang
    rows = (("p2", t["p2"]), ("p1", t["p1"]), ("d", t["d"]))
    bars = "".join(f"<div><span>{lab}</span><p><i id={k}{key} class={'g' if key == 'd' else ''}></i>"
                   f"<em id={k}{key}v></em></p></div>" for key, lab in rows)
    return (f"<figure class=calc id={k}><figcaption><b>{t['c_h']}</b><span>{t['c_sub']}</span></figcaption>"
            f"<div class=ci>{_in(k + 'a', t['cgain'], 10000)}<label>{t['rev']}<select id={k}r>"
            f"<option value=0.10>{t['r1']}</option><option value=0.18>{t['r2']}</option></select></label></div>"
            f"<div class=cb>{bars}</div></figure>" + _FMT +
            f"<script>(function(){{var k='{k}',L='{lang}';function u(){{var a=Math.max(0,parseFloat("
            "document.getElementById(k+'a').value)||0),r=parseFloat(document.getElementById(k+'r').value),"
            "v={p2:0,p1:a*0.12,d:a*r+(a-a*r)*0.12},mx=Math.max(v.d,1);for(var x in v){document.getElementById(k+x)"
            ".style.width=(100*v[x]/mx*0.8)+'%';document.getElementById(k+x+'v').textContent=crF(L,v[x])}}"
            "['a','r'].forEach(function(x){document.getElementById(k+x).addEventListener('input',u)});u()})()</script>")


def slippage(lang="en"):
    t, k = T[lang], "sl" + lang
    return (f"<figure class=calc id={k}><figcaption><b>{t['s_h']}</b><span>{t['s_sub']}</span></figcaption>"
            f"<div class=ci>{_in(k + 'x', t['size'], 1000)}{_in(k + 'r', t['liq'], 50000)}</div><div class=co>"
            f"<div class=hi><b id={k}p>3.8%</b><span>{t['lose']}</span></div><div><b id={k}c>$38</b>"
            f"<span>{t['cost']}</span></div></div><p class=cn id={k}n></p></figure>" + _FMT +
            f"<script>(function(){{var k='{k}',L='{lang}',ok={_js(t['s_ok'])},wn={_js(t['s_warn'])};function g(x){{"
            "return Math.max(0,parseFloat(document.getElementById(k+x).value)||0)}function u(){var x=g('x'),R=g('r')/2,"
            "p=R+x>0?x/(R+x):0;document.getElementById(k+'p').textContent=(p*100).toLocaleString(L=='hr'?'hr-HR':'en-IE',"
            "{maximumFractionDigits:1})+'%';document.getElementById(k+'c').textContent=crF(L,x*p,'USD');"
            "document.getElementById(k+'n').textContent=(R>0&&x/(2*R)>0.02)?wn:ok}['x','r'].forEach(function(z){"
            "document.getElementById(k+z).addEventListener('input',u)});u()})()</script>")


def _js(s):
    import json
    return json.dumps(s, ensure_ascii=False).replace("</", "<\\/")
