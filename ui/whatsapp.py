"""/whatsapp: the update for the traders' WhatsApp group, as a picture card + a short formatted message.

The picture is drawn in the browser (canvas, 1080x1350, WhatsApp's 4:5 feed size) from the same data as the text
(share/digest.collect), so the server needs no image library. Phone: "Pošalji u WhatsApp" opens the share sheet
with picture + text together. Computer: copy picture / copy text / download. Sending or copying marks the app
news as shared (POST /whatsapp/poslano), so the next update shows only what is new since.
"""
import json

from share import digest, send as gateway
from ui.html import ago, esc

CSS = """
.wa{display:grid;grid-template-columns:minmax(260px,420px) 1fr;gap:20px;align-items:start}
@media(max-width:800px){.wa{grid-template-columns:1fr}}
.wa img{width:100%;border-radius:14px;box-shadow:0 6px 24px rgba(0,0,0,.18);display:block}
.wabtns{display:flex;flex-wrap:wrap;gap:8px;margin:12px 0}
.wabtns button,.wabtns a{border:0;border-radius:10px;padding:11px 16px;font:600 15px system-ui,sans-serif;cursor:pointer;
 background:var(--card);color:var(--fg);border:1px solid var(--line);text-decoration:none;display:inline-flex;gap:6px;align-items:center}
.wabtns .go{background:#25d366;color:#fff;border-color:#25d366}.wabtns .go:hover{background:#1fb855}
.wabub{background:#d9fdd3;color:#111b21;border-radius:10px;padding:10px 12px;white-space:pre-wrap;font:15px/1.45 system-ui,sans-serif;
 box-shadow:0 1px 1px rgba(0,0,0,.12);max-width:520px}
@media (prefers-color-scheme:dark){.wabub{background:#005c4b;color:#e9edef}}
.wamsg{font-size:14px;min-height:20px;margin:4px 0}
"""

JS = r"""
(function(){
const D=JSON.parse(document.getElementById('wadata').textContent), TXT=document.getElementById('watext').value;
const W=1080,H=1350,c=document.createElement('canvas');c.width=W;c.height=H;const g=c.getContext('2d');
const F='system-ui,-apple-system,"Segoe UI",Roboto,sans-serif', E='"Apple Color Emoji","Segoe UI Emoji","Noto Color Emoji"';
const font=(w,s)=>g.font=`${w} ${s}px ${F},${E}`;
const pct=x=>x==null?'':(x>=0?'+':'−')+Math.abs(x*100).toFixed(Math.abs(x)<0.1?1:0)+'%';
const money=x=>(x>=0?'+':'−')+'$'+Math.abs(x).toLocaleString('en-US',{maximumFractionDigits:Math.abs(x)>=100?0:2});
function fit(t,max){if(g.measureText(t).width<=max)return t;while(t.length>1&&g.measureText(t+'…').width>max)t=t.slice(0,-1);return t+'…'}
function rr(x,y,w,h,r,fill){g.beginPath();g.roundRect?g.roundRect(x,y,w,h,r):g.rect(x,y,w,h);g.fillStyle=fill;g.fill()}
// background
let bg=g.createLinearGradient(0,0,W,H);bg.addColorStop(0,'#0b1220');bg.addColorStop(1,'#13243f');g.fillStyle=bg;g.fillRect(0,0,W,H);
let glow=g.createRadialGradient(W-120,80,10,W-120,80,520);glow.addColorStop(0,'rgba(37,211,102,.28)');glow.addColorStop(1,'rgba(37,211,102,0)');
g.fillStyle=glow;g.fillRect(0,0,W,H);
const X=64,CW=W-2*X;let y=70;
// header
g.textBaseline='top';font(800,58);g.fillStyle='#fff';g.fillText('📊 MemeSonar',X,y);
font(500,34);g.fillStyle='#9fb3c8';g.textAlign='right';g.fillText(D.date,W-X,y+14);g.textAlign='left';y+=96;
font(500,30);g.fillStyle='#9fb3c8';g.fillText('Dnevni pregled natjecanja i aplikacije',X,y);y+=66;
function section(title){font(700,30);g.fillStyle='#25d366';g.fillText(title,X,y);y+=50}
const L=D.league;
if(L&&L.players&&L.players.length){
  section('🏆 NATJECANJE');
  const top=L.players.slice(0,8),med={1:'🥇',2:'🥈',3:'🥉'};   // every player; rows shrink when there are more
  const rh=top.length<=3?84:top.length<=5?64:50,fs=top.length<=3?40:top.length<=5?34:28,gap=top.length<=3?14:8;
  for(const p of top){
    rr(X,y,CW,rh,16,p.rank===1?'rgba(255,200,60,.16)':'rgba(255,255,255,.07)');const ty=y+(rh-fs)/2;
    font(700,fs);g.fillStyle='#fff';g.fillText((med[p.rank]||p.rank+'.')+'  '+fit(p.user,420),X+24,ty);
    g.textAlign='right';g.fillStyle=p.ret>=0?'#3ddc84':'#ff6b6b';g.fillText(pct(p.ret),W-X-24,ty);
    font(500,fs-6);g.fillStyle='#d6e2f0';g.fillText('$'+Math.round(p.equity).toLocaleString('en-US'),W-X-200,ty+3);g.textAlign='left';
    y+=rh+gap}
  if(L.bot_ret!=null){y+=6;font(500,30);g.fillStyle='#9fb3c8';g.fillText('🤖 Bot od početka natjecanja: '+pct(L.bot_ret),X+8,y);y+=56}
  y+=10;
  const tr=[['🚀 Najbolji trade',L.best],['🩸 Najgori trade',L.worst]].filter(t=>t[1]);
  if(tr.length){
    const bw=(CW-20)/2;let x=X;
    for(const [lbl,t] of tr){
      const w=tr.length===1?CW:bw;rr(x,y,w,150,18,'rgba(255,255,255,.07)');
      font(500,27);g.fillStyle='#9fb3c8';g.fillText(lbl+' · 24 h',x+22,y+18);
      font(800,44);g.fillStyle=t.pnl>=0?'#3ddc84':'#ff6b6b';g.fillText(fit(t.symbol+' '+pct(t.ret),w-44),x+22,y+56);
      font(500,27);g.fillStyle='#d6e2f0';g.fillText(fit(t.user+' · '+money(t.pnl)+(t.open?' · otvoren':''),w-44),x+22,y+110);
      x+=w+20}
    y+=176}
}
function grid(title,items,max){   // two columns of short titles: the details are in the message under the picture
  if(!items.length||y+50+64>H-126)return;section(title);const cw=(CW-20)/2;let i=0;
  for(const it of items.slice(0,max)){const x=X+(i%2)*(cw+20);if(y+64>H-126)break;
    rr(x,y,cw,64,14,'rgba(255,255,255,.07)');font(700,30);g.fillStyle='#fff';g.fillText(fit(it[0],cw-36-(it[1]?g.measureText(it[1]).width:0)),x+18,y+16);
    if(it[1]){g.textAlign='right';font(500,26);g.fillStyle='#9fb3c8';g.fillText(it[1],x+cw-18,y+20);g.textAlign='left'}
    if(i%2===1||i===Math.min(items.length,max)-1)y+=78;i++}
  y+=14}
const TK=(D.tokens||[]).length;
grid('🆕 ŠTO JE NOVO',D.news.map(n=>['✓ '+(n.naslov||n.tekst),'']),TK?4:6);
const mc=m=>!m?'':m>=1e9?(m/1e9).toFixed(1).replace('.',',')+' mlrd $':Math.round(m/1e6)+' M$';
grid('🌱 JAKI TOKENI',(D.tokens||[]).map(t=>[(t.new?'✨ ':'')+t.symbol,mc(t.mcap)]),2);
// footer
rr(0,H-120,W,120,0,'rgba(0,0,0,.28)');font(600,30);g.fillStyle='#fff';g.fillText('👉 '+D.url.replace(/^https?:\/\//,''),X,H-92);
font(400,24);g.fillStyle='#8aa0b6';g.fillText('Demo novac, nije financijski savjet.',X,H-48);
const img=document.getElementById('waimg');img.src=c.toDataURL('image/png');
const blob=new Promise(r=>c.toBlob(r,'image/png'));
const msg=document.getElementById('wamsg');const say=(t,ok=true)=>{msg.textContent=t;msg.className='wamsg '+(ok?'pos':'neg')};
const mark=()=>fetch('/whatsapp/poslano',{method:'POST',credentials:'same-origin'}).catch(()=>{});
async function copyText(){try{await navigator.clipboard.writeText(TXT);return true}catch(e){
  const ta=document.getElementById('watext');ta.select();try{return document.execCommand('copy')}catch(_){return false}}}
const fname='memesonar-'+D.date.replace(/\.$/,'').replace(/\./g,'-')+'.png';
document.getElementById('wasend').onclick=async()=>{
  const file=new File([await blob],fname,{type:'image/png'});
  await copyText();
  if(navigator.canShare&&navigator.canShare({files:[file]})){
    try{await navigator.share({files:[file],text:TXT});mark();
        say('Poslano. Ako WhatsApp nije uzeo tekst uz sliku, tekst je već kopiran: samo ga zalijepi.')}
    catch(e){if(e.name!=='AbortError')say('Dijeljenje nije uspjelo: '+e.message,false)}
  }else{say('Ovaj preglednik ne može poslati sliku izravno. Tekst je kopiran; sliku kopiraj ili preuzmi gumbom ispod.',false)}};
document.getElementById('waimgcopy').onclick=async()=>{
  try{await navigator.clipboard.write([new ClipboardItem({'image/png':blob})]);mark();say('Slika je kopirana. Zalijepi je u grupu (Ctrl+V), pa kopiraj i tekst.')}
  catch(e){say('Preglednik ne da kopirati sliku. Preuzmi je gumbom „Preuzmi sliku“.',false)}};
document.getElementById('watxtcopy').onclick=async()=>{if(await copyText()){mark();say('Tekst je kopiran. Zalijepi ga u grupu.')}
  else say('Kopiranje nije uspjelo: označi tekst ispod i kopiraj ručno.',false)};
const dl=document.getElementById('wadl');dl.download=fname;blob.then(b=>dl.href=URL.createObjectURL(b));
})();
"""


def _bubble(text):
    """The message as WhatsApp shows it: *bold* and _italic_."""
    import re
    h = esc(text)
    h = re.sub(r"\*([^*\n]+)\*", r"<b>\1</b>", h)
    return re.sub(r"(?<![\w/])_([^_\n]+)_(?![\w])", r"<i>\1</i>", h)


def page(qs, user=None):
    d = digest.collect(repeat=qs.get("ponovi") == "1")
    text = digest.text(d)
    st = digest.load_state()
    last = max(st.get("copied_ts") or 0, st.get("sent_ts") or 0)
    b = ["<style>" + CSS + "</style><h1>📲 Za WhatsApp</h1>"
         "<p class=lead>Gotov sažetak za vašu WhatsApp grupu: slika s ljestvicom i najboljim tradeom plus kratka "
         "poruka s novostima u aplikaciji. Na mobitelu pritisni <b>Pošalji u WhatsApp</b> i odaberi grupu.</p>",
         "<div class=wa><div><img id=waimg alt='Slika za WhatsApp'></div><div>",
         "<div class=wabtns><button class=go id=wasend>📤 Pošalji u WhatsApp</button>"
         "<button id=waimgcopy>🖼 Kopiraj sliku</button><button id=watxtcopy>📋 Kopiraj tekst</button>"
         "<a id=wadl href=#>⬇️ Preuzmi sliku</a></div><div id=wamsg class=wamsg></div>",
         f"<div class=wabub>{_bubble(text)}</div>",
         f"<textarea id=watext readonly style='position:absolute;left:-9999px'>{esc(text)}</textarea>",
         "<p class=mut style='margin-top:12px'>Novosti u aplikaciji pojavljuju se samo jednom: nakon slanja ili "
         "kopiranja ovdje ostaje samo ono što je novo od tada. "
         + (f"Zadnje slanje u grupu: {ago(last)[0]}. " if last else "")
         + "<a href='/whatsapp?ponovi=1'>Prikaži opet zadnje novosti</a>.</p>"]
    miss = gateway.missing()
    if not miss:
        hour = __import__("os").environ.get("WHATSAPP_HOUR", "19")
        b.append(f"<p class=pos>Automatsko slanje je uključeno: svaki dan u {esc(hour)} h ovaj tekst ide u grupu "
                 f"preko {esc(gateway.PROVIDERS[gateway.provider()])}."
                 + (f" Zadnja greška: {esc(st['error'])}" if st.get("error") else "") + "</p>")
    else:
        b.append("<details><summary>Može li ovo ići u grupu samo, bez kopiranja?</summary><p class=mut>Može, uz plaćeni "
                 "servis (Whapi.cloud ili Green API, oko 15–40 $ mjesečno) i jedan dodatni broj mobitela koji se doda u "
                 "grupu. Tada poruka svaki dan sama ode u grupu. Službeni WhatsApp ne dopušta botovima pisanje u obične "
                 "grupe pa takav broj može biti blokiran; nikad ne koristi svoj privatni broj. Javi Claudeu ako to "
                 "želiš.</p></details>")
    b.append("</div></div>")
    data_json = json.dumps(d, ensure_ascii=False).replace("</", "<\\/")
    b.append(f"<script type=application/json id=wadata>{data_json}</script><script>{JS}</script>")
    return "Za WhatsApp", "".join(b)


def post_shared():
    digest.mark_shared("copied")
