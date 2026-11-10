"""The Autopilot chart: the wallet's value and its profit and loss over time, as one inline SVG without a library.

10.11. (Jure): "na vrhu autopilota dodaj graf dužine cijelog ekrana: vrijednost walleta, uplate označene na grafu,
pokraj 1 SOL živa pretvorba u dolare i eure, profit and loss kroz vrijeme u istom grafu".

    chart_html(series, summary, deposits=(), ident="ap", compact=False, lang="hr") -> str

- `series`, `summary`, `deposits` are what trade/equity.py returns (audit/2026-11-10/dizajn.md, section 1): points oldest
  first with ts, value_sol, pnl_sol, sol_usd, usd_eur, src; the summary of the newest point; uplate i isplate {ts, sol}.
- Two panels on ONE time axis, never two scales on one plot: the value as a line on top, the PnL under it as an area
  that is green above zero and red below. The sign is carried by the side of the zero line and by the signed number
  in the read-out, the colour only repeats it (the app's own green and red sit too close for red-green colour
  blindness: checked with the palette validator, so the red here is one step darker, #b91c1c, and the dark set is
  #6f77ea / #1db071 / #cb4644; both sets pass the checks on their surfaces).
- Deposits and withdrawals are dashed vertical markers with the amount; the part rebuilt from orders (src='recon') is
  dashed and named in the legend and in the read-out.
- The points are embedded once as JSON and the browser redraws for the range (24 h / 7 d / 30 d / sve) and the unit
  (SOL / $ / €). Dollars and euros are the SOL amount at the rate of that same moment.
- Colours come from the page's CSS variables (ui/html.py: --fg, --mut, --line, --card, --acc, --good), so the chart
  follows the page. On a dark page give any ancestor data-theme=dark (the page's own variables are kept, only the
  three data colours change) or the class apc-dark (a complete dark set, for a page without those variables).
- The public Autopilot page calls this with the same arguments: nothing here is owner-only, nothing links anywhere,
  nothing but the numbers it was given leaves this module.
"""
import json
import time

from ui.html import esc

MAX_POINTS = 1500      # trade.equity.series() sends at most 600; a longer list from another caller is thinned to this
RECON = "recon"

LABELS = {
    "hr": {"loc": "hr", "ranges": (("1", "24 h"), ("7", "7 d"), ("30", "30 d"), ("0", "sve")),
           "range_aria": "Razdoblje", "unit_aria": "Jedinica",
           "val": "Vrijednost walleta", "pnl": "PnL: dobit iznad nule, gubitak ispod",
           "res": "Rezultat u razdoblju:", "none": "U ovom razdoblju nema snimki.",
           "one": "Prva snimka je spremljena. Linija se pojavi sa sljedećom, za najviše 5 minuta.",
           "empty": "Graf kreće s prvom snimkom, za najviše 5 minuta.",
           "dep": "uplata", "wd": "isplata", "rc": "rekonstruirano iz naloga",
           "leg_dep": "uplata ili isplata", "leg_rc": "rekonstruirano iz naloga",
           "table": "Tablica", "th": ("Vrijeme", "Vrijednost", "PnL"),
           "aria": "Graf vrijednosti walleta i PnL-a kroz vrijeme.", "now": "Vrijednost", "pnl_word": "PnL"},
    "en": {"loc": "en-GB", "ranges": (("1", "24 h"), ("7", "7 d"), ("30", "30 d"), ("0", "all")),
           "range_aria": "Range", "unit_aria": "Unit",
           "val": "Wallet value", "pnl": "PnL: profit above zero, loss below",
           "res": "Result in this range:", "none": "No snapshots in this range.",
           "one": "The first snapshot is saved. The line appears with the next one, within 5 minutes.",
           "empty": "The chart starts with the first snapshot, within 5 minutes.",
           "dep": "deposit", "wd": "withdrawal", "rc": "rebuilt from orders",
           "leg_dep": "deposit or withdrawal", "leg_rc": "rebuilt from orders",
           "table": "Table", "th": ("Time", "Value", "PnL"),
           "aria": "Chart of the wallet value and PnL over time.", "now": "Value", "pnl_word": "PnL"},
}

CSS = """<style>
.apc{--apc-ink:var(--fg,#0b1220);--apc-mut:var(--mut,#5b6474);--apc-grid:var(--line,#e8ebf2);--apc-axis:var(--line2,#cfd5e1);
--apc-surface:var(--card,#fff);--apc-soft:var(--soft,#f6f7fb);--apc-val:var(--acc,#4f46e5);--apc-up:var(--good,#16a34a);--apc-dn:#b91c1c;
margin:0;color:var(--apc-ink);font-variant-numeric:tabular-nums}
[data-theme=dark] .apc,.apc-dark .apc,.apc.apc-dark{--apc-val:#6f77ea;--apc-up:#1db071;--apc-dn:#cb4644}
.apc-dark .apc,.apc.apc-dark{--apc-ink:#f0efec;--apc-mut:#a3a29b;--apc-grid:#2c2c2a;--apc-axis:#45453f;--apc-surface:#1a1a19;--apc-soft:#262624}
.apc-top{display:flex;justify-content:space-between;gap:8px;flex-wrap:wrap;align-items:center}
.apc-seg{display:inline-flex;background:var(--apc-soft);border-radius:10px;padding:3px;gap:2px}
.apc-seg button{border:0;background:none;box-shadow:none;color:var(--apc-mut);font:inherit;font-size:13px;font-weight:500;padding:0 11px;
min-height:32px;border-radius:8px;cursor:pointer;transform:none}
.apc-seg button:hover{background:none;color:var(--apc-ink);box-shadow:none}
.apc-seg button.on{background:var(--apc-surface);color:var(--apc-ink);box-shadow:0 1px 2px rgba(11,18,32,.14)}
.apc-read{min-height:20px;margin:10px 0 0;font-size:13px;color:var(--apc-mut)}
.apc-plot{position:relative}
.apc svg{display:block;width:100%;touch-action:pan-y;-webkit-tap-highlight-color:transparent;user-select:none;-webkit-user-select:none}
.apc svg:focus{outline:none}.apc svg:focus-visible{outline:2px solid var(--apc-val);outline-offset:2px;border-radius:6px}
.apc-ax line{stroke:var(--apc-grid);stroke-width:1}.apc-ax line.apc-zero{stroke:var(--apc-axis)}
.apc-ax text,.apc-cap,.apc-dl{font-size:11px;fill:var(--apc-mut)}
.apc-cap{font-weight:600;paint-order:stroke;stroke:var(--apc-surface);stroke-width:4px;stroke-linejoin:round}
.apc-dl{paint-order:stroke;stroke:var(--apc-surface);stroke-width:3px;stroke-linejoin:round}
.apc-va{fill:var(--apc-val);opacity:.08}
.apc-vl{fill:none;stroke:var(--apc-val);stroke-width:2;stroke-linejoin:round;stroke-linecap:round}
g.apc-up{color:var(--apc-up)}g.apc-dn{color:var(--apc-dn)}
.apc-qa{fill:currentColor;opacity:.14}
.apc-ql{fill:none;stroke:currentColor;stroke-width:2;stroke-linejoin:round;stroke-linecap:round}
.apc-rc{stroke-dasharray:5 5;opacity:.85}
.apc-dep{stroke:var(--apc-mut);stroke-width:1;stroke-dasharray:3 3}
.apc-dot{fill:var(--apc-val);stroke:var(--apc-surface);stroke-width:2}
circle.apc-up{fill:var(--apc-up)}circle.apc-dn{fill:var(--apc-dn)}
.apc-ch line{stroke:var(--apc-mut);stroke-width:1}
.apc-empty{margin:0;padding:34px 0;color:var(--apc-mut);font-size:13px}
.apc-leg{display:flex;gap:6px 16px;flex-wrap:wrap;align-items:center;font-size:13px;color:var(--apc-mut);margin-top:4px;min-height:28px}
.apc-leg i{display:inline-block;width:18px;height:0;border-top:2px dashed var(--apc-mut);vertical-align:middle;margin-right:6px}
.apc-leg i.rc{border-top-color:var(--apc-val)}
.apc-leg button{margin-left:auto;border:0;background:none;box-shadow:none;padding:4px 0;font:inherit;font-size:13px;font-weight:500;
color:var(--apc-mut);text-decoration:underline;text-underline-offset:3px;cursor:pointer;transform:none}
.apc-leg button:hover{background:none;color:var(--apc-ink);box-shadow:none}
.apc-tbl{max-height:260px;overflow:auto;margin-top:6px;border-top:1px solid var(--apc-grid)}
.apc-tbl table{width:100%;border-collapse:collapse;font-size:13px}
.apc-tbl th,.apc-tbl td{text-align:right;padding:6px 8px;border-bottom:1px solid var(--apc-grid);white-space:nowrap;cursor:default}
.apc-tbl th{color:var(--apc-mut);font-weight:600;background:var(--apc-surface)}
.apc-tbl th:first-child,.apc-tbl td:first-child{text-align:left;padding-left:0}
</style>"""

# One script for every chart on the page. It draws at DOMContentLoaded (or at once when the page is already loaded),
# so a page that swaps a fresh copy of the chart in (the Autopilot header, every 45 s) calls window.apcInit() again
# and the new copy is drawn with the range and the unit the viewer chose (kept in localStorage per chart id).
JS = r"""<script>(()=>{if(window.apcInit){window.apcInit();return}
const NS='http://www.w3.org/2000/svg',DAY=86400,UN={sol:' SOL',usd:' $',eur:' €'};
function S(n,a,p,t){const e=document.createElementNS(NS,n);for(const k in a)e.setAttribute(k,a[k]);if(t!=null)e.textContent=t;if(p)p.appendChild(e);return e}
function nice(lo,hi,n){const raw=(hi-lo)/n||1,m=Math.pow(10,Math.floor(Math.log10(raw))),st=[1,2,2.5,5,10].map(x=>x*m).find(x=>x>=raw*.999),o=[];
for(let v=Math.ceil(lo/st-1e-9)*st;v<=hi+st*1e-6;v+=st)o.push(Math.abs(v)<st*1e-6?0:v);return o}
function runs(a){const o=[];let l=null;a.forEach((p,j)=>{if(l&&l.rc===p[3]){l.a.push(p);return}
if(l&&!p[3])l.a.push(p);l={rc:p[3],a:l&&p[3]?[a[j-1],p]:[p]};o.push(l)});return o}
function init(f){f.dataset.on=1;
const D=JSON.parse(f.querySelector('script[type="application/json"]').textContent),L=D.L,svg=f.querySelector('svg'),
read=f.querySelector('.apc-read'),msg=f.querySelector('.apc-empty'),tbl=f.querySelector('.apc-tbl'),tb=f.querySelector('.apc-tb'),
key='apc:'+f.id,n=D.t.length,st={r:D.def,u:'sol'};
try{Object.assign(st,JSON.parse(localStorage.getItem(key)||'{}'))}catch(e){}
if(!D.u||!(st.u in UN))st.u='sol';
let P=[],G=null,cur=-1,w0=0;
const k=i=>st.u==='sol'?1:st.u==='usd'?D.u[i]:D.u[i]*D.e[i];
const fmt=(v,s)=>{const a=Math.abs(v),d=st.u==='sol'?(a>=100?1:a>=10?2:3):(a>=1000?0:a>=100?1:2);return(v<0?'−':s?'+':'')+a.toFixed(d)+UN[st.u]};
const tick=v=>{const s=+v.toPrecision(6);return(Math.abs(s)>=1000?s.toFixed(0):String(s)).replace('-','−')};
const when=(t,o)=>new Date(t*1000).toLocaleString(D.loc,o);
const near=ts=>{let lo=0,hi=n-1;while(lo<hi){const m=(lo+hi)>>1;D.t[m]<ts?lo=m+1:hi=m}return lo};
const path=(a,yi)=>a.map((p,j)=>(j?'L':'M')+p[0].toFixed(1)+' '+p[yi].toFixed(1)).join('');
function say(j){if(!P.length){read.textContent='';return}
if(j==null||j<0){const a=P[0],b=P[P.length-1];read.textContent=P.length<2?L.one:L.res+' '+fmt(D.p[b]*k(b)-D.p[a]*k(a),1);return}
const i=P[j],prev=i?D.t[i-1]:-1;let s=when(D.t[i],{weekday:'short',day:'numeric',month:'numeric',hour:'2-digit',minute:'2-digit'})+' · '+fmt(D.v[i]*k(i))+' · '+L.pw+' '+fmt(D.p[i]*k(i),1);
(D.d||[]).forEach(d=>{if(d[0]>prev&&d[0]<=D.t[i])s+=' · '+(d[1]<0?L.wd:L.dep)+' '+fmt(d[1]*k(i),1)});
if(D.r[i])s+=' · '+L.rc;read.textContent=s}
function point(j){cur=j;const ch=svg.querySelector('.apc-ch');if(!ch||!G)return;
if(j<0){ch.setAttribute('visibility','hidden');say();return}
const p=G[j],c=ch.children;ch.setAttribute('visibility','visible');c[0].setAttribute('x1',p[0]);c[0].setAttribute('x2',p[0]);
c[1].setAttribute('cx',p[0]);c[1].setAttribute('cy',p[1]);c[2].setAttribute('cx',p[0]);c[2].setAttribute('cy',p[2]);
c[2].setAttribute('class','apc-dot '+(D.p[P[j]]<0?'apc-dn':'apc-up'));say(j)}
function draw(){const W=Math.max(240,w0),c=f.classList.contains('apc-compact'),g=46,pt=36,hv=c?110:W>700?230:170,gap=30,hp=c?56:W>700?104:84,
H=pt+hv+gap+hp+24,pw=W-g,end=Math.max(D.now,D.t[n-1]),from=st.r?end-st.r*DAY:-1;
P=[];for(let i=0;i<n;i++)if(D.t[i]>=from)P.push(i);
svg.setAttribute('viewBox','0 0 '+W+' '+H);svg.setAttribute('height',H);svg.replaceChildren();cur=-1;G=null;
msg.hidden=P.length>0;svg.style.display=P.length?'':'none';if(!P.length){msg.textContent=L.none;say();return}
const t0=D.t[P[0]],t1=D.t[P[P.length-1]],x=t=>t1>t0?(t-t0)/(t1-t0)*pw:pw/2,V=P.map(i=>D.v[i]*k(i)),Q=P.map(i=>D.p[i]*k(i));
let vlo=Math.min(...V),vhi=Math.max(...V);const vp=(vhi-vlo)*.1||Math.abs(vhi)*.02||1;vlo-=vp;vhi+=vp;
let qlo=Math.min(0,...Q),qhi=Math.max(0,...Q);const qs=qhi-qlo||1;qlo-=qlo<0?qs*.12:qs*.18;qhi+=qhi>0?qs*.12:qs*.18;
const yv=v=>pt+hv-(v-vlo)/(vhi-vlo)*hv,y0=pt+hv+gap,yq=v=>y0+hp-(v-qlo)/(qhi-qlo)*hp,yz=yq(0),ax=S('g',{class:'apc-ax'},svg);
nice(vlo,vhi,3).forEach(v=>{const y=yv(v);S('line',{x1:0,x2:pw,y1:y,y2:y},ax);S('text',{x:pw+6,y:y+4},ax,tick(v))});
nice(qlo,qhi,3).forEach(v=>{if(!v)return;const y=yq(v);if(Math.abs(y-yz)<13)return;S('line',{x1:0,x2:pw,y1:y,y2:y},ax);S('text',{x:pw+6,y:y+4},ax,tick(v))});
S('line',{x1:0,x2:pw,y1:yz,y2:yz,class:'apc-zero'},ax);S('text',{x:pw+6,y:yz+4},ax,'0');
const mx=Math.max(2,Math.min(9,Math.floor(pw/70))),sx=[1,2,3,6,12,24,48,72,96,120,168,336,720,2160].map(h=>h*3600).find(s=>(t1-t0)/s<=mx)||8760*3600,
d0=new Date(t0*1000),hm={hour:'2-digit',minute:'2-digit'},dm={day:'numeric',month:'numeric'};d0.setHours(0,0,0,0);let nt=0;
const xl=(t,o)=>{const X=x(t);S('text',{x:X,y:H-7,'text-anchor':X<18?'start':X>pw-18?'end':'middle'},ax,when(t,o));nt++};
if(t1>t0)for(let t=d0.getTime()/1000;t<=t1;t+=sx){if(t<t0)continue;const dt=new Date(t*1000);xl(t,sx<DAY&&(dt.getHours()||dt.getMinutes())?hm:dm)}
if(!nt){xl(t0,hm);if(t1>t0)xl(t1,hm)}
let lx=-1e9;(D.d||[]).forEach(d=>{if(d[0]<t0||d[0]>t1)return;const X=x(d[0]),s=fmt(d[1]*k(Math.min(n-1,near(d[0]))),1).replace(/(\.\d*?)0+(?= )/,'$1').replace(/\.(?= )/,''),w=s.length*6.3,
a=X<w/2+2?'start':X>pw-w/2-2?'end':'middle',l=a==='start'?X:a==='end'?X-w:X-w/2;
S('line',{x1:X,x2:X,y1:16,y2:y0+hp,class:'apc-dep'},svg);
if(l>lx+8){S('text',{x:a==='start'?X+2:a==='end'?X-2:X,y:11,'text-anchor':a,class:'apc-dl'},svg,s);lx=l+w}});
const pts=P.map((i,j)=>[x(D.t[i]),yv(V[j]),yq(Q[j]),D.r[i]]),la=pts[pts.length-1],id=f.id+'-c';
if(pts.length>1){S('path',{d:path(pts,1)+'L'+la[0]+' '+(pt+hv)+'L'+pts[0][0]+' '+(pt+hv)+'Z',class:'apc-va'},svg);
const df=S('defs',{},svg),qa=path(pts,2)+'L'+la[0]+' '+yz+'L'+pts[0][0]+' '+yz+'Z',rs=runs(pts);
S('rect',{x:-2,y:y0-4,width:pw+4,height:yz-y0+4},S('clipPath',{id:id+'u'},df));S('rect',{x:-2,y:yz,width:pw+4,height:y0+hp-yz+4},S('clipPath',{id:id+'d'},df));
[['u','apc-up'],['d','apc-dn']].forEach(q=>{const gq=S('g',{'clip-path':'url(#'+id+q[0]+')',class:q[1]},svg);S('path',{d:qa,class:'apc-qa'},gq);
rs.forEach(r=>S('path',{d:path(r.a,2),class:'apc-ql'+(r.rc?' apc-rc':'')},gq))});
rs.forEach(r=>S('path',{d:path(r.a,1),class:'apc-vl'+(r.rc?' apc-rc':'')},svg))}
S('text',{x:0,y:pt-8,class:'apc-cap'},svg,L.val);S('text',{x:0,y:y0-8,class:'apc-cap'},svg,L.pnl);
S('circle',{cx:la[0],cy:la[1],r:4,class:'apc-dot'},svg);
const ch=S('g',{class:'apc-ch',visibility:'hidden'},svg);S('line',{y1:pt,y2:y0+hp},ch);S('circle',{r:4,class:'apc-dot'},ch);S('circle',{r:4,class:'apc-dot'},ch);
S('rect',{x:0,y:0,width:W,height:H,fill:'none','pointer-events':'all'},svg);G=pts;say()}
function at(e){if(!G)return;const X=e.clientX-svg.getBoundingClientRect().left;let lo=0,hi=G.length-1;
while(hi-lo>1){const m=(lo+hi)>>1;G[m][0]<X?lo=m:hi=m}point(X-G[lo][0]<G[hi][0]-X?lo:hi)}
function table(){if(!tbl||tbl.hidden)return;const step=Math.ceil(P.length/24)||1,o={day:'numeric',month:'numeric',hour:'2-digit',minute:'2-digit'};
const t=document.createElement('table'),row=(c,h)=>{const r=t.insertRow();c.forEach(x=>{const e=document.createElement(h?'th':'td');e.textContent=x;r.appendChild(e)})};
row(L.th,1);for(let j=P.length-1;j>=0;j-=step){const i=P[j];row([when(D.t[i],o),fmt(D.v[i]*k(i)),fmt(D.p[i]*k(i),1)])}tbl.replaceChildren(t)}
function sync(){f.querySelectorAll('.apc-seg button').forEach(b=>{const on=String(st[b.parentNode.dataset.k])===b.dataset.v;b.classList.toggle('on',on);b.setAttribute('aria-pressed',on)})}
f.querySelectorAll('.apc-seg button').forEach(b=>b.addEventListener('click',()=>{const q=b.parentNode.dataset.k;st[q]=q==='r'?+b.dataset.v:b.dataset.v;
try{localStorage.setItem(key,JSON.stringify(st))}catch(e){}sync();draw();table()}));
if(tb)tb.addEventListener('click',()=>{tbl.hidden=!tbl.hidden;tb.setAttribute('aria-expanded',!tbl.hidden);table()});
svg.addEventListener('pointermove',at);svg.addEventListener('pointerdown',at);
svg.addEventListener('pointerleave',()=>point(-1));svg.addEventListener('pointercancel',()=>point(-1));svg.addEventListener('blur',()=>point(-1));
svg.addEventListener('keydown',e=>{const d=e.key==='ArrowRight'?1:e.key==='ArrowLeft'?-1:0;if(e.key==='Escape')point(-1);if(!d||!G)return;e.preventDefault();
point(Math.max(0,Math.min(G.length-1,(cur<0?G.length-1:cur)+d)))});
const go=()=>{const w=Math.round(f.getBoundingClientRect().width);if(w&&w!==w0){w0=w;draw();table()}};
sync();go();if(window.ResizeObserver)new ResizeObserver(go).observe(f);else addEventListener('resize',go)}
window.apcInit=()=>document.querySelectorAll('figure.apc[data-n]:not([data-on])').forEach(f=>{try{init(f)}catch(e){console.error('apchart',e)}});
if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',window.apcInit);else window.apcInit()})()</script>"""


def _num(x):
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return v if v == v and abs(v) != float("inf") else None   # NaN and infinity are "no number" too


def _filled(vals):
    """Rates with the gaps closed: a missing one takes the last known before it, the leading ones the first known.
    None when the whole list is empty (then the chart offers SOL only)."""
    known = [v for v in vals if v]
    if not known:
        return None
    out, last = [], known[0]
    for v in vals:
        last = v or last
        out.append(last)
    return out


def _thin(rows, limit=MAX_POINTS):
    """At most `limit` points, evenly, always with the first and the newest; points of a deposit are kept."""
    if len(rows) <= limit:
        return rows
    step = len(rows) / float(limit - 1)
    keep = {int(i * step) for i in range(limit - 1)} | {len(rows) - 1}
    return [r for i, r in enumerate(rows) if i in keep or r.get("flow_sol")]


def pack(series, deposits=()):
    """The embedded data: {t, v, p, r, u, e, d} as plain lists (ts, value in SOL, PnL in SOL, 1 for a rebuilt point,
    USD per SOL, EUR per USD, [[ts, sol], ...] of deposits). Rows without a time or a value are left out, the rest is
    sorted by time. u and e are None when no rate is known (the unit switch is then not shown)."""
    rows = []
    for s in series or ():
        ts, val = _num(s.get("ts")), _num(s.get("value_sol"))
        if ts is None or val is None:
            continue
        rows.append({"ts": int(ts), "v": val, "p": _num(s.get("pnl_sol")) or 0.0, "u": _num(s.get("sol_usd")),
                     "e": _num(s.get("usd_eur")), "r": 1 if s.get("src") == RECON else 0, "flow_sol": _num(s.get("flow_sol"))})
    rows.sort(key=lambda r: r["ts"])
    rows = _thin(rows)
    u, e = _filled([r["u"] for r in rows]), _filled([r["e"] for r in rows])
    deps = sorted([int(d["ts"]), round(float(d["sol"]), 4)] for d in deposits or ()
                  if _num(d.get("ts")) is not None and _num(d.get("sol")))
    return {"t": [r["ts"] for r in rows], "v": [round(r["v"], 5) for r in rows], "p": [round(r["p"], 5) for r in rows],
            "r": [r["r"] for r in rows], "u": [round(x, 3) for x in u] if u else None,
            "e": [round(x, 5) for x in e] if u and e else None, "d": deps}


def _figure(inner, ident, compact, extra=""):
    return f'<figure class="apc{" apc-compact" if compact else ""}" id="apc-{esc(ident)}"{extra}>{inner}</figure>'


def chart_html(series, summary, deposits=(), ident="ap", compact=False, lang="hr"):
    """The chart as HTML (style + figure + script). No points = one clear sentence instead of an empty frame.
    compact=True: lower panels, the range switch only (no unit switch, no table)."""
    L = LABELS.get(lang) or LABELS["hr"]
    try:
        data = pack(series, deposits)
    except Exception as e:  # noqa: BLE001 - a broken row must never take the page down
        print(f"apchart: podaci za graf nisu čitljivi: {type(e).__name__}: {e}", flush=True)
        data = {"t": []}
    n = len(data["t"])
    if not n:
        return CSS + _figure(f'<p class=apc-empty>{esc(L["empty"])}</p>', ident, compact)
    summary = summary or {}
    span = data["t"][-1] - data["t"][0]
    data.update(now=int(time.time()), loc=L["loc"], **{"def": 30 if span > 30 * 86400 else 0},
                L={"val": L["val"], "pnl": L["pnl"], "res": L["res"], "none": L["none"], "one": L["one"], "dep": L["dep"],
                   "wd": L["wd"], "rc": L["rc"], "th": list(L["th"]), "pw": L["pnl_word"]})
    if data.get("u") and not data.get("e"):
        data["e"] = [1.0] * n   # dollars known, euros not: the euro button is left out below
    seg = ('<div class=apc-seg data-k=r role=group aria-label="{}">'.format(esc(L["range_aria"]))
           + "".join(f'<button type=button data-v={v}>{esc(lab)}</button>' for v, lab in L["ranges"]) + "</div>")
    units = [("sol", "SOL")] + ([("usd", "$")] if data.get("u") else []) + (
        [("eur", "€")] if data.get("u") and _filled([_num(s.get("usd_eur")) for s in series or ()]) else [])
    if len(units) > 1 and not compact:
        seg += ('<div class=apc-seg data-k=u role=group aria-label="{}">'.format(esc(L["unit_aria"]))
                + "".join(f'<button type=button data-v={v}>{lab}</button>' for v, lab in units) + "</div>")
    val, pnl = _num(summary.get("value_sol")), _num(summary.get("pnl_sol"))
    if val is None:   # no summary: the newest point says the same
        val, pnl = data["v"][-1], data["p"][-1]
    now_txt = f'{L["now"]} {val:.3f} SOL · {L["pnl_word"]} {pnl or 0:+.3f} SOL'
    leg = ""
    if data["d"]:
        leg += f'<span><i></i>{esc(L["leg_dep"])}</span>'
    if any(data["r"]):
        leg += f'<span><i class=rc></i>{esc(L["leg_rc"])}</span>'
    tbl = "" if compact else f'<button type=button class=apc-tb aria-expanded=false>{esc(L["table"])}</button>'
    inner = (f'<div class=apc-top>{seg}</div><div class=apc-read aria-live=polite>{esc(now_txt)}</div>'
             f'<div class=apc-plot><svg role=img tabindex=0 aria-label="{esc(L["aria"] + " " + now_txt)}"></svg>'
             '<p class=apc-empty hidden></p></div>'
             + (f'<div class=apc-leg>{leg}{tbl}</div>' if leg or tbl else "")
             + ("" if compact else '<div class=apc-tbl hidden></div>')
             + '<script type="application/json">' + json.dumps(data, separators=(",", ":")).replace("<", "\\u003c") + "</script>")
    return CSS + _figure(inner, ident, compact, f" data-n={n}") + JS
