"""Public pages of the macro influencers (EN main + HR), rendered through ui/public._shell and cached by
ui/public.route like the other public pages:

  /macro-influencers, /macro-influencer/<handle>              English (x-default)
  /hr/makro-influenceri, /hr/makro-influencer/<handle>        Croatian

Behind the OWNER SWITCH makroinf_javno (default off; on since his order of 15.11.: "Možeš ti odmah objaviti te
stranice javno ..."): while it is off every route answers 404 and nothing is in the sitemap, robots.txt or the menu.
Rules (as ui/apjavno.py): only aggregated statistics with their intervals and n, the methodology, "insufficient
evidence" (the label "still collecting evidence") below 10 episodes, links to the original posts (no post text is
copied; a post no longer visible is "later unavailable", without a link), neutral wording (no accusations), the
stances, the index and the market mood with a PUBLIC_DELAY_S delay (members see them fresh in the app,
makroinf/web.py, makroinf/appviews.py), never keys, env names, internal services, costs or wallets. The numbers are
the last scoring's: makroinf/web.sync drops the cached copies when it moves.
15.11. navečer (the owner: "Objavi. Neka Google sve indeksira, pa nek se podaci osvježavaju."): EVERY page is
indexable (no noindex, also below 10 episodes: the honest label stays) and in the sitemap, lastmod = the day of the
newest scoring / topics (daily). The hub also carries the market mood of the influencers (as of 7 days ago, with its
sources: the counts, the accounts, the posts) and the topics of the day (same day: topics are not stances; the accounts
of a topic link to their pages here, not to today's posts).
"""
import json
import os
import re
import time

from makroinf import mood as mmood
from makroinf import teme as mteme
from makroinf import web
from ui.html import esc

PUBLIC_DELAY_S = web.PUBLIC_DELAY_S
MIN_EP = web.MIN_EP
HANDLE = web.HANDLE
GONE = web.GONE
CAT = {"en": {"ta": "Trader / TA", "makro": "Macro / on-chain", "edukacija": "YouTube / education",
              "memecoin": "Memecoin KOL", "vijesti": "News / aggregator"},
       "hr": {"ta": "Trader / TA", "makro": "Makro / on-chain", "edukacija": "YouTube / edukacija",
              "memecoin": "Memecoin KOL", "vijesti": "Vijesti / agregator"}}
DIR = {"en": {"up": "up", "down": "down", "bottom_in": "bottom is in", "top_in": "top is in", "range": "range"},
       "hr": {"up": "gore", "down": "dolje", "bottom_in": "dno je tu", "top_in": "vrh je tu", "range": "raspon"}}
RES = {"en": {"hit": "hit", "miss": "miss", "flat": "no clear move", "ceka": "pending", "neaktiviran": "condition not met",
              "bez_podataka": "no price data", "dugo": "long-term (not scored)"},
       "hr": {"hit": "pogodak", "miss": "promašaj", "flat": "bez jasnog pomaka", "ceka": "čeka", "neaktiviran":
              "uvjet nije ispunjen", "bez_podataka": "nema cijene", "dugo": "dugoročno (ne mjeri se)"}}
ASSET = {"en": {"BTC": "BTC", "ETH": "ETH", "SOL": "SOL", "alts": "altcoins", "memes": "meme coins", "total": "crypto market"},
         "hr": {"BTC": "BTC", "ETH": "ETH", "SOL": "SOL", "alts": "altcoini", "memes": "meme coini",
                "total": "kripto tržište"}}
VERDICT = {"en": {"bolji od baznih strategija": "better than the simple baselines",
                  "lošiji od baznih strategija": "below the simple baselines",
                  "ne razlikuje se od baznih strategija": "not distinguishable from the simple baselines",
                  "dodaje vrijednost": "adds value over always-bullish",
                  "gubi prema uvijek-bik": "trails always-bullish",
                  "ne razlikuje se od uvijek-bik": "no clear difference from always-bullish",
                  "nedovoljno dokaza": "insufficient evidence"},
           "hr": {"bolji od baznih strategija": "bolji od jednostavnih osnova",
                  "lošiji od baznih strategija": "ispod jednostavnih osnova",
                  "ne razlikuje se od baznih strategija": "ne razlikuje se od jednostavnih osnova",
                  "dodaje vrijednost": "dodaje vrijednost prema uvijek-bik",
                  "gubi prema uvijek-bik": "zaostaje za uvijek-bik",
                  "ne razlikuje se od uvijek-bik": "bez jasne razlike prema uvijek-bik",
                  "nedovoljno dokaza": "nedovoljno dokaza"}}
RTONE = {"hit": "st-up", "miss": "st-dn"}
TONE = {"bolji od baznih strategija": "good", "lošiji od baznih strategija": "bad", "dodaje vrijednost": "good",
        "gubi prema uvijek-bik": "bad"}
BASE = {"en": {"uvijek_bik": "always bullish", "nasumicno": "coin flip", "trend_7d": "7-day trend"},
        "hr": {"uvijek_bik": "uvijek bikovski", "nasumicno": "bacanje novčića", "trend_7d": "trend 7 dana"}}
LEAN = {"en": {"bull": "Bullish", "bear": "Bearish", "neutral": "Neutral"},
        "hr": {"bull": "Bikovski", "bear": "Medvjeđi", "neutral": "Neutralno"}}
MONTHS_EN = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")

T = {
    "en": dict(
        hub="/macro-influencers", prof="/macro-influencer/", other="/hr/makro-influenceri", how_id="how-we-measure",
        nav=("Macro influencers", "Calls on BTC and the market measured"),
        title="Crypto macro influencers: who calls BTC right? | MemeSonar",
        desc="{n} well-known crypto accounts on X, their calls on BTC, ETH, SOL, altcoins and meme coins measured "
             "against what the market did, with rules fixed in advance. Hit rate with intervals, baselines, n.",
        h1="Crypto macro influencer scorecard",
        lead="We measure the market calls of {n} well-known crypto accounts on X against what BTC, ETH, SOL, altcoins "
             "and meme coins did next. The rules were fixed before looking at any result.",
        kpi=("accounts tracked", "measured calls", "with enough evidence", "updated"),
        rank_h="Ranked accounts", rank_note="Accounts with at least {m} measured episodes, ordered by their hit rate "
        "shrunk towards the average (a short lucky streak does not top the list).",
        rank_none="No account has {m} measured episodes yet. The ranking appears here as the evidence comes in; until "
                  "then every account is listed below without a verdict.",
        cols=("#", "Account", "Episodes", "Hit rate (95 % interval)", "vs best baseline", "Follow vs always-bull",
              "Later unavailable", "BTC stance 7 days ago"),
        m_line="{n} episodes · vs best baseline {b} · follow vs always-bull {e} · later unavailable {g}",
        st_short="BTC 7 days ago",
        few_h="Still collecting evidence", few_note="Fewer than {m} measured episodes: no rank and no verdict yet. "
        "Their pages show what they said and are updated every day as the evidence comes in.",
        mood_h="Market mood of the influencers", mood_as="as of {d}, published with a 7-day delay",
        mood_none="Not enough history yet: the market mood is published with a 7-day delay once it exists.",
        win={"24h": "24 hours", "7d": "7 days"}, sides={"bik": "Bullish", "medvjed": "Bearish", "neutralno": "Neutral"},
        mood_card="{n} accounts with a view in the {w} to {d}",
        mood_split="{b} bullish · {m} bearish · {z} neutral", mood_w="Weighted by accuracy: {v} ({s})",
        mood_rule="Each account counts once, with the sign of its calls in the window (conditional, unclear, joke and "
                  "promotional calls are left out). Weighted: more accurate accounts count more and a cluster of "
                  "look-alike accounts counts as one and a half at most. ",
        src_h="Where this comes from", src_cols=("Side", "Accounts", "Share", "Weighted"), src_posts="posts",
        topics_h="Topics of the day", topics_note="Grouped from {p} market posts of {a} accounts in the 24 hours to {d} "
        "(UTC), refreshed four times a day.", topics_none="No topics yet: they are grouped from the day's market posts.",
        topic_meta="{a} accounts · {p} posts", topic_who="Accounts",
        assets_h="By asset", assets_note="7 days to {d}; bullish and bearish as a share of the accounts with a side.",
        assets_cols=("Asset", "Accounts", "Bullish", "Bearish", "Reading"),
        ds_name="Crypto macro influencer market mood",
        ds_desc="Daily share of bullish, bearish and neutral crypto macro influencers on X, from their classified "
                "market calls, unweighted and weighted by measured accuracy, published with a 7-day delay.",
        few_cols=("Account", "Measured episodes", "BTC stance 7 days ago"),
        few="still collecting evidence", none="No measured calls yet.",
        cov="What we read: {p} posts, {c} of them market calls ({a}), {d0} to {d1}.",
        idx_h="Consensus of the most accurate accounts",
        idx="On BTC, as of {d}: {v} on a scale from −1 (all bearish) to +1 (all bullish), from {n} of the most accurate "
            "accounts with a view. Published with a 7-day delay.",
        idx_none="Not enough history yet: the consensus is published with a 7-day delay once it exists.",
        how_h="How we measure",
        how=("A call is a post stating where a market goes (up, down, the bottom or the top is in, a range), on BTC, ETH, "
             "SOL, altcoins, meme coins or the whole market. Posts are classified automatically; a stratified sample is "
             "audited.",
             "Horizons are fixed in advance: 7 and 30 days. A call that states its horizon is tested on the matching one; "
             "a call without one is tested on both, each with half weight, and both results are shown.",
             "A hit means the price moved in the called direction by more than half of its usual move over that horizon "
             "(volatility of the 30 days before the call). Conditional calls (\"if BTC loses 60k\") count only once the "
             "condition is met.",
             "Repeating the same call is one prediction (an episode), not ten.",
             "Every account is compared with simple baselines on the same dates: always bullish, a coin flip and "
             "following the last 7 days' trend. A hit rate means little unless it beats them.",
             "Three separate scores, never multiplied: predictive (hit rate with a 95 % interval), economic (the return "
             "of following the calls against always-bullish) and integrity (posts that later became unavailable, "
             "promotions).",
             "Fewer than {m} measured episodes = insufficient evidence: no rank and no verdict.",
             "\"Later unavailable\" means we can no longer see a post we stored (deleted, or the account became private "
             "or suspended). It is reported, not judged.",
             "Known limits: the accounts are the ones well known today, and history only shows posts that still existed "
             "when we first read them."),
        lock="Members see every account's current stance and the consensus live, without the 7-day delay.",
        cta="Request access", back="← All macro influencers", memecoin="Memecoin calls of @{h} →",
        p_title="@{h}: crypto market calls measured, hit rate {hit} | MemeSonar",
        p_title_few="@{h}: crypto market calls measured | MemeSonar",
        p_desc="How did @{h}'s calls on BTC and the crypto market play out? {n} measured episodes, hit rate {hit} "
               "(95 % interval {lo}–{hi}) against simple baselines on the same dates.",
        p_desc_few="We measure @{h}'s calls on BTC and the crypto market; {n} measured episodes so far, too few for a "
                   "verdict.",
        p_lead="Hit rate {hit} (95 % interval {ci}) on {n} measured episodes; the best simple baseline on the same "
               "dates hit {b} ({bn}). Verdict: {v}.",
        p_lead_few="{n} of the {m} measured episodes needed for a verdict so far. No rank yet; the numbers below are for "
                   "information only.",
        rank_of="#{k} of {n} ranked",
        cards=("Predictive", "Economic", "Integrity"),
        c_pred="95 % interval {ci} · n {n} · best baseline {b}",
        c_econ="return of following the calls vs always-bullish, per call · 95 % {lo} to {hi} · n {n}",
        c_integ="of {m} calls later unavailable · promotions {p}",
        hz_h="By horizon", hz_cols=("Group", "Measured", "Hit rate", "95 % interval"),
        hz_names={"s_rokom_7d": "Stated horizon, 7 days", "s_rokom_30d": "Stated horizon, 30 days",
                  "bez_roka_7d": "No horizon, tested at 7 days", "bez_roka_30d": "No horizon, tested at 30 days"},
        ep_h="Calls (older than 7 days)", ep_cols=("Date", "Call", "Horizon", "Result", "Post"),
        post="post", gone="later unavailable", stance="Stance on BTC 7 days ago: {s}.", no_stance="no current view",
        method="How we measure →", crumb_home="Home",
        foot_note="Not financial advice. These are measurements of past public posts, not accusations or endorsements.",
        pg="Page {p} of {n}", pg_range="Accounts {a}–{b} of {n}", pg_prev="← Previous {k}", pg_next="Next {k} accounts →",
        pg_first="← Mood, topics and method", pg_nav="More accounts",
        pg_title="Crypto macro influencer scorecard: page {p} | MemeSonar",
        pg_desc="Accounts {a}–{b} of {n} on the crypto macro influencer scorecard: their calls on BTC and the market "
                "measured against what happened, with hit rate, intervals and baselines."),
    "hr": dict(
        hub="/hr/makro-influenceri", prof="/hr/makro-influencer/", other="/macro-influencers", how_id="kako-mjerimo",
        nav=("Makro influenceri", "Izjave o BTC-u i tržištu izmjerene"),
        title="Kripto makro influenceri: tko pogađa BTC? | MemeSonar",
        desc="{n} poznatih kripto računa na X-u, njihove izjave o BTC-u, ETH-u, SOL-u, altcoinima i meme coinima "
             "izmjerene prema tome što je tržište napravilo, pravilima zadanima unaprijed. Pogodak s intervalima, n.",
        h1="Ocjene kripto makro influencera",
        lead="Izjave {n} poznatih kripto računa na X-u o tržištu mjerimo prema tome što su BTC, ETH, SOL, altcoini i "
             "meme coini zatim napravili. Pravila su zadana prije nego što smo vidjeli ijedan rezultat.",
        kpi=("praćenih računa", "izmjerenih izjava", "s dovoljno dokaza", "osvježeno"),
        rank_h="Rangirani računi", rank_note="Računi s barem {m} izmjerenih epizoda, poredani po pogotku skupljenom "
        "prema prosjeku (kratki niz sreće ne dolazi na vrh).",
        rank_none="Još nijedan račun nema {m} izmjerenih epizoda. Poredak se pojavi ovdje kako dokazi stižu; dotad su "
                  "svi računi ispod, bez presude.",
        cols=("#", "Račun", "Epizode", "Pogodak (95 % interval)", "prema najboljoj osnovi", "Praćenje prema uvijek-bik",
              "Naknadno nedostupno", "Stav o BTC-u prije 7 dana"),
        m_line="{n} epizoda · prema najboljoj osnovi {b} · praćenje prema uvijek-bik {e} · naknadno nedostupno {g}",
        st_short="BTC prije 7 dana",
        few_h="Još skupljaju dokaze", few_note="Manje od {m} izmjerenih epizoda: još bez ranga i bez presude. Njihove "
        "stranice pokazuju što su rekli i osvježavaju se svaki dan kako dokazi stižu.",
        mood_h="Raspoloženje influencera prema tržištu", mood_as="stanje {d}, objavljuje se s odgodom od 7 dana",
        mood_none="Još nema dovoljno povijesti: raspoloženje se objavljuje s odgodom od 7 dana kad postoji.",
        win={"24h": "24 sata", "7d": "7 dana"}, sides={"bik": "Bikovski", "medvjed": "Medvjeđi", "neutralno": "Neutralno"},
        mood_card="{n} računa sa stavom u {w} do {d}",
        mood_split="{b} bikovski · {m} medvjeđi · {z} neutralno", mood_w="Ponderirano točnošću: {v} ({s})",
        mood_rule="Svaki račun broji se jednom, predznakom svojih izjava u razdoblju (uvjetne, nejasne, šaljive i "
                  "promotivne izjave se ne broje). Ponderirano: točniji računi vrijede više, a skupina sličnih računa "
                  "zajedno najviše kao jedan i pol. ",
        src_h="Iz čega je izvučeno", src_cols=("Strana", "Računa", "Udio", "Ponderirano"), src_posts="objave",
        topics_h="Teme dana", topics_note="Složeno iz {p} tržišnih objava {a} računa u 24 sata do {d} (UTC), "
        "osvježava se četiri puta dnevno.", topics_none="Još nema tema: slažu se iz tržišnih objava dana.",
        topic_meta="{a} računa · {p} objava", topic_who="Računi",
        assets_h="Po imovini", assets_note="7 dana do {d}; bikovski i medvjeđi kao udio računa s jasnom stranom.",
        assets_cols=("Imovina", "Računa", "Bikovski", "Medvjeđi", "Zaključak"),
        ds_name="Raspoloženje kripto makro influencera",
        ds_desc="Dnevni udio bikovskih, medvjeđih i neutralnih kripto makro influencera na X-u iz njihovih razvrstanih "
                "izjava o tržištu, bez pondera i ponderirano izmjerenom točnošću, objavljeno s odgodom od 7 dana.",
        few_cols=("Račun", "Izmjerene epizode", "Stav o BTC-u prije 7 dana"),
        few="skuplja dokaze", none="Još nema izmjerenih izjava.",
        cov="Što smo pročitali: {p} objava, od toga {c} izjava o tržištu ({a}), od {d0} do {d1}",
        idx_h="Konsenzus najtočnijih računa",
        idx="O BTC-u, stanje {d}: {v} na ljestvici od −1 (svi medvjeđi) do +1 (svi bikovski), od {n} najtočnijih računa "
            "sa stavom. Objavljuje se s odgodom od 7 dana.",
        idx_none="Još nema dovoljno povijesti: konsenzus se objavljuje s odgodom od 7 dana kad postoji.",
        how_h="Kako mjerimo",
        how=("Izjava je objava koja kaže kamo ide tržište (gore, dolje, dno ili vrh je tu, raspon), o BTC-u, ETH-u, SOL-u, "
             "altcoinima, meme coinima ili cijelom tržištu. Objave se razvrstavaju automatski; stratificirani uzorak se "
             "provjerava.",
             "Horizonti su zadani unaprijed: 7 i 30 dana. Izjava s rokom mjeri se na odgovarajućem; izjava bez roka na "
             "oba, svaki s pola težine, i oba rezultata su prikazana.",
             "Pogodak znači da se cijena pomaknula u najavljenom smjeru više od pola svog uobičajenog pomaka u tom "
             "horizontu (volatilnost 30 dana prije izjave). Uvjetne izjave („ako BTC izgubi 60k”) broje se tek kad se "
             "uvjet ostvari.",
             "Ponavljanje iste izjave je jedno predviđanje (epizoda), ne deset.",
             "Svaki račun uspoređujemo s jednostavnim osnovama na istim datumima: uvijek bikovski, bacanje novčića i "
             "praćenje trenda zadnjih 7 dana. Pogodak malo znači ako ih ne nadmašuje.",
             "Tri odvojene ocjene, nikad pomnožene: prediktivna (pogodak s 95 % intervalom), ekonomska (povrat praćenja "
             "izjava prema uvijek-bik) i integritet (objave koje su naknadno postale nedostupne, promocije).",
             "Manje od {m} izmjerenih epizoda = nedovoljno dokaza: bez ranga i bez presude.",
             "„Naknadno nedostupno” znači da objavu koju smo spremili više ne vidimo (obrisana ili je račun postao "
             "privatan ili suspendiran). Navodimo to, ne prosuđujemo.",
             "Poznata ograničenja: računi su oni poznati danas, a povijest pokazuje samo objave koje su postojale kad smo "
             "ih prvi put pročitali."),
        lock="Članovi vide trenutni stav svakog računa i konsenzus uživo, bez odgode od 7 dana.",
        cta="Zatraži pristup", back="← Svi makro influenceri", memecoin="Memecoin pozivi od @{h} →",
        p_title="@{h}: izmjerene izjave o kripto tržištu, pogodak {hit} | MemeSonar",
        p_title_few="@{h}: izmjerene izjave o kripto tržištu | MemeSonar",
        p_desc="Kako su prošle izjave @{h} o BTC-u i kripto tržištu? {n} izmjerenih epizoda, pogodak {hit} (95 % "
               "interval {lo}–{hi}) prema jednostavnim osnovama na istim datumima.",
        p_desc_few="Mjerimo izjave @{h} o BTC-u i kripto tržištu; dosad {n} izmjerenih epizoda, premalo za presudu.",
        p_lead="Pogodak {hit} (95 % interval {ci}) na {n} izmjerenih epizoda; najbolja jednostavna osnova na istim "
               "datumima pogodila je {b} ({bn}). Presuda: {v}.",
        p_lead_few="Dosad {n} od {m} izmjerenih epizoda potrebnih za presudu. Još bez ranga; brojke ispod su samo "
                   "informativne.",
        rank_of="#{k} od {n} rangiranih",
        cards=("Prediktivno", "Ekonomski", "Integritet"),
        c_pred="95 % interval {ci} · n {n} · najbolja osnova {b}",
        c_econ="povrat praćenja izjava prema uvijek-bik, po izjavi · 95 % {lo} do {hi} · n {n}",
        c_integ="od {m} izjava naknadno nedostupno · promocija {p}",
        hz_h="Po horizontu", hz_cols=("Skupina", "Izmjereno", "Pogodak", "95 % interval"),
        hz_names={"s_rokom_7d": "S rokom, 7 dana", "s_rokom_30d": "S rokom, 30 dana",
                  "bez_roka_7d": "Bez roka, mjereno na 7 dana", "bez_roka_30d": "Bez roka, mjereno na 30 dana"},
        ep_h="Izjave (starije od 7 dana)", ep_cols=("Datum", "Izjava", "Horizont", "Ishod", "Objava"),
        post="objava", gone="naknadno nedostupno", stance="Stav o BTC-u prije 7 dana: {s}.", no_stance="bez stava",
        method="Kako mjerimo →", crumb_home="Naslovnica",
        foot_note="Nije financijski savjet. Ovo su mjerenja prošlih javnih objava, a ne optužbe ili preporuke.",
        pg="Stranica {p} od {n}", pg_range="Računi {a}–{b} od {n}", pg_prev="← Prethodnih {k}",
        pg_next="Sljedećih {k} računa →", pg_first="← Raspoloženje, teme i metoda", pg_nav="Još računa",
        pg_title="Ocjene kripto makro influencera: stranica {p} | MemeSonar",
        pg_desc="Računi {a}–{b} od {n} na ljestvici kripto makro influencera: njihove izjave o BTC-u i tržištu "
                "izmjerene prema onome što se dogodilo, s pogotkom, intervalima i osnovama."),
}

CSS = """<style>
.mk{display:flex;flex-wrap:wrap;gap:8px;margin:-6px 0 26px}.mk span{border:1px solid var(--line);background:var(--soft);
border-radius:999px;padding:6px 13px;font-size:14px;color:var(--mut)}.mk b{color:var(--fg);font-weight:650;margin-right:4px}
.mix{border:1px solid var(--line);border-radius:18px;padding:18px 20px;background:#fff;display:flex;gap:6px 22px;align-items:center;flex-wrap:wrap}
.mixw{font-size:28px;font-weight:760;letter-spacing:-.02em;white-space:nowrap}.mix p{margin:0;color:var(--mut);flex:1 1 300px}
.mixw i{display:inline-block;width:12px;height:12px;border-radius:50%;margin-right:10px;vertical-align:middle;background:#cfd5e1}
.mixw i.good{background:#16a34a}.mixw i.bad{background:#dc2626}
.mnote{color:var(--mut);margin:-4px 0 12px;font-size:15px}
td .mcat{display:block;font-size:12.5px;color:var(--mut);font-weight:400;margin:2px 0 0}
td .ci{color:var(--mut)}table.mr td.mr-meta,.mo{display:none}table.mr td a{white-space:nowrap}
@media(max-width:700px){
table.mr,table.mr tbody{display:block}table.mr thead{display:none}
table.mr tr{display:block;position:relative;padding:14px 14px 14px 42px;border-bottom:1px solid var(--line)}
table.mr tr:last-child{border-bottom:0}table.mr td{display:block;border:0;padding:0;white-space:normal}
table.mr td.mr-ep,table.mr td.mr-bl,table.mr td.mr-fo,table.mr td.mr-un{display:none}
table.mr td.mr-rk{position:absolute;left:16px;top:15px}table.mr td.mr-acc{padding-right:92px}
table.mr td.mr-hit{position:absolute;right:14px;top:14px;text-align:right}table.mr td.mr-hit .ci{display:block;font-size:12.5px}
table.mr td.mr-st{margin-top:8px;font-size:14.5px}table.mr td.mr-meta{display:block;margin-top:4px;font-size:13px;color:var(--mut);line-height:1.45}
table.mr .mo{display:inline;color:var(--mut)}
table.mh td,table.mh th{padding:10px 10px;white-space:normal}table.mh .x{display:none}}
.vb{display:inline-block;font-size:12.5px;border-radius:999px;padding:3px 9px;border:1px solid var(--line);background:var(--soft);
color:var(--fg);white-space:nowrap}.vb.good{background:#ecfdf5;border-color:#bbf7d0}.vb.bad{background:#fef2f2;border-color:#fecaca}
.vb.few{background:transparent;border-style:dashed;color:var(--mut)}
.st-up{color:#16a34a;font-weight:600}.st-dn{color:#dc2626;font-weight:600}.st-fl{font-weight:600}
.mc3{display:grid;grid-template-columns:repeat(3,1fr);gap:12px;margin:8px 0 10px}@media(max-width:760px){.mc3{grid-template-columns:1fr}}
.mc3 .card b{font-size:28px}.mc3 .card p{margin:6px 0 0;color:var(--mut);font-size:14px;line-height:1.45}
.mc3 .card .vb{margin-top:8px}.who{color:var(--mut);margin:0 0 4px}.who a{color:var(--acc)}
.plead{font-size:17px;max-width:760px;margin:6px 0 12px}.rp{display:block}.rp.mut{color:var(--mut)}td.nw{white-space:nowrap!important}
@media(max-width:600px){.mixw{font-size:24px}table.coins td .mcat{white-space:normal}}
.md2{display:grid;grid-template-columns:1fr 1fr;gap:12px;margin:0 0 10px}@media(max-width:700px){.md2{grid-template-columns:1fr}}
.mdc{border:1px solid var(--line);border-radius:18px;padding:16px 18px;background:#fff;min-width:0}
.mdc .l{font-size:13px;color:var(--mut)}.mdc .w{font-size:26px;font-weight:760;letter-spacing:-.02em;margin:4px 0 10px;
display:flex;align-items:center;gap:10px}.mdc .w i{width:12px;height:12px;border-radius:50%;background:#cfd5e1;flex:none}
.mdc .w i.good{background:#16a34a}.mdc .w i.bad{background:#dc2626}.mdc p{margin:6px 0 0;color:var(--mut);font-size:14.5px}
.mdc p b{color:var(--fg)}.mbar{display:flex;height:10px;border-radius:999px;overflow:hidden;background:var(--soft)}
.mbar span{display:block;height:100%}.mbar .b{background:#16a34a}.mbar .n{background:#cfd5e1}.mbar .m{background:#dc2626}
.mrule{color:var(--mut);font-size:14px;margin:6px 0 10px;max-width:820px}
details.msrc{border:1px solid var(--line);border-radius:16px;background:#fff;margin:10px 0 0}
details.msrc>summary{cursor:pointer;padding:12px 16px;font-weight:600;font-size:15px}details.msrc .in{padding:0 16px 14px}
details.msrc table{font-size:14px}details.msrc th,details.msrc td{padding:9px 10px}
.mwho{font-size:14px;line-height:1.9;margin:8px 0 0}.mwho b{display:block;color:var(--mut);font-weight:600;font-size:13px;line-height:1.4;margin-top:6px}
.mwho span{white-space:nowrap;margin-right:8px}.mwho a{color:var(--acc)}.mwho a.p{font-size:11.5px;color:var(--mut);
border:1px solid var(--line);border-radius:6px;padding:0 4px;margin-left:3px}
ol.mtp{list-style:none;padding:0;margin:0;counter-reset:t;border:1px solid var(--line);border-radius:18px;background:#fff}
ol.mtp>li{counter-increment:t;padding:14px 16px 14px 46px;position:relative;border-bottom:1px solid var(--line)}
ol.mtp>li:last-child{border-bottom:0}ol.mtp>li:before{content:counter(t);position:absolute;left:18px;top:14px;color:var(--mut);font-weight:600}
ol.mtp .mt-t{font-weight:650;font-size:16.5px}ol.mtp .mt-s{margin:3px 0 0}
ol.mtp .mt-m{color:var(--mut);font-size:13.5px;margin:4px 0 0}ol.mtp .mt-m a{color:var(--acc)}
.mpg{display:flex;flex-wrap:wrap;gap:10px 14px;align-items:center;justify-content:space-between;margin:18px 0 6px}
.mpg span{color:var(--mut);font-size:14.5px}.mpg a{border:1px solid var(--line);border-radius:999px;padding:9px 16px;
background:#fff;color:var(--fg);text-decoration:none;font-weight:600;font-size:15px}.mpg a:hover{border-color:var(--acc)}
</style>"""


def on():
    """True while the owner switch makroinf_javno is on ("live"). Never raises: unreadable = off."""
    return web.on()


NB = "\u00a0"   # a number and its unit never break apart


def _pct(x, lang=None):
    return "–" if x is None else f"{x * 100:.0f}{NB}%"


def _pp(x, lang):
    if x is None:
        return "–"
    s = f"{x * 100:+.1f}{NB}pp".replace("-", "−")
    return s.replace(".", ",") if lang == "hr" else s


def _ci(lo, hi):
    return "–" if lo is None or hi is None else f"{lo * 100:.0f}–{hi * 100:.0f}{NB}%"


def _num(v, lang, dec=2):
    s = f"{v:+.{dec}f}".replace("-", "−")
    return s.replace(".", ",") if lang == "hr" else s


def _date(ts, lang):
    if not ts:
        return "–"
    g = time.gmtime(ts)
    return f"{g.tm_mday} {MONTHS_EN[g.tm_mon - 1]} {g.tm_year}" if lang == "en" else time.strftime("%d.%m.%Y.", g)


def _iso(ts):
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(ts)) if ts else None


def _stance(r, lang):
    st = r.get("stav")
    if not st:
        return f"<span class=mut>{T[lang]['no_stance']}</span>"
    sg = web.SIGN.get(st["dir"], 0)
    cls = "st-up" if sg > 0 else "st-dn" if sg < 0 else "st-fl"
    arrow = "↑ " if sg > 0 else "↓ " if sg < 0 else "↔ "
    return f"<span class={cls}>{arrow}{esc(DIR[lang].get(st['dir'], st['dir']))}</span>"


def _stance_text(r, lang):
    st = r.get("stav")
    return DIR[lang].get(st["dir"], st["dir"]) if st else T[lang]["no_stance"]


VIEW_TTL_S = 300


def _view():
    """23.11. (hitno): web.view reads every score (JSON per account) and counts the tweets; a burst of account pages
    did it once per page. One shared copy per process now, rebuilt when the scores move (web.stamp) or after
    VIEW_TTL_S. Shared: do not change it."""
    from makroinf import store
    from ui import javniteret
    p = store.db_path()
    return javniteret.shared(("makro_view", p), VIEW_TTL_S, lambda: web.view(fresh=False),
                             version=(web.stamp(), javniteret.file_version(p)))


def _jsonld(obj):
    return '<script type="application/ld+json">' + json.dumps(obj, ensure_ascii=False).replace("</", "<\\/") + "</script>"


def _pct_i(x):
    return "–" if x is None else f"{round(x * 100)}{NB}%"


def _verdict_word(key, lang):
    return mmood.VERDICT[lang].get(key, key)


def _split(st, lang):
    t = T[lang]
    if not st or st.get("bik") is None:
        return "–"
    return f"{_pct_i(st['bik'])} {t['sides']['bik'].lower()} · {_pct_i(st['medvjed'])} {t['sides']['medvjed'].lower()}"


def _post(h, i):
    return f"https://x.com/{h}/status/{i}"


def mood_html(lang, m=None):
    """The market mood as of 7 days ago (both windows), the rule and its sources."""
    t = T[lang]
    m = m if m is not None else mmood.load(public=True)
    head = f"<h2 class=s id=mood>{t['mood_h']}</h2>"
    blocks = (m or {}).get("okviri") or {}
    if not blocks or not any((b or {}).get("n") for b in blocks.values()):
        return head + f"<div class=mix><p>{esc(t['mood_none'])}</p></div>"
    d = _date(m.get("t"), lang)
    cards, srcs = [], []
    for key in ("24h", "7d"):
        b = blocks.get(key)
        if not b:
            continue
        tone = mmood.TONE.get(b["presuda"], "")
        u = b["udio"]
        bar = "".join(f"<span class={c} style='width:{round((u.get(k) or 0) * 100, 1)}%'></span>"
                      for k, c in (("bik", "b"), ("neutralno", "n"), ("medvjed", "m")))
        cards.append(f"<div class=mdc><div class=l>{esc(t['mood_card'].format(n=b['n'], w=t['win'][key], d=d))}</div>"
                     f"<div class=w><i class='{tone}'></i>{esc(_verdict_word(b['presuda'], lang))}</div>"
                     f"<div class=mbar>{bar}</div><p><b>{esc(_split(b['strane'], lang))}</b> · {b['broj']['neutralno']} "
                     f"{t['sides']['neutralno'].lower()}</p><p>{esc(t['mood_w'].format(v=_verdict_word(b['presuda_pond'], lang).lower(), s=_split(b['strane_pond'], lang)))}</p></div>")
        if not b["n"]:
            continue
        trs = "".join(f"<tr><td>{t['sides'][k]}</td><td class=n>{b['broj'][k]}</td><td class=n>{_pct_i(b['udio'][k])}</td>"
                      f"<td class=n>{_pct_i(b['udio_pond'][k])}</td></tr>" for k in mmood.SIDES)
        head_t = "".join(f"<th{' class=n' if j else ''}>{x}</th>" for j, x in enumerate(t["src_cols"]))
        who = ""
        for k in mmood.SIDES:
            rows = b["racuni"][k]
            if not rows:
                continue
            items = "".join(
                f"<span><a href=\"{t['prof']}{r['h']}\">@{esc(r['h'])}</a>"
                + "".join(f"<a class=p href=\"{_post(r['h'], i)}\" target=_blank rel=\"nofollow noopener\">{j}</a>"
                          for j, i in enumerate(r["ids"][:3], 1)) + "</span>" for r in rows[:80])
            who += f"<div class=mwho><b>{t['sides'][k]} · {len(rows)}</b>{items}</div>"
        srcs.append(f"<details class=msrc><summary>{t['src_h']} · {t['win'][key]}</summary><div class=in><div class=tw>"
                    f"<table><thead><tr>{head_t}</tr></thead><tbody>{trs}</tbody></table></div>{who}</div></details>")
    line = mmood.line(blocks.get("24h"), lang)
    return (head + f"<p class=mnote>{esc(line.rstrip('.'))} ({esc(t['mood_as'].format(d=d))}).</p>"
            f"<div class=md2>{''.join(cards)}</div>"
            f"<p class=mrule>{esc(t['mood_rule'])}{esc(mmood.rule_text(lang))}</p>{''.join(srcs)}")


def topics_html(lang, tp=None, known=None):
    """The topics of the day (same day): title, one sentence, how many accounts and posts, the accounts (links to their
    pages here)."""
    t = T[lang]
    tp = tp if tp is not None else mteme.load()
    head = f"<h2 class=s id=topics>{t['topics_h']}</h2>"
    if not tp or not tp.get("topics"):
        return head + f"<p class=mnote>{esc(t['topics_none'])}</p>"
    known = known or set()
    items = []
    for x in tp["topics"]:
        hs = [h for h in x.get("handles") or [] if h.lower() in known][:12]
        who = ", ".join(f"<a href=\"{t['prof']}{h}\">@{esc(h)}</a>" for h in hs)
        items.append(f"<li><div class=mt-t>{esc(x['title_' + lang] or x['title_en'])}</div>"
                     f"<div class=mt-s>{esc(x['summary_' + lang] or x['summary_en'])}</div>"
                     f"<div class=mt-m>{esc(t['topic_meta'].format(a=x['n_accounts'], p=x['n_posts']))}"
                     + (f" · {t['topic_who']}: {who}" if who else "") + "</div></li>")
    note = t["topics_note"].format(p=tp.get("n_objava", 0), a=tp.get("n_racuna", 0),
                                   d=time.strftime("%d.%m. %H:%M" if lang == "hr" else "%d %b %H:%M",
                                                   time.gmtime(tp.get("do") or 0)))
    return head + f"<p class=mnote>{esc(note)}</p><ol class=mtp>{''.join(items)}</ol>"


def assets_html(lang, m=None):
    t = T[lang]
    m = m if m is not None else mmood.load(public=True)
    pa = (m or {}).get("po_imovini") or {}
    trs = []
    for a in mmood.ASSETS:
        b = pa.get(a)
        if not b or not b["n"]:
            continue
        tone = {"good": "st-up", "bad": "st-dn"}.get(mmood.TONE.get(b["presuda"], ""), "")
        trs.append(f"<tr><td>{esc(ASSET[lang][a][:1].upper() + ASSET[lang][a][1:])}</td><td class=n>{b['n']}</td>"
                   f"<td class=n>{_pct_i((b['strane'] or {}).get('bik'))}</td>"
                   f"<td class=n>{_pct_i((b['strane'] or {}).get('medvjed'))}</td>"
                   f"<td><span class='{tone}'>{esc(_verdict_word(b['presuda'], lang))}</span></td></tr>")
    if not trs:
        return ""
    head = "".join(f"<th{' class=n' if 0 < j < 4 else ''}>{x}</th>" for j, x in enumerate(t["assets_cols"]))
    return (f"<h2 class=s id=assets>{t['assets_h']}</h2><p class=mnote>{esc(t['assets_note'].format(d=_date(m.get('t'), lang)))}"
            f"</p><div class=tw><table class=coins><thead><tr>{head}</tr></thead><tbody>{''.join(trs)}</tbody></table></div>")


HUB_PAGE = 100   # accounts on one page of the hub (16.11.: up to 800 accounts; a phone never gets them all at once)


def hub_pages(v):
    """How many pages the hub's account list has (the ranked accounts first, then the ones still collecting)."""
    return max(1, -(-(len(v["ranked"]) + len(v["few"])) // HUB_PAGE))


def _hub_path(lang, page):
    return T[lang]["hub"] + (f"/{page}" if page > 1 else "")


def hub(lang, page=1):
    """HTML of the hub, or None while the switch is off / before any data / past the last page. The account list is
    paged (HUB_PAGE a page: the ranked accounts in order, then the ones still collecting evidence); page 1 carries the
    mood, the topics, the index and the method, the next pages only their part of the list."""
    if not on():
        return None
    v = _view()
    if not v:
        return None
    from ui import public as P
    t = T[lang]
    base = os.environ.get("RENDER_EXTERNAL_URL", "").rstrip("/")
    all_ranked, all_few = v["ranked"], v["few"]
    total, pages = len(all_ranked) + len(all_few), hub_pages(v)
    if page < 1 or page > pages:
        return None
    p0, p1 = (page - 1) * HUB_PAGE, page * HUB_PAGE
    ranked = all_ranked[p0:p1]
    few = all_few[max(0, p0 - len(all_ranked)):max(0, p1 - len(all_ranked))]
    trs = []
    for k, r in enumerate(ranked, p0 + 1):
        g, e = r["integritet"], r["ekonomski"]
        lo, hi = r["wilson95"]
        gtxt = f"{g.get('naknadno_nedostupno') or 0} / {g.get('makro_izjava') or 0}"
        mline = t["m_line"].format(n=r["n_epizoda"], b=_pp(r["razlika"], lang), e=_pp(e.get("razlika"), lang), g=gtxt)
        trs.append(f"<tr><td class='mut mr-rk'>{k}</td><td class=mr-acc><a href=\"{t['prof']}{r['handle']}\">"
                   f"@{esc(r['handle'])}</a><span class=mcat>{esc(CAT[lang].get(r['category'] or '', ''))}</span></td>"
                   f"<td class='n mr-ep'>{r['n_epizoda']}</td><td class='n mr-hit'><b>{_pct(r['pogodak'])}</b> "
                   f"<span class=ci>{_ci(lo, hi)}</span></td><td class='n mr-bl'>{_pp(r['razlika'], lang)}</td>"
                   f"<td class='n mr-fo'>{_pp(e.get('razlika'), lang)}</td><td class='n mr-un'>{gtxt}</td>"
                   f"<td class=mr-st><span class=mo>{t['st_short']}: </span>{_stance(r, lang)}</td>"
                   f"<td class=mr-meta>{esc(mline)}</td></tr>")
    head = "".join(f"<th class='{'n' if 1 < j < 7 else ''}'>{h}</th>" for j, h in enumerate(t["cols"]))
    rank_html = (f"<p class=mnote>{esc(t['rank_note'].format(m=MIN_EP))}</p><div class=tw><table class=mr><thead>"
                 f"<tr>{head}</tr></thead><tbody>{''.join(trs)}</tbody></table></div>") if trs else \
        f"<p class=mnote>{esc(t['rank_none'].format(m=MIN_EP))}</p>"
    rank_html = (f"<h2 class=s id=rank>{t['rank_h']} · {len(all_ranked)}</h2>{rank_html}"
                 if trs or (page == 1 and not all_ranked) else "")
    ftrs = "".join(f"<tr><td><a href=\"{t['prof']}{r['handle']}\">@{esc(r['handle'])}</a><span class=mcat>"
                   f"{esc(CAT[lang].get(r['category'] or '', ''))}</span></td><td class=n>{r['n_epizoda']} / {MIN_EP}</td>"
                   f"<td>{_stance(r, lang)}</td></tr>" for r in few)
    fhead = "".join(f"<th{' class=n' if j == 1 else ''}>{h}</th>" for j, h in enumerate(t["few_cols"]))
    few_html = (f"<h2 class=s>{t['few_h']} · {len(all_few)}</h2><p class=mnote>{esc(t['few_note'].format(m=MIN_EP))}</p>"
                f"<div class=tw><table class=coins><thead><tr>{fhead}</tr></thead><tbody>{ftrs}</tbody></table></div>"
                if few else "")
    ix = v["index"]
    if ix and ix["n"]:
        tone = {"bull": "good", "bear": "bad"}.get(ix["lean"], "")
        idx = (f"<div class=mix><div class=mixw><i class={tone or 'nt'}></i>{LEAN[lang][ix['lean']]}</div><p>"
               f"{esc(t['idx'].format(d=_date(ix['day'], lang), v=_num(ix['v'], lang), n=ix['n']))}</p></div>")
    else:
        idx = f"<div class=mix><p>{esc(t['idx_none'])}</p></div>"
    how = "".join(f"<li>{esc(x.format(m=MIN_EP))}</li>" for x in t["how"])
    n = v["n"]
    kpi = (f"<div class=mk><span><b>{n}</b>{t['kpi'][0]}</span><span><b>{v['measured']}</b>{t['kpi'][1]}</span>"
           f"<span><b>{len(all_ranked)}</b>{t['kpi'][2]}</span><span>{t['kpi'][3]} <b style=margin:0>"
           f"{_date(v.get('ts'), lang)}</b></span></div>")
    a, b = p0 + 1, min(p1, total)
    pager = ""
    if pages > 1:   # "show more": the next HUB_PAGE accounts are one tap away, never in this page's HTML
        prev = (f"<a rel=prev href=\"{_hub_path(lang, page - 1)}{'#rank' if page == 2 else ''}\">"
                f"{esc(t['pg_prev'].format(k=HUB_PAGE))}</a>" if page > 1 else "")
        nxt = (f"<a rel=next href=\"{_hub_path(lang, page + 1)}\">"
               f"{esc(t['pg_next'].format(k=min(HUB_PAGE, total - p1)))}</a>" if page < pages else "")
        pager = (f"<nav class=mpg aria-label=\"{esc(t['pg_nav'])}\">{prev}<span>{esc(t['pg_range'].format(a=a, b=b, n=total))}"
                 f" · {esc(t['pg'].format(p=page, n=pages))}</span>{nxt}</nav>")
    url = f"{base}{_hub_path(lang, page)}"
    ld = {"@context": "https://schema.org", "@type": "CollectionPage", "name": t["h1"], "url": url,
          "inLanguage": lang, "description": t["desc"].format(n=n), "dateModified": _iso(v.get("ts")),
          "isPartOf": {"@type": "WebSite", "name": "MemeSonar", "url": base + P.L[lang]["home"]}}
    if ranked or few:   # this page's account pages (ranked first): all of them are indexable and in the sitemap
        ld["mainEntity"] = {"@type": "ItemList", "numberOfItems": total, "itemListElement": [
            {"@type": "ListItem", "position": k, "name": "@" + r["handle"], "url": f"{base}{t['prof']}{r['handle']}"}
            for k, r in enumerate(ranked + few, a)]}
    lds = _jsonld(ld)
    if page > 1:   # a light page: the heading, this part of the list, the way back and on
        body = (f"{CSS}<section class=ph1><div class=eyebrow>MemeSonar</div><h1>{t['h1']}</h1><p class=lead>"
                f"{esc(t['pg_range'].format(a=a, b=b, n=total))} · {esc(t['pg'].format(p=page, n=pages))}</p>"
                f"<p><a href=\"{t['hub']}\">{esc(t['pg_first'])}</a></p></section>{rank_html}{few_html}{pager}"
                f"<p class=mut style='font-size:13px'>{t['foot_note']}</p>")
        return P._shell(lang, t["pg_title"].format(p=page), t["pg_desc"].format(a=a, b=b, n=total),
                        _hub_path("en", page), _hub_path("hr", page), body, jsonld=lds)
    m = mmood.load(public=True)
    tp = mteme.load()
    known = {r["handle"].lower() for r in all_ranked + all_few}
    body = (f"{CSS}<section class=ph1><div class=eyebrow>MemeSonar</div><h1>{t['h1']}</h1><p class=lead>"
            f"{esc(t['lead'].format(n=n))}</p>{kpi}</section>"
            f"{mood_html(lang, m)}{topics_html(lang, tp, known)}{assets_html(lang, m)}"
            f"<h2 class=s>{t['idx_h']}</h2>{idx}{rank_html}{few_html}{pager}"
            f"<h2 class=s id={t['how_id']}>{t['how_h']}</h2><ul class=how>{how}</ul>"
            f"<div class=lock><p>{t['lock']}</p><a class='btn sm' href={P.L[lang]['home']}#pristup>{t['cta']}</a></div>"
            f"<p class=mut style='font-size:13px'>{t['foot_note']}</p>")
    if m and (m.get("okviri") or {}).get("24h", {}).get("n"):
        mt = m.get("t") or v.get("ts")
        ds = {"@context": "https://schema.org", "@type": "Dataset", "name": t["ds_name"], "description": t["ds_desc"],
              "url": f"{url}#mood", "inLanguage": lang, "isAccessibleForFree": True,
              "creator": {"@type": "Organization", "name": "MemeSonar", "url": base + P.L[lang]["home"]},
              "temporalCoverage": f"{time.strftime('%Y-%m-%d', time.gmtime(mt - 7 * 86400))}/"
                                  f"{time.strftime('%Y-%m-%d', time.gmtime(mt))}",
              "dateModified": _iso(m.get("ts")),
              "variableMeasured": [t["sides"]["bik"], t["sides"]["medvjed"], t["sides"]["neutralno"]]}
        lds += _jsonld(ds)
    return P._shell(lang, t["title"], t["desc"].format(n=n), "/macro-influencers", "/hr/makro-influenceri", body,
                    jsonld=lds)


def _episodes(h):
    return web.episodes(h, fresh=False, limit=40)


def coverage(h, lang, now=None):
    """One sentence of what is stored for the account (posts older than PUBLIC_DELAY_S only), or ""."""
    from makroinf import store
    con = store.ro()
    if con is None:
        return ""
    cut = int(now or time.time()) - PUBLIC_DELAY_S
    try:
        r = store.q(con, "SELECT COUNT(*), MIN(ts), MAX(ts) FROM tweets WHERE lower(handle) = lower(?) AND ts < ?",
                    (h, cut))
        by = store.q(con, "SELECT asset, COUNT(DISTINCT id) FROM calls WHERE lower(handle) = lower(?) AND ts < ? GROUP "
                          "BY asset ORDER BY 2 DESC", (h, cut))
        nc = store.q(con, "SELECT COUNT(DISTINCT id) FROM calls WHERE lower(handle) = lower(?) AND ts < ?", (h, cut))
    finally:
        con.close()
    if not r or not r[0][0]:
        return ""
    n, t0, t1 = r[0]
    a = ", ".join(f"{ASSET[lang].get(x, x)} {k}" for x, k in by[:6]) or "–"
    return T[lang]["cov"].format(p=n, c=(nc[0][0] if nc else 0) or 0, a=a, d0=_date(t0, lang), d1=_date(t1, lang))


def _memecoin_page(h):
    try:
        from ui import public as P
        return any(r["handle"].lower() == h.lower() for r in P.influencers())
    except Exception:  # noqa: BLE001
        return False


def profile(handle, lang):
    """HTML of one account page, or None (switch off, unknown handle)."""
    if not on() or not HANDLE.fullmatch(handle or ""):
        return None
    v = _view()
    if not v:
        return None
    me = next((r for r in v["ranked"] + v["few"] if r["handle"].lower() == handle.lower()), None)
    if not me:
        return None
    from ui import public as P
    t = T[lang]
    base = os.environ.get("RENDER_EXTERNAL_URL", "").rstrip("/")
    h = me["handle"]
    few = me["few"]
    lo, hi = me["wilson95"]
    e, g = me["ekonomski"], me["integritet"]
    p = (v["scores"].get(h) or {}).get("prediktivno") or {}
    bz = p.get("bazne") or {}
    best_k = max((k for k in bz if bz.get(k) is not None), key=lambda k: bz[k], default=None)
    e95 = e.get("razlika95") or [None, None]

    def chip(verdict):
        cls = "few" if verdict == "nedovoljno dokaza" else TONE.get(verdict, "")
        return f"<span class='vb {cls}'>{esc(VERDICT[lang].get(verdict, verdict or ''))}</span>" if verdict else ""
    cards = (f"<div class=card><span>{t['cards'][0]}</span><b>{'–' if few else _pct(me['pogodak'])}</b>"
             f"<p>{esc(t['c_pred'].format(ci=_ci(lo, hi), n=me['n_epizoda'], b=_pct(me['najbolja_bazna'])))}"
             f"</p>{chip(me['presuda'])}</div>"
             f"<div class=card><span>{t['cards'][1]}</span><b>{_pp(e.get('razlika'), lang)}</b>"
             f"<p>{esc(t['c_econ'].format(lo=_pp(e95[0], lang), hi=_pp(e95[1], lang), n=e.get('n') or 0))}</p>"
             f"{chip(e.get('presuda'))}</div>"
             f"<div class=card><span>{t['cards'][2]}</span><b>{g.get('naknadno_nedostupno') or 0}</b>"
             f"<p>{esc(t['c_integ'].format(m=g.get('makro_izjava') or 0, p=g.get('promocije') or 0))}</p></div>")
    hz = me.get("po_horizontu") or {}

    def ci(k):
        lo_, hi_ = ((hz.get(k) or {}).get("wilson95") or [None, None])[:2]
        return _ci(lo_, hi_)
    hz_rows = "".join(f"<tr><td>{esc(t['hz_names'][k])}</td><td class=n>{(hz.get(k) or {}).get('n', 0)}</td>"
                      f"<td class=n>{_pct((hz.get(k) or {}).get('pogodak'))}</td><td class=n>{ci(k)}</td></tr>"
                      for k in t["hz_names"])
    hz_head = "".join(f"<th{' class=n' if j else ''}>{x}</th>" for j, x in enumerate(t["hz_cols"]))
    eps, gone = _episodes(h)
    ep_rows = []
    for _eid, asset, dr, hzb, ts, res, fid in eps:
        parts = [(f"{hh}{NB}d: " if hh.isdigit() else "", rr) for hh, rr in
                 sorted((x.split(":", 1) for x in (res or "").split(",") if ":" in x),
                        key=lambda p_: int(p_[0]) if p_[0].isdigit() else 999)]
        res_html = "".join(f"<span class='rp {RTONE.get(rr, 'mut')}'>{esc(pre + RES[lang].get(rr, rr))}</span>"
                           for pre, rr in parts)
        hz_txt = {"7": "7 d", "30": "30 d", "oba": "7 + 30 d", "dugo": "> 60 d"}.get(hzb, hzb)
        post = (f"<span class=mut>{t['gone']}</span>" if gone.get(str(fid)) in GONE else
                f"<a href=\"https://x.com/{h}/status/{esc(str(fid))}\" target=_blank rel=\"nofollow noopener\">"
                f"{t['post']} ↗</a>")
        ep_rows.append(f"<tr><td class='mut nw'>{_date(ts, lang)}</td>"
                       f"<td>{esc(ASSET[lang].get(asset, asset))}: <b>{esc(DIR[lang].get(dr, dr))}</b></td>"
                       f"<td class=x>{esc(hz_txt)}</td><td>{res_html}</td><td class=nw>{post}</td></tr>")
    ep_head = "".join(f"<th{' class=x' if j == 2 else ''}>{x}</th>" for j, x in enumerate(t["ep_cols"]))
    ep_html = (f"<div class=tw><table class=mh><thead><tr>{ep_head}</tr></thead><tbody>{''.join(ep_rows)}</tbody></table></div>"
               if ep_rows else f"<p class=mut>{t['none']}</p>")
    a = v["accounts"].get(h) or {}
    name = a.get("name") if a.get("name") and a.get("name") != h else ""
    mc = (f"<p><a href=\"{P.L[lang]['prof']}{h}\">{esc(t['memecoin'].format(h=h))}</a></p>" if _memecoin_page(h) else "")
    rank = next((k for k, r in enumerate(v["ranked"], 1) if r is me), None)
    if few:
        lead = t["p_lead_few"].format(n=me["n_epizoda"], m=MIN_EP)
    else:
        lead = t["p_lead"].format(hit=_pct(me["pogodak"]), ci=_ci(lo, hi), n=me["n_epizoda"],
                                  b=_pct(bz.get(best_k)) if best_k else "–",
                                  bn=BASE[lang].get(best_k, "–"), v=VERDICT[lang].get(me["presuda"], me["presuda"]))
    meta = " · ".join(x for x in (esc(CAT[lang].get(me["category"] or "", "")),
                                  f"<a href=\"https://x.com/{esc(h)}\" target=_blank rel=\"nofollow noopener\">x.com/{esc(h)}</a>",
                                  esc(t["rank_of"].format(k=rank, n=len(v["ranked"]))) if rank else
                                  f"<span class='vb few'>{t['few']}</span>") if x)
    stance = esc(t["stance"].format(s=_stance_text(me, lang)))
    cov = coverage(h, lang)
    body = (f"{CSS}<section class=ph1><div class=crumb><a href={t['hub']}>{t['back']}</a></div><h1>@{esc(h)}</h1>"
            f"<p class=who>{(esc(name) + ' · ') if name else ''}{meta}</p><p class=plead>{esc(lead)}</p>"
            + (f"<p class=mut>{esc(cov)}</p>" if cov else "") + f"<p>{stance} "
            f"<a href=\"{t['hub']}#{t['how_id']}\" style=color:var(--acc)>{t['method']}</a></p></section>"
            f"<div class=mc3>{cards}</div><h2 class=s>{t['hz_h']}</h2><div class=tw><table class=mh><thead><tr>{hz_head}"
            f"</tr></thead><tbody>{hz_rows}</tbody></table></div><h2 class=s>{t['ep_h']}</h2>{ep_html}{mc}"
            f"<div class=lock><p>{t['lock']}</p><a class='btn sm' href={P.L[lang]['home']}#pristup>{t['cta']}</a></div>"
            f"<p class=mut style='font-size:13px'>{t['foot_note']}</p>")
    if few:
        title, desc = t["p_title_few"].format(h=h), t["p_desc_few"].format(h=h, n=me["n_epizoda"])
    else:
        title = t["p_title"].format(h=h, hit=_pct(me["pogodak"]))
        desc = t["p_desc"].format(h=h, n=me["n_epizoda"], hit=_pct(me["pogodak"]), lo=_pct(lo), hi=_pct(hi))
    ld = {"@context": "https://schema.org", "@type": "ProfilePage", "url": f"{base}{t['prof']}{h}", "inLanguage": lang,
          "dateModified": _iso(v.get("ts")),
          "mainEntity": {"@type": "Person", "name": name or h, "alternateName": "@" + h,
                         "sameAs": [f"https://x.com/{h}"]},
          "breadcrumb": {"@type": "BreadcrumbList", "itemListElement": [
              {"@type": "ListItem", "position": 1, "name": t["crumb_home"], "item": base + P.L[lang]["home"]},
              {"@type": "ListItem", "position": 2, "name": t["nav"][0], "item": base + t["hub"]},
              {"@type": "ListItem", "position": 3, "name": "@" + h, "item": f"{base}{t['prof']}{h}"}]}}
    # 15.11. navečer (the owner: "Neka Google sve indeksira"): indexable also below 10 episodes, the label says so
    return P._shell(lang, title, desc, f"/macro-influencer/{h}", f"/hr/makro-influencer/{h}", body, noindex=False,
                    jsonld=_jsonld(ld))


def match(path):
    """fn() -> HTML or None for a macro-influencer path, else None (not ours)."""
    if path in ("/macro-influencers", "/hr/makro-influenceri"):
        lang = "en" if path == "/macro-influencers" else "hr"
        return lambda: hub(lang)
    m = re.fullmatch(r"(/macro-influencers|/hr/makro-influenceri)/([2-9]|[1-9]\d{1,2})", path)
    if m:   # 16.11.: the next pages of the hub's account list (page 1 is the hub itself)
        lang, pg = ("en" if m.group(1) == "/macro-influencers" else "hr"), int(m.group(2))
        return lambda: hub(lang, pg)
    m = re.fullmatch(r"(/hr)?/(macro|makro)-influencer/([^/]+)", path)
    if m and ((m.group(1) is None) == (m.group(2) == "macro")):
        lang, h = ("hr" if m.group(1) else "en"), m.group(3)
        return lambda: profile(h, lang)
    return None


def urls():
    """Sitemap entries (en, hr, priority, lastmod): only while the switch is on; EVERY profile (15.11. navečer, the
    owner: "Neka Google sve indeksira"), the ranked ones with a higher priority; lastmod = the day of the newest score
    (the hub: of the newest score or topics), so it moves every day while the data is refreshed."""
    if not on():
        return []
    v = _view()
    if not v:
        return []
    ts = v.get("ts") or time.time()
    tp = mteme.load()
    mod = time.strftime("%Y-%m-%d", time.gmtime(ts))
    hub_mod = time.strftime("%Y-%m-%d", time.gmtime(max(ts, (tp or {}).get("ts") or 0)))
    out = [("/macro-influencers", "/hr/makro-influenceri", "0.7", hub_mod)]
    out += [(f"/macro-influencers/{p}", f"/hr/makro-influenceri/{p}", "0.3", mod) for p in range(2, hub_pages(v) + 1)]
    out += [(f"/macro-influencer/{r['handle']}", f"/hr/makro-influencer/{r['handle']}", "0.5", mod) for r in v["ranked"]]
    out += [(f"/macro-influencer/{r['handle']}", f"/hr/makro-influencer/{r['handle']}", "0.4", mod) for r in v["few"]]
    return out


def robots_lines():
    if not on():
        return ""
    return "Allow: /macro-influencer\nAllow: /hr/makro-influenc\n"


def nav_items(lang):
    """ui/sitenav plugin: the hub in the Influencers group, right after the influencer ranking (only while on)."""
    if not on():
        return []
    lang = "en" if lang == "en" else "hr"
    t = T[lang]
    after = "/influencers" if lang == "en" else "/hr/influenceri"
    return [("kols", t["hub"], t["nav"][0], t["nav"][1], after)]
