"""Column chooser for every dashboard table.

Each table with a header gets a small "⚙ Stupci" button: show/hide columns and change their order (drag or ↑/↓).
The choice is stored in the browser (localStorage) per page + table, keyed by column label, so it survives reloads
and new columns simply appear. Tables whose rows are re-rendered by JS (e.g. live demo positions) are re-applied
automatically through a MutationObserver. Nothing is stored on the server.

On phones (< 700 px, or by choice < 900 px) every table switches to cards: one card per row, first visible column
as the title, the other visible columns as label/value pairs, with a "Sortiraj" select instead of the header.
"""

CSS = """
.tw{max-height:78vh;overflow:auto;overscroll-behavior-x:contain}
.tw th,.tw td{padding:5px 8px}.tw td{font-size:13px}
.tw thead th{position:sticky;top:0;z-index:2;white-space:normal;vertical-align:bottom;min-width:44px}
.tw td.wrap{min-width:200px;max-width:420px}
.tw .stk{position:sticky;left:0;z-index:1;background:var(--card);box-shadow:1px 0 0 var(--line)}
.tw thead th.stk{z-index:3}
tr:hover td{background:color-mix(in srgb,var(--acc) 5%,var(--card))}
.tw .ch{display:none}
.colbar{display:flex;justify-content:flex-end;gap:8px;align-items:center;margin:2px 0 4px;position:relative;font-size:12px}
.colbar button,.colpan button{background:var(--card);color:var(--mut);border:1px solid var(--line);border-radius:6px;padding:2px 8px;font:12px system-ui,sans-serif;cursor:pointer}
.colbar button:hover,.colpan button:hover{color:var(--fg);border-color:var(--acc)}
.colbar .hid{color:var(--warn)}
.colpan{position:absolute;right:0;top:100%;z-index:20;background:var(--card);border:1px solid var(--line);border-radius:8px;
 box-shadow:0 6px 20px rgba(0,0,0,.2);padding:8px;width:300px;max-height:70vh;overflow:auto;font-size:13px}
.colpan .h{display:flex;gap:6px;flex-wrap:wrap;margin-bottom:6px}.colpan .mut{font-size:12px;margin:0 0 6px}
.colpan li{list-style:none;display:flex;align-items:center;gap:6px;padding:3px 4px;border-radius:5px;cursor:grab}
.colpan li:hover{background:color-mix(in srgb,var(--acc) 7%,var(--card))}.colpan li.drag{opacity:.4}
.colpan li label{flex:1;cursor:pointer;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.colpan li button{padding:0 6px}.colpan ul{margin:0;padding:0}
.colbar select{font:12px system-ui,sans-serif;padding:2px 4px}
.colbar .cv{display:none}@media(max-width:900px){.colbar .cv{display:inline-block}}
table.cards,table.cards tbody{display:block;width:100%}table.cards thead{display:none}
table.cards tr{display:grid;grid-template-columns:1fr 1fr;column-gap:18px;padding:8px 12px;border-bottom:1px solid var(--line)}
table.cards td.stk,table.cards td.wrap,table.cards td[colspan]{grid-column:1/-1}table.cards td:empty{display:none}
table.cards td{display:block;border:0;padding:3px 0;white-space:normal;text-align:right;min-width:0;max-width:none;font-size:14px;overflow-wrap:anywhere}
table.cards td::after{content:'';display:block;clear:both}
table.cards td::before{content:attr(data-l);float:left;color:var(--mut);font-size:12px;text-align:left;max-width:45%;padding-right:10px;line-height:20px}
table.cards td.wrap{display:block;text-align:left}table.cards td.wrap::before{float:none;display:block;max-width:none}
table.cards td.stk{position:static;box-shadow:none;font-weight:600;font-size:15px;text-align:left;padding-bottom:4px}
table.cards td.stk::before{display:none}table.cards td.ch{display:none}
table.cards tr:hover td{background:none}.tw:has(table.cards){max-height:none;overflow:visible}
@media(max-width:700px){header{padding:0 8px;flex-wrap:nowrap;overflow-x:auto;scrollbar-width:none}header b{margin-right:8px;white-space:nowrap}
header a{padding:10px 8px;white-space:nowrap}nav.sub{padding:0 8px;flex-wrap:nowrap;overflow-x:auto;scrollbar-width:none}nav.sub a{white-space:nowrap}
main{padding:10px}h1{font-size:18px}.intro{font-size:13px;padding:8px 10px}.grid{grid-template-columns:repeat(auto-fit,minmax(140px,1fr))}
.stat .v{font-size:18px}.flt input[data-f]{width:100%}.colpan{width:min(300px,calc(100vw - 20px))}dialog#ev .body{padding:0 10px 12px}}
"""

JS = r"""
(()=>{
const P='cols:'+location.pathname+':';
const lab=th=>{const c=th.cloneNode(true);c.querySelectorAll('.tip').forEach(x=>x.remove());return c.textContent.trim()||'#'};
const load=k=>{try{return JSON.parse(localStorage.getItem(P+k))||{}}catch(e){return {}}};
const save=(k,s)=>{try{(s.order||s.hide&&s.hide.length)?localStorage.setItem(P+k,JSON.stringify(s)):localStorage.removeItem(P+k)}catch(e){}};
const tables=[];let n=0;
const cardsOn=()=>{if(innerWidth>=900)return false;const v=localStorage.getItem('cols:view');return v?v==='cards':innerWidth<700};
function init(t){
 if(t._cols)return;const hr=t.tHead&&t.tHead.rows[t.tHead.rows.length-1];
 if(!hr||hr.cells.length<3||t.tHead.rows.length>1||[...hr.cells].some(c=>c.colSpan>1))return;
 const labels=[...hr.cells].map(lab);
 t._cols={k:t.id||('t'+(n++)),labels,v:0};tables.push(t);
 [...hr.cells].forEach((c,i)=>c.dataset.c=i);
 const w=t.closest('.tw')||t,bar=document.createElement('div');bar.className='colbar';
 bar.innerHTML='<span class=hid></span><select class=srt title="Sortiraj" hidden></select><button type=button class=cv></button><button type=button title="Odaberi koje stupce vidiš i njihov redoslijed">⚙ Stupci</button>';
 w.parentNode.insertBefore(bar,w);t._cols.bar=bar;
 bar.querySelector('button:last-child').onclick=e=>{e.stopPropagation();panel(t)};
 bar.querySelector('.cv').onclick=()=>{localStorage.setItem('cols:view',cardsOn()?'table':'cards');tables.forEach(view)};
 const sel=bar.querySelector('.srt');sel.innerHTML='<option value="">Sortiraj…</option>'+labels.map((l,i)=>'<option value='+i+'>'+l.replace(/</g,'&lt;')+'</option>').join('');
 sel.onchange=()=>{const th=hr.querySelector('th[data-c="'+sel.value+'"]');if(th&&th.onclick)th.click();sel.value=''};
 view(t);
 apply(t,true)}
function view(t){const on=cardsOn(),b=t._cols.bar;t.classList.toggle('cards',on);
 b.querySelector('.cv').textContent=on?'☰ Tablica':'▦ Kartice';b.querySelector('.srt').hidden=!(on&&t.classList.contains('s'))}
function state(t){const C=t._cols,s=load(C.k),idx=Object.fromEntries(C.labels.map((l,i)=>[l,i]));
 let ord=(s.order||[]).filter(l=>l in idx);C.labels.forEach((l,i)=>{if(!ord.includes(l)){
  // new column: put it after its left neighbour in the default order
  const prev=C.labels[i-1],p=ord.indexOf(prev);ord.splice(p<0?i:p+1,0,l)}});
 const hide=new Set((s.hide||[]).filter(l=>l in idx));if(hide.size>=C.labels.length)hide.clear();
 return {ord,hide,pos:ord.map(l=>idx[l]),s}}
function fixRow(r,C,pos,hid,ncol){
 const cells=[...r.cells];if(cells.length!==ncol||cells.some(c=>c.colSpan>1))return;
 if(!r._c){cells.forEach((c,i)=>c.dataset.c=i);r._c=1}
 const by=[];cells.forEach(c=>by[+c.dataset.c]=c);
 let first=true;pos.forEach(i=>{const c=by[i];r.appendChild(c);c.dataset.l=C.labels[i];const h=hid.has(i);c.classList.toggle('ch',h);
  c.classList.toggle('stk',!h&&first);if(!h)first=false});r._v=C.v}
function apply(t,full){const C=t._cols;if(full){C.v++;C.st=state(t)}const {pos,hide}=C.st;
 const hid=new Set([...hide].map(l=>C.labels.indexOf(l))),ncol=C.labels.length;
 for(const r of t.rows)if(full||r._v!==C.v)fixRow(r,C,pos,hid,ncol);
 const sp=C.bar.querySelector('.hid');sp.textContent=hide.size?('skriveno stupaca: '+hide.size):''}
function panel(t){
 document.querySelectorAll('.colpan').forEach(p=>p.remove());
 const C=t._cols,st=state(t),p=document.createElement('div');p.className='colpan';
 p.innerHTML='<p class=mut>Kvačica = stupac se prikazuje. Povuci red ili koristi ↑↓ za redoslijed. Prvi vidljivi stupac ostaje zaključan lijevo pri scrollanju. Pamti se u ovom pregledniku.</p>'+
  '<div class=h><button data-a=all>Prikaži sve</button><button data-a=reset>Vrati zadano</button><button data-a=x>Zatvori</button></div><ul></ul>';
 const ul=p.querySelector('ul');let ord=st.ord.slice(),hide=new Set(st.hide);
 const commit=()=>{const def=ord.every((l,i)=>l===C.labels[i]);save(C.k,{order:def?undefined:ord,hide:[...hide]});apply(t,true)};
 const draw=()=>{ul.innerHTML='';ord.forEach((l,i)=>{const li=document.createElement('li');li.draggable=true;li.dataset.i=i;
  li.innerHTML='<input type=checkbox><label></label><button data-m=-1 title="Pomakni gore">↑</button><button data-m=1 title="Pomakni dolje">↓</button>';
  const cb=li.querySelector('input');cb.checked=!hide.has(l);cb.id='cc'+i;li.querySelector('label').htmlFor='cc'+i;li.querySelector('label').textContent=l;
  cb.onchange=()=>{if(cb.checked)hide.delete(l);else{if(hide.size>=ord.length-1){cb.checked=true;return}hide.add(l)}commit()};
  li.querySelectorAll('button').forEach(b=>b.onclick=()=>{const j=i+ +b.dataset.m;if(j<0||j>=ord.length)return;[ord[i],ord[j]]=[ord[j],ord[i]];commit();draw()});
  li.ondragstart=e=>{li.classList.add('drag');e.dataTransfer.effectAllowed='move';e.dataTransfer.setData('text/plain',i)};
  li.ondragend=()=>li.classList.remove('drag');li.ondragover=e=>e.preventDefault();
  li.ondrop=e=>{e.preventDefault();const f=+e.dataTransfer.getData('text/plain');if(isNaN(f)||f===i)return;const [m]=ord.splice(f,1);ord.splice(i,0,m);commit();draw()};
  ul.appendChild(li)})};
 p.querySelector('.h').onclick=e=>{const a=e.target.dataset.a;if(!a)return;
  if(a==='x'){p.remove();return}hide.clear();if(a==='reset')ord=C.labels.slice();commit();draw()};
 p.onclick=e=>e.stopPropagation();draw();C.bar.appendChild(p)}
document.addEventListener('click',()=>document.querySelectorAll('.colpan').forEach(p=>p.remove()));
document.addEventListener('keydown',e=>{if(e.key==='Escape')document.querySelectorAll('.colpan').forEach(p=>p.remove())});
const scan=()=>{document.querySelectorAll('table').forEach(init);tables.forEach(t=>{if(t.isConnected)apply(t,false)})};
let q=0;new MutationObserver(()=>{if(!q){q=1;requestAnimationFrame(()=>{q=0;scan()})}}).observe(document.body,{childList:true,subtree:true});
scan();
})();
"""
