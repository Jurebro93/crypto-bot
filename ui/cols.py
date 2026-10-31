"""Column chooser for every dashboard table.

Each table with a header gets a small "⚙ Stupci" button: show/hide columns and change their order (drag or ↑/↓).
The choice is stored in the browser (localStorage) per page + table, keyed by column label, so it survives reloads
and new columns simply appear. Tables whose rows are re-rendered by JS (e.g. live demo positions) are re-applied
automatically through a MutationObserver. Nothing is stored on the server.
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
"""

JS = r"""
(()=>{
const P='cols:'+location.pathname+':';
const lab=th=>{const c=th.cloneNode(true);c.querySelectorAll('.tip').forEach(x=>x.remove());return c.textContent.trim()||'#'};
const load=k=>{try{return JSON.parse(localStorage.getItem(P+k))||{}}catch(e){return {}}};
const save=(k,s)=>{try{(s.order||s.hide&&s.hide.length)?localStorage.setItem(P+k,JSON.stringify(s)):localStorage.removeItem(P+k)}catch(e){}};
const tables=[];let n=0;
function init(t){
 if(t._cols)return;const hr=t.tHead&&t.tHead.rows[t.tHead.rows.length-1];
 if(!hr||hr.cells.length<3||t.tHead.rows.length>1||[...hr.cells].some(c=>c.colSpan>1))return;
 const labels=[...hr.cells].map(lab);
 t._cols={k:t.id||('t'+(n++)),labels,v:0};tables.push(t);
 [...hr.cells].forEach((c,i)=>c.dataset.c=i);
 const w=t.closest('.tw')||t,bar=document.createElement('div');bar.className='colbar';
 bar.innerHTML='<span class=hid></span><button type=button title="Odaberi koje stupce vidiš i njihov redoslijed">⚙ Stupci</button>';
 w.parentNode.insertBefore(bar,w);t._cols.bar=bar;
 bar.querySelector('button').onclick=e=>{e.stopPropagation();panel(t)};
 apply(t,true)}
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
 let first=true;pos.forEach(i=>{const c=by[i];r.appendChild(c);const h=hid.has(i);c.classList.toggle('ch',h);
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
