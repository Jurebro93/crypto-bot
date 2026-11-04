"""Long-page navigation, shared by the dashboard (ui/html.page) and the public site (ui/public._shell).

  * Section chips: a row of chips built in the browser from the page's own <h2> headings. It sits under the page
    title and sticks under the top bar while you scroll, so every section of a long page is one tap away; the
    section you are reading is highlighted. A new page gets it automatically as soon as it has 3+ visible <h2>.
    A heading can set its own short chip name with data-sec="…"; data-sec="" (or class nosec) leaves it out.
    The chip text is the heading's own text (not the ⓘ, filters or note inside it), cut at " · " or "(".
  * Long tables: a table with more than 25 body rows shows the first 25; "Vidi još 25" under it adds the next 25
    ("Prikaži sve" shows the rest). Sorting, the row filter and live updates re-apply it; a filter shows all matches.
    class nopage on the table (or a parent) turns it off.
  * Back to top: a round ↑ button bottom right, shown once you are more than about a screen down. On phones it
    sits above the bottom menu bar (dashboard) or the "Request access" bar (public site).

The two labels people read are rendered on the server in Croatian (aria-label / title), so the i18n layer
translates them for the English app; the public English pages pass their own English labels.
"""

CSS = """
.secnav{position:sticky;top:var(--sn-top,60px);z-index:25;display:flex;gap:6px;overflow-x:auto;scrollbar-width:none;
 margin:8px 0 14px;padding:8px 2px;background:color-mix(in srgb,var(--bg,#fff) 92%,transparent);
 -webkit-backdrop-filter:blur(10px);backdrop-filter:blur(10px);border-bottom:1px solid transparent;
 overscroll-behavior-x:contain;-webkit-overflow-scrolling:touch}
.secnav::-webkit-scrollbar{display:none}.secnav[hidden],.totop[hidden]{display:none}
.secnav.stuck{border-bottom-color:var(--line,#e5e7eb);box-shadow:0 6px 14px -12px rgba(0,0,0,.35)}
.secnav a{flex:none;white-space:nowrap;font-size:13px;line-height:1.2;padding:7px 12px;border-radius:999px;text-decoration:none;
 border:1px solid var(--line,#e5e7eb);background:var(--card,var(--bg,#fff));color:var(--fg,#111)}
.secnav a:hover{border-color:var(--acc,#4f46e5);color:var(--acc,#4f46e5)}
.secnav a.on{background:var(--acc,#4f46e5);border-color:var(--acc,#4f46e5);color:#fff;font-weight:600}
.totop{position:fixed;right:14px;bottom:calc(var(--tt-b,16px) + env(safe-area-inset-bottom,0px));z-index:40;width:46px;height:46px;
 border-radius:50%;border:1px solid var(--line,#e5e7eb);background:var(--card,var(--bg,#fff));color:var(--fg,#111);
 font-size:22px;line-height:1;cursor:pointer;box-shadow:0 8px 22px -8px rgba(0,0,0,.45);opacity:0;transform:translateY(12px);
 transition:opacity .2s,transform .2s;pointer-events:none;display:flex;align-items:center;justify-content:center}
.totop.show{opacity:1;transform:none;pointer-events:auto}.totop:hover{border-color:var(--acc,#4f46e5);color:var(--acc,#4f46e5)}
tr.pgh{display:none!important}
.pgbar{display:flex;align-items:center;flex-wrap:wrap;gap:8px;margin:8px 0 4px;font-size:13px;color:var(--mut,#667)}
.pgbar[hidden]{display:none}
.pgbar button{font:inherit;font-weight:600;padding:8px 16px;border-radius:999px;cursor:pointer;border:1px solid var(--acc,#4f46e5);
 background:var(--card,var(--bg,#fff));color:var(--acc,#4f46e5)}
.pgbar button.pgm{background:var(--acc,#4f46e5);color:#fff}.pgbar button:hover{filter:brightness(1.08)}
@media print{.secnav,.totop,.pgbar{display:none}tr.pgh{display:table-row!important}}
"""

JS = r"""
(()=>{
const main=document.querySelector('main');if(!main)return;
const nav=document.getElementById('secnav'),top=document.getElementById('totop');
const bar=()=>document.querySelector('header.top,body>nav.s');
const shown=e=>e&&e.getClientRects().length>0&&getComputedStyle(e).visibility!=='hidden';
function label(h){
  if(h.dataset.sec!==undefined)return h.dataset.sec.trim();
  let t='';for(const n of h.childNodes){if(n.nodeType===3)t+=n.textContent;
    else if(n.nodeType===1&&/^(B|STRONG|I|EM|U|MARK|BDI)$/.test(n.tagName))t+=n.textContent;
    else if(t.trim())break}
  t=(t.trim()||h.textContent.trim()).replace(/\s+/g,' ');
  t=t.split(' · ')[0].split(' (')[0].replace(/[:\s]+$/,'');
  return t.length>34?t.slice(0,32).trim()+'…':t}
let heads=[],links=[],sig='',offs=60,cur=-1;
function headerH(){const b=bar();return b?Math.round(b.getBoundingClientRect().height):0}
function build(){
  if(!nav)return;
  const hs=[...main.querySelectorAll('h2')].filter(h=>!h.classList.contains('nosec')&&!h.closest('dialog,.secnav,[hidden]')&&shown(h));
  const items=hs.map(h=>[h,label(h)]).filter(x=>x[1]);
  const tall=items.length>=3&&document.documentElement.scrollHeight>=innerHeight*2;
  const s=tall+'|'+items.map(x=>x[1]).join('|');if(s===sig)return;sig=s;cur=-1;
  if(!tall){nav.hidden=true;heads=[];links=[];return}
  nav.innerHTML='';heads=[];links=[];
  items.forEach(([h,t],i)=>{if(!h.id)h.id='s-'+(t.toLowerCase().normalize('NFD').replace(/[^a-z0-9]+/g,'-').replace(/^-|-$/g,'')||i);
    const a=document.createElement('a');a.href='#'+h.id;a.textContent=t;
    a.onclick=e=>{e.preventDefault();go(h)};nav.appendChild(a);heads.push(h);links.push(a)});
  /* place the chips right before the block that holds the first section, as a direct child of <main> */
  let a=heads[0];while(a.parentElement&&a.parentElement!==main)a=a.parentElement;
  if(a.parentElement===main&&nav.nextElementSibling!==a)main.insertBefore(nav,a);
  nav.hidden=false;place();spy()}
function go(h){
  /* a section inside a closed box: open it first, or the chip scrolls to nothing (Influenceri, 4.11.) */
  for(let d=h.closest('details');d;d=d.parentElement&&d.parentElement.closest('details'))d.open=true;
  const at=()=>h.getBoundingClientRect().top+scrollY-offs-(nav&&!nav.hidden?nav.offsetHeight:0)-6;
  scrollTo({top:Math.max(0,at()),behavior:'smooth'});try{history.replaceState(null,'','#'+h.id)}catch(e){}
  /* long tables above can change height while we scroll: land exactly on the heading once it settles */
  setTimeout(()=>{const y=Math.max(0,at());if(Math.abs(y-scrollY)>8)scrollTo({top:y,behavior:'auto'})},700)}
function place(){offs=headerH();if(nav)nav.style.setProperty('--sn-top',offs+'px');
  if(!top)return;let b=16;
  for(const el of document.querySelectorAll('.bbar,.mcta')){if(shown(el)&&getComputedStyle(el).position==='fixed'&&!el.classList.contains('h'))
    b=Math.max(b,innerHeight-el.getBoundingClientRect().top+12)}
  top.style.setProperty('--tt-b',b+'px')}
function spy(){
  if(top){const on=scrollY>innerHeight*1.1;top.hidden=false;top.classList.toggle('show',on)}
  if(!heads.length||nav.hidden)return;
  nav.classList.toggle('stuck',nav.getBoundingClientRect().top<=offs+1);
  const line=offs+nav.offsetHeight+24;let i=-1;
  heads.forEach((h,k)=>{if(h.getBoundingClientRect().top<=line)i=k});
  if(innerHeight+scrollY>=document.documentElement.scrollHeight-4)i=heads.length-1;
  if(i===cur)return;cur=i;
  links.forEach((l,k)=>l.classList.toggle('on',k===i));
  const l=links[i];if(l)nav.scrollTo({left:l.offsetLeft-nav.clientWidth/2+l.offsetWidth/2,behavior:'smooth'})}
let raf=0;addEventListener('scroll',()=>{if(!raf)raf=requestAnimationFrame(()=>{raf=0;spy()})},{passive:true});
let t=0;const later=()=>{clearTimeout(t);t=setTimeout(()=>{build();place();spy()},250)};
addEventListener('resize',later);document.addEventListener('click',later);document.addEventListener('toggle',later,true);
if(top)top.onclick=()=>scrollTo({top:0,behavior:'smooth'});
/* long tables: show PG rows, then "Vidi još 25" adds the next PG; sorting/filters/live updates re-apply it */
const PG=25,pgL=(()=>{const d=document.getElementById('pglab'),s=d?[...d.children].map(x=>x.textContent.trim()):[];
  return {more:s[0]||'Vidi još',all:s[1]||'Prikaži sve',shown:s[2]||'prikazano',of:s[3]||'od'}})();
function pg(t){
  if(t.closest('.nopage'))return;const b=t.tBodies[0];if(!b)return;const rs=[...b.rows];
  let st=t._pg;if(!st){if(rs.length<=PG)return;st=t._pg={n:PG};
    const bar=st.bar=document.createElement('div');bar.className='pgbar';
    bar.innerHTML='<button type=button class=pgm></button><button type=button class=pga></button><span class=pgc></span>';
    bar.querySelector('.pgm').onclick=()=>{st.n+=PG;pg(t)};bar.querySelector('.pga').onclick=()=>{st.n=1e9;pg(t)};
    const w=t.closest('.tw')||t;w.parentNode.insertBefore(bar,w.nextSibling)}
  const f=t.id&&[...document.querySelectorAll('input[data-f="'+t.id+'"]')].some(i=>i.value.trim());
  let k=0;for(const r of rs){if(r.style.display==='none'){r.classList.remove('pgh');continue}k++;r.classList.toggle('pgh',!f&&k>st.n)}
  const shownN=f?k:Math.min(k,st.n);st.bar.hidden=f||k<=st.n;
  st.bar.querySelector('.pgm').textContent=pgL.more+' '+Math.min(PG,k-shownN);
  st.bar.querySelector('.pga').textContent=pgL.all+' ('+k+')';st.bar.querySelector('.pga').hidden=k-shownN<=PG;
  st.bar.querySelector('.pgc').textContent=pgL.shown+' '+shownN+' '+pgL.of+' '+k}
const pgAll=()=>{document.querySelectorAll('table').forEach(pg);
  const h=location.hash&&document.getElementById(decodeURIComponent(location.hash.slice(1)));const r=h&&h.closest('tr.pgh');
  if(r){const t=r.closest('table');if(t._pg){t._pg.n=1e9;pg(t)}}};
let pq=0;const pgSoon=()=>{if(!pq){pq=1;requestAnimationFrame(()=>{pq=0;pgAll()})}};
new MutationObserver(ms=>{if(ms.some(m=>m.target.closest&&!m.target.closest('.pgbar,.secnav')))pgSoon()}).observe(document.body,{childList:true,subtree:true});
document.addEventListener('input',e=>{if(e.target.matches&&e.target.matches('input[data-f]'))setTimeout(pgAll,0)});
pgAll();
build();place();spy();addEventListener('load',later);
})();
"""


PG_LABELS = {"hr": ("Vidi još", "Prikaži sve", "prikazano", "od"), "en": ("See more:", "Show all", "showing", "of")}


def markup(nav_label="Sekcije stranice", top_label="Povratak na vrh", lang="hr"):
    """Empty chip bar (filled by JS) + the ↑ button + the words of the table "Vidi još" bar (hidden; the dashboard's
    i18n layer translates them, public English pages pass lang="en"). Put it at the top of <main>."""
    pgl = "".join(f"<span>{w}</span>" for w in PG_LABELS.get(lang, PG_LABELS["hr"]))
    return (f'<nav class=secnav id=secnav aria-label="{nav_label}" hidden></nav>'
            f'<button type=button class=totop id=totop aria-label="{top_label}" title="{top_label}" hidden>↑</button>'
            f'<div id=pglab hidden>{pgl}</div>')
