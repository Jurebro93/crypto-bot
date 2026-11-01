"""Content of the "Best crypto tools" topic cluster (/best-crypto-tools, /hr/najbolji-kripto-alati).

One pillar page plus seven categories. Every tool has the same fields in English and Croatian, so the comparison
table, the tool cards and both languages always describe the same thing.

Prices and fees were checked on 1 November 2026 on each vendor's own pricing page or docs (listed in SOURCES of each
category). Where a vendor does not publish a number we say so instead of guessing. Re-check before changing a number:
Nicholas compares these pages with the vendors' sites.

tool(): name, url, chains, en=(best_for, free, paid, what, [features], watch_out), hr=(same in Croatian), ours=True
marks MemeSonar itself (shown with an "our tool" badge, never ranked first in a table that compares paid tools).
"""
CHECKED = "2026-11-01"

RETRO = ("MemeSonar retrospective of 10,650 pump.fun tokens, October 2026",
         "MemeSonar retrospektiva 10.650 pump.fun tokena, listopad 2026.")
WALLETS = ("MemeSonar wallet tracker, snapshot of 30 October 2026",
           "MemeSonar praćenje novčanika, stanje 30. listopada 2026.")
PRICES = ("Vendors' pricing pages and docs, checked 1 November 2026",
          "Cjenici i dokumentacija proizvođača, provjereno 1. studenoga 2026.")


def tool(name, url, chains, en, hr, ours=False):
    keys = ("best", "free", "paid", "what", "feats", "watch")
    return {"name": name, "url": url, "chains": chains, "ours": ours,
            "en": dict(zip(keys, en)), "hr": dict(zip(keys, hr))}


OURS_WALLETS = tool(
    "MemeSonar", "/", "Solana",
    ("Finding the few wallets worth copying", "Invite only (free for members)", "–",
     "Our own tool. It scores Solana wallets on closed trades, labels snipers, bundlers, insiders and bots, and alerts "
     "when several good wallets buy the same token.",
     ["Score from closed trades, not screenshots", "Warning labels (sniper, bundler, insider, bot)",
      "Alert when 6+ tracked wallets converge on one token", "Rug filter on every token a wallet buys"],
     "Invite only, Solana only, and we are obviously biased: compare it with the others."),
    ("Pronalazak rijetkih novčanika koje vrijedi kopirati", "Samo uz pozivnicu (besplatno za članove)", "–",
     "Naš alat. Ocjenjuje Solana novčanike po zatvorenim tradeovima, označava snajpere, bundlere, insajdere i botove i "
     "javlja kad više dobrih novčanika kupi isti token.",
     ["Ocjena iz zatvorenih tradeova, ne iz screenshotova", "Oznake upozorenja (snajper, bundler, insajder, bot)",
      "Upozorenje kad 6+ praćenih novčanika kupi isti token", "Rug filter na svakom tokenu koji novčanik kupi"],
     "Samo uz pozivnicu, samo Solana, i naravno da smo pristrani: usporedi s ostalima."),
    ours=True)

# ─────────────────────────────────────────────────────────────────────────────────────────────── categories
CATS = []


def cat(key, en_slug, hr_slug, en, hr, tools, chart, sources, blog=(), terms=()):
    CATS.append({"key": key, "en_slug": en_slug, "hr_slug": hr_slug, "en": en, "hr": hr, "tools": tools,
                 "chart": chart, "sources": sources, "blog": blog, "terms": terms})


# 1 ── wallet trackers ─────────────────────────────────────────────────────────────────────────────────────────
cat("wallets", "wallet-trackers", "pracenje-novcanika",
    en=dict(
        tag="Wallet tracking", short="Wallet trackers",
        h1="Best crypto wallet trackers in 2026 (Solana and multi-chain)",
        title="Best crypto wallet trackers 2026: Cielo vs GMGN vs Nansen vs Arkham (prices) | MemeSonar",
        desc="We compared the best wallet trackers for Solana and other chains: free plans, paid plans, alerts and "
             "wallet limits. Cielo, GMGN, Nansen, Arkham, Kolscan and Axiom side by side.",
        kw=["best crypto wallet tracker", "solana wallet tracker", "wallet tracker", "smart money tracker"],
        tldr="For Telegram alerts on many wallets across chains, <b>Cielo</b> (free up to 250 wallets, Pro $59/month) "
             "is the most complete. For Solana meme coins, <b>GMGN</b> is free to use and shows wallet PnL. For "
             "research on who a wallet belongs to, <b>Arkham</b> (free) and <b>Nansen</b> (Pro $49/month yearly) have "
             "the best labels. The tracker matters less than your filter: of 469 'smart' wallets we tracked, 2 were "
             "worth copying.",
        intro="<p>A wallet tracker watches a list of blockchain addresses and tells you when they buy or sell. The good "
              "ones also tell you <b>who</b> the wallet is (an exchange, a fund, a known trader) and whether its past "
              "trades made money. We looked at the tools Solana traders actually use, read their pricing pages and "
              "docs, and compared what you get for free and what you pay for.</p>",
        chart_note="<p>Why a filter matters more than the app: this is what was left of 469 wallets from public "
                   "'smart money' lists after we scored their real trades.</p>",
        choose=["<b>Which chains?</b> Solana-only traders can live with GMGN, Kolscan or Axiom. If you also hold EVM "
                "tokens, Cielo, Nansen and Arkham cover both.",
                "<b>How many wallets?</b> Ten wallets fit every free plan. Hundreds of wallets need Cielo Pro or a "
                "trading terminal's built-in tracker.",
                "<b>Alerts where you look.</b> Cielo sends to Telegram and Discord; terminals show alerts in the app.",
                "<b>PnL from closed trades.</b> Prefer tools that show realised profit per wallet, not only balances.",
                "<b>Labels.</b> Nansen and Arkham label exchanges, funds and known entities; that stops you from "
                "copying an exchange hot wallet."],
        faq=[("What is the best free wallet tracker?",
              "For Solana, GMGN and Kolscan are free and show wallet PnL. For alerts across chains, Cielo's free plan "
              "follows up to 250 wallets (10 of them on Solana). Arkham's explorer and entity labels are free."),
             ("Is Nansen worth it?",
              "If you research who is behind wallets and want labelled smart money across many chains, yes: Pro is "
              "$49/month billed yearly or $69 monthly. For pure Solana meme coin alerts, free tools cover most needs."),
             ("Can I track a Solana wallet for free?",
              "Yes. Paste the address into Solscan or GMGN for its history, or add it to Cielo's free plan for "
              "Telegram alerts."),
             ("Are smart money wallets worth copying?",
              "Rarely. In our tracker, only 11 of 50 active wallets were profitable and 2 were worth copying; the rest "
              "were snipers, bots or simply lucky. See our guide to wallet tracking.")]),
    hr=dict(
        tag="Praćenje novčanika", short="Praćenje novčanika",
        h1="Najbolji alati za praćenje kripto novčanika 2026. (Solana i više mreža)",
        title="Najbolji alati za praćenje novčanika 2026: Cielo, GMGN, Nansen, Arkham (cijene) | MemeSonar",
        desc="Usporedili smo najbolje alate za praćenje novčanika za Solanu i druge mreže: besplatni i plaćeni "
             "planovi, upozorenja, broj novčanika. Cielo, GMGN, Nansen, Arkham, Kolscan i Axiom.",
        tldr="Za Telegram upozorenja na puno novčanika na više mreža najpotpuniji je <b>Cielo</b> (besplatno do 250 "
             "novčanika, Pro $59 mjesečno). Za Solana meme coine <b>GMGN</b> je besplatan i pokazuje dobit novčanika. "
             "Za istraživanje čiji je novčanik najbolje oznake imaju <b>Arkham</b> (besplatno) i <b>Nansen</b> (Pro "
             "$49 mjesečno uz godišnje plaćanje). Alat je manje važan od filtra: od 469 'pametnih' novčanika koje smo "
             "pratili, samo 2 je vrijedilo kopirati.",
        intro="<p>Alat za praćenje novčanika (wallet tracker) prati popis adresa na blockchainu i javlja ti kad kupe ili "
              "prodaju. Dobri alati kažu i <b>čiji</b> je novčanik (burza, fond, poznati trader) i je li zaradio na "
              "prošlim tradeovima. Pogledali smo alate koje Solana traderi stvarno koriste, pročitali njihove cjenike "
              "i dokumentaciju i usporedili što dobiješ besplatno, a što plaćaš.</p>",
        chart_note="<p>Zašto je filtar važniji od aplikacije: ovo je ostalo od 469 novčanika s javnih 'smart money' "
                   "popisa nakon što smo ocijenili njihove stvarne tradeove.</p>",
        choose=["<b>Koje mreže?</b> Ako trguješ samo na Solani, dovoljni su GMGN, Kolscan ili Axiom. Ako imaš i EVM "
                "tokene, Cielo, Nansen i Arkham pokrivaju oboje.",
                "<b>Koliko novčanika?</b> Deset novčanika stane u svaki besplatni plan. Za stotine treba Cielo Pro ili "
                "praćenje ugrađeno u trading terminal.",
                "<b>Upozorenja tamo gdje gledaš.</b> Cielo šalje na Telegram i Discord, terminali u aplikaciji.",
                "<b>Dobit iz zatvorenih tradeova.</b> Biraj alate koji pokazuju ostvarenu dobit novčanika, ne samo stanje.",
                "<b>Oznake.</b> Nansen i Arkham označavaju burze, fondove i poznate subjekte, pa nećeš kopirati "
                "novčanik burze."],
        faq=[("Koji je najbolji besplatni alat za praćenje novčanika?",
              "Za Solanu su GMGN i Kolscan besplatni i pokazuju dobit novčanika. Za upozorenja na više mreža Cielo "
              "besplatno prati do 250 novčanika (od toga 10 na Solani). Arkham explorer i oznake su besplatni."),
             ("Isplati li se Nansen?",
              "Ako istražuješ tko stoji iza novčanika i želiš označen smart money na puno mreža, da: Pro je $49 "
              "mjesečno uz godišnje plaćanje ili $69 mjesečno. Za upozorenja na Solana meme coine besplatni alati "
              "pokrivaju većinu potreba."),
             ("Mogu li besplatno pratiti Solana novčanik?",
              "Da. Zalijepi adresu u Solscan ili GMGN za povijest ili je dodaj u besplatni Cielo plan za upozorenja "
              "na Telegramu."),
             ("Vrijedi li kopirati smart money novčanike?",
              "Rijetko. U našem praćenju samo 11 od 50 aktivnih novčanika bilo je u plusu, a 2 je vrijedilo kopirati; "
              "ostalo su snajperi, botovi ili sretnici. Pogledaj naš vodič o praćenju novčanika.")]),
    tools=[
        tool("Cielo", "https://cielo.finance", "Solana + EVM chains",
             ("Telegram alerts on many wallets", "Up to 250 wallets (10 on Solana), 5 tokens, 5 lists",
              "Pro $59/mo (1,000 wallets), Whale $199/mo (10,000 wallets, API)",
              "A multi-chain wallet tracker built around fast alerts in Telegram and Discord, with a feed of what your "
              "wallets trade and their PnL.",
              ["Telegram and Discord bots", "Wallet PnL and trade feed", "Solana and EVM in one list",
               "Monthly, 6-month or yearly billing"],
              "Free plan allows only 10 Solana wallets."),
             ("Upozorenja na Telegramu za puno novčanika", "Do 250 novčanika (10 na Solani), 5 tokena, 5 popisa",
              "Pro $59/mj (1.000 novčanika), Whale $199/mj (10.000 novčanika, API)",
              "Praćenje novčanika na više mreža s brzim upozorenjima na Telegramu i Discordu, uz feed tradeova i dobit "
              "novčanika.",
              ["Telegram i Discord botovi", "Dobit i tradeovi novčanika", "Solana i EVM na jednom popisu",
               "Plaćanje mjesečno, na 6 mjeseci ili godišnje"],
              "Besplatni plan dopušta samo 10 Solana novčanika.")),
        tool("GMGN", "https://gmgn.ai", "Solana, Ethereum, Base, BNB Chain",
             ("Free Solana smart money research", "Free to browse; 1% fee only if you trade",
              "No subscription; 1% per trade",
              "A meme coin terminal with wallet PnL pages, smart money and KOL wallet lists, and one-click copy trading.",
              ["Wallet PnL, win rate and trade history", "Smart money and KOL wallet lists", "Copy trading built in",
               "Token security checks on each token"],
              "Trading through it costs 1% per trade; many traders research on GMGN and trade elsewhere."),
             ("Besplatno istraživanje smart moneyja na Solani", "Besplatno pregledavanje; 1% samo kad trguješ",
              "Bez pretplate; 1% po tradeu",
              "Terminal za meme coine sa stranicama dobiti novčanika, popisima smart money i KOL novčanika i copy "
              "tradingom na jedan klik.",
              ["Dobit, postotak pogodaka i povijest novčanika", "Popisi smart money i KOL novčanika",
               "Ugrađen copy trading", "Sigurnosna provjera svakog tokena"],
              "Trgovanje preko njega košta 1% po tradeu; mnogi istražuju na GMGN-u, a trguju drugdje.")),
        tool("Nansen", "https://www.nansen.ai", "Ethereum, Solana and 20+ chains",
             ("Labelled smart money across chains", "Free tier with basic labels and limited use",
              "Pro $49/mo billed yearly or $69/mo monthly",
              "An on-chain analytics platform with labels on hundreds of millions of addresses, smart money dashboards "
              "and alerts.",
              ["Smart money labels and dashboards", "Wallet profiler and alerts", "Token god mode (holders, flows)",
               "API on credits (sold separately)"],
              "Strongest on large tokens and funds; less useful for minute-by-minute meme coin trading."),
             ("Označeni smart money na više mreža", "Besplatna razina s osnovnim oznakama i ograničenjima",
              "Pro $49/mj uz godišnje ili $69/mj mjesečno plaćanje",
              "Platforma za on-chain analizu s oznakama na stotinama milijuna adresa, smart money pregledima i "
              "upozorenjima.",
              ["Smart money oznake i pregledi", "Profil novčanika i upozorenja", "Token god mode (holderi, tokovi)",
               "API na kredite (plaća se posebno)"],
              "Najjači na velikim tokenima i fondovima; manje koristan za trgovanje meme coinima iz minute u minutu.")),
        tool("Arkham", "https://intel.arkm.com", "Bitcoin, Ethereum, Solana and more",
             ("Finding out who owns a wallet", "Explorer, entity labels and visualiser are free",
              "No public price for API / enterprise",
              "An intelligence explorer that ties addresses to entities (exchanges, funds, people) and draws the "
              "money flows between them.",
              ["Entity labels and profiles", "Visual graph of transfers", "Alerts on wallets and entities",
               "Free core platform"],
              "Built for research, not for fast trading alerts on new tokens."),
             ("Otkriti čiji je novčanik", "Explorer, oznake subjekata i vizualizacija besplatni",
              "Nema javne cijene za API / enterprise",
              "Explorer koji povezuje adrese sa subjektima (burze, fondovi, osobe) i crta tokove novca među njima.",
              ["Oznake i profili subjekata", "Grafički prikaz transfera", "Upozorenja za novčanike i subjekte",
               "Osnovna platforma besplatna"],
              "Napravljen za istraživanje, ne za brza upozorenja na nove tokene.")),
        tool("Kolscan", "https://kolscan.io", "Solana",
             ("Seeing what known meme coin traders do", "Free", "–",
              "A free leaderboard of known Solana traders and influencers' wallets, ranked by realised profit.",
              ["Daily, weekly and monthly PnL leaderboard", "Trades of each known wallet", "No sign-up needed"],
              "A leaderboard, not an alert tool; the top of the list changes every week."),
             ("Vidjeti što rade poznati meme coin traderi", "Besplatno", "–",
              "Besplatna ljestvica novčanika poznatih Solana tradera i influencera, poredana po ostvarenoj dobiti.",
              ["Ljestvica dobiti po danu, tjednu i mjesecu", "Tradeovi svakog poznatog novčanika",
               "Bez registracije"],
              "Ljestvica, ne alat za upozorenja; vrh popisa se mijenja svaki tjedan.")),
        tool("Axiom", "https://axiom.trade", "Solana",
             ("Tracking wallets inside a trading terminal", "Free to use; fee only on trades",
              "1% per trade, 0.95% to 0.75% net after SOL cashback",
              "A Solana trading terminal with a built-in wallet tracker, so an alert and the buy button sit on the "
              "same screen.",
              ["Wallet tracker with live trade feed", "Buy and sell from the alert", "Cashback tiers by volume"],
              "Tracking is a side feature of a trading app; you pay only if you trade through it."),
             ("Praćenje novčanika unutar trading terminala", "Besplatno; naknada samo na trade",
              "1% po tradeu, neto 0,95% do 0,75% uz SOL povrat",
              "Solana trading terminal s ugrađenim praćenjem novčanika, pa su upozorenje i gumb za kupnju na istom "
              "ekranu.",
              ["Praćenje novčanika s tradeovima uživo", "Kupi i prodaj iz upozorenja", "Povrat naknade po volumenu"],
              "Praćenje je sporedna funkcija trading aplikacije; plaćaš samo ako preko nje trguješ.")),
        OURS_WALLETS,
    ],
    chart=dict(fmt="num", hl=(4,), source=WALLETS, rows=[
        (("Wallets collected", "Prikupljeni novčanici"), 469, ("public 'smart money' lists", "javni 'smart money' popisi")),
        (("Enough history to score", "Dovoljno povijesti za ocjenu"), 293, ("", "")),
        (("10+ closed trades", "10+ zatvorenih tradeova"), 50, ("enough to judge skill", "dovoljno za ocjenu vještine")),
        (("Profitable", "U plusu"), 11, ("after all trades", "nakon svih tradeova")),
        (("Worth copying", "Vrijedi kopirati"), 2, ("not a bot, sniper or insider", "nije bot, snajper ni insajder")),
    ], title=("From 469 'smart' wallets to 2 worth copying", "Od 469 'pametnih' novčanika do 2 koja vrijedi kopirati"),
        sub=("Wallets left after each filter", "Novčanici koji ostanu nakon svakog filtra")),
    sources=[("Cielo docs: plans", "https://docs.cielo.finance/wallet-tracking/subscribe"),
             ("Nansen docs: credits and pricing", "https://docs.nansen.ai/getting-started/credits"),
             ("GMGN docs: fees", "https://docs.gmgn.ai/index/gmgn-fees-settings"),
             ("Axiom docs: fees", "https://docs.axiom.trade/getting-started/fees/axiom-fees"),
             ("Arkham Intel", "https://intel.arkm.com"), ("Kolscan", "https://kolscan.io")],
    blog=("what-is-wallet-tracking", "bundles-and-snipers", "what-is-copy-trading"),
    terms=("smart-money", "crypto-wallet", "sniper-bot", "insider-wallet", "pnl"))


# 2 ── analysis tools ──────────────────────────────────────────────────────────────────────────────────────────
cat("analysis", "crypto-analysis-tools", "alati-za-analizu",
    en=dict(
        tag="Analysis", short="Analysis tools",
        h1="Best crypto analysis tools in 2026: charts, on-chain data and holder maps",
        title="Best crypto analysis tools 2026: DexScreener, Birdeye, Nansen, Dune, Glassnode, TradingView | MemeSonar",
        desc="The best tools for analysing crypto and Solana meme coins: DEX charts, on-chain analytics, holder maps "
             "and macro data. Free plans, paid plans and what each one is best at.",
        kw=["best crypto analysis tools", "best on chain analytics tools", "crypto charting tools", "dex screener"],
        tldr="Start free: <b>DexScreener</b> or <b>Birdeye</b> for every DEX chart, <b>Bubblemaps</b> for who holds a "
             "token, and <b>TradingView</b>'s free plan for indicators. Pay only when you need depth: <b>Nansen</b> "
             "(from $49/month) for labelled wallets, <b>Dune</b> (from $75/month) for your own queries, "
             "<b>Glassnode</b> (from $49/month) for Bitcoin and Ethereum cycle data.",
        intro="<p>\"Analysis\" means three different jobs: reading a price chart, reading the blockchain (who buys, "
              "who holds, where money flows) and reading the big market cycle. No single tool does all three well, "
              "so most traders combine a free chart, a free holder view and at most one paid data tool.</p>",
        chart_note="<p>Entry price of the cheapest paid plan, per month. DexScreener and Bubblemaps are free for "
                   "traders, so they are not on the chart.</p>",
        choose=["<b>Meme coins on Solana:</b> DexScreener or Birdeye for charts and new pairs, Bubblemaps for holder "
                "clusters, RugCheck before any buy.",
                "<b>Who is buying:</b> Nansen or Arkham labels; for Solana meme coins, GMGN's wallet pages are free.",
                "<b>Your own questions:</b> Dune lets you write SQL over blockchain data and share dashboards.",
                "<b>Bitcoin and Ethereum cycles:</b> Glassnode's on-chain indicators (exchange flows, holder cost basis).",
                "<b>Technical analysis:</b> TradingView, which also powers the charts inside many crypto apps."],
        faq=[("What is the best free crypto analysis tool?",
              "DexScreener: every DEX pair on every major chain, live charts, transactions and holders, no account "
              "needed. Birdeye is a close alternative with stronger Solana wallet data."),
             ("Is TradingView free?",
              "Yes, the Basic plan is free with 2 indicators per chart and 3 price alerts. Paid plans start at "
              "$12.95/month billed yearly."),
             ("Dune or Nansen?",
              "Dune if you want to build your own analysis (SQL, dashboards); Nansen if you want labelled wallets and "
              "ready-made smart money views."),
             ("Do I need Glassnode for meme coins?",
              "No. Glassnode is built for Bitcoin and Ethereum market cycles; it says little about a new Solana token.")]),
    hr=dict(
        tag="Analiza", short="Alati za analizu",
        h1="Najbolji alati za analizu kriptovaluta 2026: grafovi, on-chain podaci i mape holdera",
        title="Najbolji alati za kripto analizu 2026: DexScreener, Birdeye, Nansen, Dune, Glassnode | MemeSonar",
        desc="Najbolji alati za analizu kriptovaluta i Solana meme coina: DEX grafovi, on-chain analiza, mape holdera i "
             "makro podaci. Besplatni i plaćeni planovi i za što je koji najbolji.",
        tldr="Kreni besplatno: <b>DexScreener</b> ili <b>Birdeye</b> za graf svakog DEX para, <b>Bubblemaps</b> za to tko "
             "drži token i besplatni <b>TradingView</b> za indikatore. Plati tek kad trebaš dubinu: <b>Nansen</b> (od "
             "$49 mjesečno) za označene novčanike, <b>Dune</b> (od $75 mjesečno) za vlastite upite, <b>Glassnode</b> "
             "(od $49 mjesečno) za cikluse Bitcoina i Ethereuma.",
        intro="<p>\"Analiza\" su zapravo tri posla: čitanje grafa cijene, čitanje blockchaina (tko kupuje, tko drži, kamo "
              "ide novac) i čitanje velikog tržišnog ciklusa. Nijedan alat ne radi sva tri dobro, pa većina tradera "
              "kombinira besplatni graf, besplatni pregled holdera i najviše jedan plaćeni alat za podatke.</p>",
        chart_note="<p>Početna cijena najjeftinijeg plaćenog plana, mjesečno. DexScreener i Bubblemaps su besplatni "
                   "za tradere, pa nisu na grafu.</p>",
        choose=["<b>Meme coini na Solani:</b> DexScreener ili Birdeye za grafove i nove parove, Bubblemaps za grupe "
                "holdera, RugCheck prije svake kupnje.",
                "<b>Tko kupuje:</b> oznake Nansena ili Arkhama; za Solana meme coine besplatne su stranice novčanika "
                "na GMGN-u.",
                "<b>Vlastita pitanja:</b> Dune omogućuje SQL upite nad podacima s blockchaina i dijeljenje pregleda.",
                "<b>Ciklusi Bitcoina i Ethereuma:</b> on-chain indikatori Glassnodea (tokovi na burze, prosječna cijena "
                "holdera).",
                "<b>Tehnička analiza:</b> TradingView, na kojem rade i grafovi u mnogim kripto aplikacijama."],
        faq=[("Koji je najbolji besplatni alat za kripto analizu?",
              "DexScreener: svaki DEX par na svim većim mrežama, grafovi uživo, transakcije i holderi, bez računa. "
              "Birdeye je dobra alternativa s jačim podacima o Solana novčanicima."),
             ("Je li TradingView besplatan?",
              "Da, plan Basic je besplatan, s 2 indikatora po grafu i 3 upozorenja na cijenu. Plaćeni planovi počinju "
              "od $12,95 mjesečno uz godišnje plaćanje."),
             ("Dune ili Nansen?",
              "Dune ako želiš graditi vlastitu analizu (SQL, pregledi); Nansen ako želiš označene novčanike i gotove "
              "smart money preglede."),
             ("Trebam li Glassnode za meme coine?",
              "Ne. Glassnode je napravljen za tržišne cikluse Bitcoina i Ethereuma; o novom Solana tokenu ne kaže "
              "gotovo ništa.")]),
    tools=[
        tool("DexScreener", "https://dexscreener.com", "80+ chains incl. Solana",
             ("Free charts of every DEX pair", "Everything for traders; no account needed",
              "Projects pay for profile and boosts; traders pay nothing",
              "The default chart site for tokens that trade on decentralised exchanges, with new pairs, trending "
              "lists, transactions and holders.",
              ["Live charts for every pool", "New pairs and trending lists", "Transactions and top holders",
               "Free public API"],
              "'Trending' and boosted tokens are partly paid placements by projects."),
             ("Besplatni grafovi svakog DEX para", "Sve za tradere; bez računa",
              "Projekti plaćaju profil i boostove; traderi ne plaćaju ništa",
              "Glavna stranica s grafovima tokena kojima se trguje na decentraliziranim burzama: novi parovi, popisi "
              "u trendu, transakcije i holderi.",
              ["Grafovi uživo za svaki pool", "Novi parovi i trending popisi", "Transakcije i najveći holderi",
               "Besplatni javni API"],
              "'Trending' i boostani tokeni su dijelom plaćeno mjesto od strane projekata.")),
        tool("Birdeye", "https://birdeye.so", "Solana + major EVM chains",
             ("Solana token and wallet data", "Web app free", "Data API from $99/mo (Starter)",
              "A token explorer that started on Solana: charts, trader lists, wallet portfolio and PnL views, plus a "
              "paid data API.",
              ["Token charts and top traders", "Wallet portfolio and PnL", "Token security tab",
               "Data API with free 30k compute units"],
              "API plans are priced in compute units; check what your calls cost before you build on it."),
             ("Podaci o Solana tokenima i novčanicima", "Web aplikacija besplatna", "Data API od $99/mj (Starter)",
              "Explorer tokena koji je krenuo na Solani: grafovi, popisi tradera, portfelj i dobit novčanika te "
              "plaćeni API za podatke.",
              ["Grafovi tokena i najveći traderi", "Portfelj i dobit novčanika", "Kartica sigurnosti tokena",
               "Data API s besplatnih 30k compute jedinica"],
              "API planovi se naplaćuju u compute jedinicama; provjeri koliko koštaju tvoji pozivi.")),
        tool("Bubblemaps", "https://bubblemaps.io", "Solana, Ethereum, Base, BNB Chain and more",
             ("Seeing linked holders at a glance", "Basic maps free", "Pro features paid (no public price)",
              "Draws a token's top holders as bubbles and links the wallets that sent tokens to each other, which "
              "exposes clusters that look like many holders but are one team.",
              ["Holder bubble map", "Links between connected wallets", "Shows supply held by clusters"],
              "A map is a hint, not proof; exchanges and liquidity pools also show up as big bubbles."),
             ("Brzo vidjeti povezane holdere", "Osnovne mape besplatne", "Pro funkcije plaćene (nema javne cijene)",
              "Crta najveće holdere tokena kao mjehuriće i povezuje novčanike koji su jedni drugima slali tokene, pa se "
              "vide grupe koje izgledaju kao puno holdera, a zapravo su jedan tim.",
              ["Mapa holdera u mjehurićima", "Veze među povezanim novčanicima", "Koliko ponude drže grupe"],
              "Mapa je trag, ne dokaz; burze i likvidnosni poolovi su također veliki mjehurići.")),
        tool("TradingView", "https://www.tradingview.com", "All markets",
             ("Charts and technical indicators", "Basic: 1 chart per tab, 2 indicators, 3 price alerts",
              "Essential $12.95, Plus $29.95, Premium $59.95, Ultimate $199.95 per month (billed yearly)",
              "The charting platform most traders know, with drawing tools, thousands of community indicators and "
              "alerts, for crypto, stocks and forex.",
              ["Best-in-class charting", "Community scripts and indicators", "Alerts on price and indicators",
               "Many crypto exchanges connected"],
              "Covers big pairs well; brand-new meme coins appear only once a supported DEX feed lists them."),
             ("Grafovi i tehnički indikatori", "Basic: 1 graf po kartici, 2 indikatora, 3 upozorenja",
              "Essential $12,95, Plus $29,95, Premium $59,95, Ultimate $199,95 mjesečno (godišnje plaćanje)",
              "Platforma za grafove koju zna većina tradera, s alatima za crtanje, tisućama indikatora zajednice i "
              "upozorenjima, za kripto, dionice i forex.",
              ["Najbolji grafovi", "Skripte i indikatori zajednice", "Upozorenja na cijenu i indikatore",
               "Povezano s mnogo kripto burzi"],
              "Dobro pokriva velike parove; posve novi meme coini pojave se tek kad ih podrži DEX izvor.")),
        tool("Nansen", "https://www.nansen.ai", "Ethereum, Solana and 20+ chains",
             ("Labelled wallets and token flows", "Free tier with limits", "Pro $49/mo billed yearly, $69 monthly",
              "On-chain analytics with wallet labels, token holder breakdowns and smart money flows.",
              ["Token god mode", "Smart money inflows and outflows", "Wallet profiler", "AI assistant on Pro"],
              "Most valuable on established tokens with labelled holders."),
             ("Označeni novčanici i tokovi tokena", "Besplatna razina s ograničenjima",
              "Pro $49/mj godišnje, $69 mjesečno",
              "On-chain analiza s oznakama novčanika, raspodjelom holdera i tokovima smart moneyja.",
              ["Token god mode", "Ulazi i izlazi smart moneyja", "Profil novčanika", "AI asistent u Pro planu"],
              "Najkorisniji na etabliranim tokenima s označenim holderima.")),
        tool("Dune", "https://dune.com", "Most major chains incl. Solana",
             ("Building your own on-chain analysis", "Browse public dashboards",
              "Analyst from $75/mo, Plus $399/mo ($349 billed yearly)",
              "A SQL workspace over decoded blockchain data, with thousands of public dashboards made by analysts.",
              ["SQL over decoded chain data", "Public dashboards to fork", "API to export results",
               "Team seats on Plus"],
              "Dune changed its free plan in 2026; running your own queries may need a paid plan, check before "
              "you start."),
             ("Gradnja vlastite on-chain analize", "Pregled javnih dashboarda",
              "Analyst od $75/mj, Plus $399/mj ($349 godišnje)",
              "SQL radni prostor nad dekodiranim podacima s blockchaina, s tisućama javnih pregleda analitičara.",
              ["SQL nad podacima s mreže", "Javni pregledi za kopiranje", "API za izvoz rezultata",
               "Više korisnika u planu Plus"],
              "Dune je 2026. promijenio besplatni plan; vlastiti upiti možda traže plaćeni plan, provjeri prije.")),
        tool("Glassnode", "https://glassnode.com", "Bitcoin, Ethereum and majors",
             ("Bitcoin and Ethereum market cycles", "Limited free metrics",
              "Advanced $49/mo (yearly), Professional from $584/mo (yearly)",
              "On-chain market intelligence for the big coins: exchange flows, holder cost basis, profit taking and "
              "cycle indicators.",
              ["270+ on-chain metrics on Advanced", "10 alerts on Advanced", "Weekly research",
               "API only as a Professional add-on"],
              "Not built for small caps or meme coins."),
             ("Ciklusi Bitcoina i Ethereuma", "Ograničene besplatne metrike",
              "Advanced $49/mj (godišnje), Professional od $584/mj (godišnje)",
              "On-chain podaci o velikim kriptovalutama: tokovi na burze, prosječna cijena holdera, uzimanje dobiti i "
              "indikatori ciklusa.",
              ["270+ on-chain metrika u Advanced", "10 upozorenja u Advanced", "Tjedna istraživanja",
               "API samo kao dodatak Professional planu"],
              "Nije napravljen za male tokene ni meme coine.")),
    ],
    chart=dict(fmt="usd2", hl=None, source=PRICES, rows=[
        (("TradingView Essential", "TradingView Essential"), 12.95, ("billed yearly", "godišnje plaćanje")),
        (("Glassnode Advanced", "Glassnode Advanced"), 49, ("billed yearly", "godišnje plaćanje")),
        (("Nansen Pro", "Nansen Pro"), 49, ("$69 if paid monthly", "$69 uz mjesečno plaćanje")),
        (("Dune Analyst", "Dune Analyst"), 75, ("monthly", "mjesečno")),
        (("Birdeye API Starter", "Birdeye API Starter"), 99, ("data API, 3M compute units", "data API, 3M jedinica")),
    ], title=("Cheapest paid plan per tool", "Najjeftiniji plaćeni plan po alatu"),
        sub=("USD per month", "USD mjesečno")),
    sources=[("TradingView pricing", "https://www.tradingview.com/pricing/"),
             ("Glassnode pricing", "https://studio.glassnode.com/pricing"),
             ("Nansen docs: credits and pricing", "https://docs.nansen.ai/getting-started/credits"),
             ("Dune pricing FAQ", "https://docs.dune.com/learning/how-tos/pricing-faqs"),
             ("Birdeye Data Services pricing", "https://docs.birdeye.so/docs/pricing"),
             ("DexScreener API docs", "https://docs.dexscreener.com/api/reference"),
             ("Bubblemaps", "https://bubblemaps.io")],
    blog=("market-cap-liquidity-slippage", "how-to-trade-meme-coins", "how-to-spot-a-rug-pull"),
    terms=("market-cap", "liquidity", "trading-volume", "holders", "dex"))


# 3 ── trading terminals and bots ──────────────────────────────────────────────────────────────────────────────
cat("trading", "trading-bots", "trading-botovi",
    en=dict(
        tag="Trading", short="Trading bots and terminals",
        h1="Best Solana trading bots and terminals in 2026 (fees compared)",
        title="Best Solana trading bots 2026: Axiom vs Photon vs GMGN vs Trojan vs BonkBot (fees) | MemeSonar",
        desc="Fees and features of the most used Solana trading terminals and Telegram bots: Axiom, Photon, GMGN, "
             "Trojan, BonkBot and Jupiter. What a trade really costs and which one fits you.",
        kw=["best solana trading bot", "best crypto trading bot", "axiom vs photon", "solana trading terminal"],
        tldr="Almost every meme coin terminal and Telegram bot charges <b>about 1% on every buy and every sell</b>, so "
             "a round trip costs about 2% before network fees. <b>Axiom</b> is the most complete web terminal (0.95% "
             "to 0.75% net with cashback), <b>Trojan</b> the most complete Telegram bot (0.9% with a referral), and "
             "<b>Jupiter</b> the cheapest way to swap (0% on manual swaps).",
        intro="<p>Trading terminals and Telegram bots exist because buying a brand-new Solana token in a normal wallet "
              "is slow. They keep a hot wallet ready, show new tokens as they launch, and let you buy in one click "
              "with preset amounts, slippage and priority fees. The price is a fee on every trade, which adds up "
              "fast if you trade small amounts often.</p>",
        chart_note="<p>The platform fee you pay on each buy and each sell (before Solana network fees, priority fees "
                   "and the pool's own fee). On a $100 buy and a $100 sell, 1% is $2 in total.</p>",
        choose=["<b>Web or Telegram?</b> Web terminals (Axiom, Photon, GMGN) show more on screen; Telegram bots "
                "(Trojan, BonkBot) work anywhere from your phone.",
                "<b>Count the fee twice.</b> You pay on the buy and the sell. Ten $50 round trips a day at 1% cost "
                "$10 a day.",
                "<b>Bigger, older tokens:</b> swap on Jupiter or in your wallet; the 1% terminal fee buys you nothing "
                "there.",
                "<b>Keep the bot wallet small.</b> Terminals and bots hold your key in a hot wallet. Move profits out "
                "to your own wallet regularly.",
                "<b>Status changes fast.</b> BullX reportedly stopped trading on its app on 1 June 2026, so we left "
                "it out. Check a tool still works before you deposit."],
        faq=[("What is the cheapest Solana trading bot?",
              "For plain swaps, Jupiter: manual swaps have no Jupiter fee and Ultra charges 0% to 0.5%. Among meme coin "
              "terminals, Axiom's cashback brings the net fee to 0.95% to 0.75%, and Trojan charges 0.9% with a "
              "referral."),
             ("Are Telegram trading bots safe?",
              "They are custodial in practice: the bot holds the private key of your trading wallet. Use a separate "
              "wallet with a small balance and withdraw profits."),
             ("Axiom or Photon?",
              "Both are web terminals at about 1%. Axiom has more built in (wallet tracker, cashback tiers); Photon is "
              "simpler and fast."),
             ("Do trading bots make you profitable?",
              "No. They make you faster. Speed helps only if your entries are good; most new tokens never double.")]),
    hr=dict(
        tag="Trgovanje", short="Trading botovi i terminali",
        h1="Najbolji Solana trading botovi i terminali 2026. (usporedba naknada)",
        title="Najbolji Solana trading botovi 2026: Axiom, Photon, GMGN, Trojan, BonkBot (naknade) | MemeSonar",
        desc="Naknade i funkcije najkorištenijih Solana trading terminala i Telegram botova: Axiom, Photon, GMGN, "
             "Trojan, BonkBot i Jupiter. Koliko trade stvarno košta i koji ti odgovara.",
        tldr="Gotovo svaki terminal za meme coine i Telegram bot naplaćuje <b>oko 1% na svaku kupnju i svaku "
             "prodaju</b>, pa kupnja i prodaja zajedno koštaju oko 2% prije mrežnih naknada. <b>Axiom</b> je "
             "najpotpuniji web terminal (neto 0,95% do 0,75% uz povrat), <b>Trojan</b> najpotpuniji Telegram bot (0,9% "
             "uz referral), a <b>Jupiter</b> najjeftiniji način zamjene (0% na ručne swapove).",
        intro="<p>Trading terminali i Telegram botovi postoje jer je kupnja posve novog Solana tokena u običnom "
              "novčaniku spora. Drže spreman 'vrući' novčanik, pokazuju nove tokene čim se lansiraju i omogućuju "
              "kupnju jednim klikom s unaprijed zadanim iznosom, slippageom i prioritetnom naknadom. Cijena je naknada "
              "na svaki trade, koja brzo naraste ako često trguješ malim iznosima.</p>",
        chart_note="<p>Naknada platforme na svaku kupnju i svaku prodaju (prije Solana mrežne naknade, prioritetne "
                   "naknade i naknade poola). Na kupnju od $100 i prodaju od $100, 1% je ukupno $2.</p>",
        choose=["<b>Web ili Telegram?</b> Web terminali (Axiom, Photon, GMGN) pokazuju više na ekranu; Telegram botovi "
                "(Trojan, BonkBot) rade s mobitela bilo gdje.",
                "<b>Naknadu računaj dvaput.</b> Plaćaš na kupnju i na prodaju. Deset kupnji i prodaja od $50 dnevno uz "
                "1% košta $10 dnevno.",
                "<b>Veći, stariji tokeni:</b> mijenjaj na Jupiteru ili u novčaniku; naknada terminala od 1% tamo ti ne "
                "donosi ništa.",
                "<b>Novčanik bota drži malim.</b> Terminali i botovi drže tvoj ključ u vrućem novčaniku. Redovito "
                "prebacuj dobit u svoj novčanik.",
                "<b>Stanje se brzo mijenja.</b> BullX je prema izvještajima prestao s trgovanjem u aplikaciji 1. lipnja "
                "2026., pa ga nismo uvrstili. Provjeri radi li alat prije uplate."],
        faq=[("Koji je najjeftiniji Solana trading bot?",
              "Za obične zamjene Jupiter: ručni swapovi nemaju Jupiterovu naknadu, a Ultra naplaćuje 0% do 0,5%. Među "
              "terminalima za meme coine Axiomov povrat spušta neto naknadu na 0,95% do 0,75%, a Trojan uz referral "
              "naplaćuje 0,9%."),
             ("Jesu li Telegram trading botovi sigurni?",
              "U praksi su skrbnički: bot drži privatni ključ tvog trading novčanika. Koristi poseban novčanik s malim "
              "iznosom i podiži dobit."),
             ("Axiom ili Photon?",
              "Oba su web terminali s oko 1%. Axiom ima više ugrađenog (praćenje novčanika, razine povrata); Photon "
              "je jednostavniji i brz."),
             ("Hoće li mi bot donijeti zaradu?",
              "Ne. Čini te bržim. Brzina pomaže samo ako su ulazi dobri; većina novih tokena nikad se ne udvostruči.")]),
    tools=[
        tool("Axiom", "https://axiom.trade", "Solana (+ Hyperliquid perps)",
             ("All-in-one web terminal", "No subscription", "1% per trade; 0.95% to 0.75% net with SOL cashback tiers",
              "A web trading terminal for Solana meme coins with a live feed of new and migrating tokens, wallet "
              "tracker, limit orders and cashback by volume.",
              ["New token feed (Pulse)", "Wallet tracker", "Limit orders, take profit and stop loss",
               "SOL cashback up to 0.25% of volume"],
              "Your trading wallet is held by the app; keep only what you trade."),
             ("Sve-u-jednom web terminal", "Bez pretplate", "1% po tradeu; neto 0,95% do 0,75% uz SOL povrat",
              "Web terminal za Solana meme coine s feedom novih tokena i tokena koji migriraju, praćenjem novčanika, "
              "limit nalozima i povratom po volumenu.",
              ["Feed novih tokena (Pulse)", "Praćenje novčanika", "Limit nalozi, take profit i stop loss",
               "SOL povrat do 0,25% volumena"],
              "Trading novčanik drži aplikacija; drži u njemu samo ono čime trguješ.")),
        tool("Photon", "https://photon-sol.tinyastro.io", "Solana (+ EVM versions)",
             ("Fast, simple web terminal", "No subscription", "1% on each buy and sell",
              "One of the first Solana web terminals: new pairs, trending tokens and one-click buys with presets.",
              ["New pairs feed", "Presets for amount, slippage and fee", "Limit orders", "Multi-wallet"],
              "Same 1% as the others with fewer extras."),
             ("Brz, jednostavan web terminal", "Bez pretplate", "1% na svaku kupnju i prodaju",
              "Jedan od prvih Solana web terminala: novi parovi, tokeni u trendu i kupnja jednim klikom.",
              ["Feed novih parova", "Zadane postavke iznosa, slippagea i naknade", "Limit nalozi", "Više novčanika"],
              "Isti 1% kao drugi, s manje dodataka.")),
        tool("GMGN", "https://gmgn.ai", "Solana, Ethereum, Base, BNB Chain",
             ("Research and copy trading in one", "Free to browse", "1% per trade",
              "A terminal built around discovery: smart money, KOL wallets, token security checks and copy trading.",
              ["Smart money and KOL lists", "Copy trading", "Token security checks", "Multi-chain"],
              "Copy trades land 1 to 3 seconds after the copied wallet, which matters on fast tokens."),
             ("Istraživanje i copy trading na jednom mjestu", "Pregledavanje besplatno", "1% po tradeu",
              "Terminal izgrađen oko otkrivanja: smart money, KOL novčanici, sigurnosne provjere tokena i copy trading.",
              ["Smart money i KOL popisi", "Copy trading", "Sigurnosna provjera tokena", "Više mreža"],
              "Kopirani tradeovi kasne 1 do 3 sekunde za novčanikom, što je bitno na brzim tokenima.")),
        tool("Trojan", "https://trojan.com", "Solana",
             ("Full-featured Telegram bot", "No subscription", "1% per trade, 0.9% with a referral link",
              "The most used Solana Telegram bot: buy and sell from chat, limit orders, DCA, copy trading and sniping.",
              ["Trading from Telegram", "Copy trading and limit orders", "DCA orders", "Web version too"],
              "Telegram-first interface takes some getting used to."),
             ("Telegram bot s najviše funkcija", "Bez pretplate", "1% po tradeu, 0,9% uz referral link",
              "Najkorišteniji Solana Telegram bot: kupnja i prodaja iz chata, limit nalozi, DCA, copy trading i "
              "sniping.",
              ["Trgovanje iz Telegrama", "Copy trading i limit nalozi", "DCA nalozi", "Postoji i web verzija"],
              "Sučelje u Telegramu traži malo navikavanja.")),
        tool("BonkBot", "https://bonkbot.io", "Solana",
             ("Simplest Telegram bot", "No subscription", "1% per trade",
              "A minimal Telegram bot for quick Solana swaps. Its fee is used to buy BONK, part of which is burned.",
              ["Very simple to start", "Fast swaps from chat", "Fee buys back BONK"],
              "Few advanced features (no copy trading)."),
             ("Najjednostavniji Telegram bot", "Bez pretplate", "1% po tradeu",
              "Minimalni Telegram bot za brze Solana zamjene. Naknadom kupuje BONK, a dio spaljuje.",
              ["Vrlo jednostavan početak", "Brze zamjene iz chata", "Naknada otkupljuje BONK"],
              "Malo naprednih funkcija (nema copy tradinga).")),
        tool("Jupiter", "https://jup.ag", "Solana",
             ("Cheapest swaps, limit and recurring orders", "Manual swaps: no Jupiter fee",
              "Ultra 0% to 0.5%; limit orders 0.1% (v1) or 0.03% to 0.1% + routing (v2)",
              "Solana's main DEX aggregator: finds the best route across pools. Also limit orders, recurring (DCA) "
              "orders and a mobile app.",
              ["Best price routing", "Limit and recurring orders", "Works from any Solana wallet", "Mobile app"],
              "Not a sniping tool; for brand-new tokens terminals are faster."),
             ("Najjeftinije zamjene, limit i ponavljajući nalozi", "Ručni swapovi: bez Jupiterove naknade",
              "Ultra 0% do 0,5%; limit nalozi 0,1% (v1) ili 0,03% do 0,1% + rutiranje (v2)",
              "Glavni Solana DEX agregator: nalazi najbolju rutu kroz poolove. Ima i limit naloge, ponavljajuće (DCA) "
              "naloge i aplikaciju za mobitel.",
              ["Najbolja cijena kroz rutiranje", "Limit i ponavljajući nalozi", "Radi iz bilo kojeg Solana novčanika",
               "Aplikacija za mobitel"],
              "Nije alat za sniping; za posve nove tokene terminali su brži.")),
    ],
    chart=dict(fmt="pct2", hl=None, source=PRICES, rows=[
        (("Jupiter manual swap", "Jupiter ručni swap"), 0, ("no Jupiter fee", "bez Jupiterove naknade")),
        (("Jupiter Ultra (max)", "Jupiter Ultra (najviše)"), 0.5, ("0% to 0.5% by pair", "0% do 0,5% ovisno o paru")),
        (("Axiom, top cashback tier", "Axiom, najviša razina povrata"), 0.75, ("Champion tier", "razina Champion")),
        (("Trojan with referral", "Trojan uz referral"), 0.9, ("1% without", "1% bez")),
        (("Axiom, first tier", "Axiom, prva razina"), 0.95, ("1% minus 0.05% cashback", "1% minus 0,05% povrata")),
        (("Photon", "Photon"), 1, ("each buy and sell", "svaka kupnja i prodaja")),
        (("GMGN", "GMGN"), 1, ("", "")),
        (("BonkBot", "BonkBot"), 1, ("", "")),
    ], title=("Platform fee per trade", "Naknada platforme po tradeu"),
        sub=("% of each buy and each sell", "% svake kupnje i svake prodaje")),
    sources=[("Axiom docs: fees", "https://docs.axiom.trade/getting-started/fees/axiom-fees"),
             ("GMGN docs: fees", "https://docs.gmgn.ai/index/gmgn-fees-settings"),
             ("Jupiter docs: swap fees", "https://docs.jup.ag/user-docs/trade/swap/fees"),
             ("Trojan", "https://trojan.com"), ("BonkBot", "https://bonkbot.io"),
             ("Photon", "https://photon-sol.tinyastro.io")],
    blog=("how-to-trade-meme-coins", "what-is-pump-fun", "market-cap-liquidity-slippage"),
    terms=("trading-bot", "slippage", "take-profit", "stop-loss", "sniper-bot", "dca"))


# 4 ── wallets and storage ─────────────────────────────────────────────────────────────────────────────────────
cat("storage", "crypto-wallets", "kripto-novcanici",
    en=dict(
        tag="Wallets and storage", short="Wallets and cold storage",
        h1="Best crypto wallets for Solana in 2026: hot, hardware and multisig",
        title="Best Solana wallets 2026: Phantom, Solflare, Backpack, Ledger, Trezor, Tangem, Squads | MemeSonar",
        desc="Where to keep your crypto safely: the best Solana wallets (Phantom, Solflare, Backpack), hardware "
             "wallets (Ledger, Trezor, Tangem) and multisig (Squads), with prices and swap fees.",
        kw=["best solana wallet", "best crypto wallet", "best hardware wallet", "cold wallet"],
        tldr="Use two wallets: a <b>hot wallet</b> for trading (Phantom, Solflare or Backpack, all free) and "
             "<b>cold storage</b> for what you keep (a hardware wallet from about $50: Trezor Safe 3, Tangem cards, "
             "Ledger Nano). Shared or larger funds belong in a <b>multisig</b> like Squads, where several people must "
             "approve every transfer.",
        intro="<p>A crypto wallet does not hold coins; it holds the key that controls them. Whoever has the key (or "
              "the 12/24-word recovery phrase) owns the money. That makes storage a simple question: how many places "
              "can your key leak from? A browser wallet is convenient but online; a hardware wallet keeps the key on "
              "a device that never touches the internet.</p>",
        chart_note="<p>Hardware wallet prices on the makers' own stores (US dollars, before tax and shipping; prices "
                   "change with promotions).</p>",
        choose=["<b>Never type your recovery phrase into a website, bot or chat.</b> No real support team will ask "
                "for it. MemeSonar never asks for it either.",
                "<b>Split hot and cold.</b> Keep a trading amount in Phantom or Solflare; move the rest to a hardware "
                "wallet.",
                "<b>Connect hardware to your hot app.</b> Phantom, Solflare and Backpack can use a Ledger as signer, so "
                "you keep the app and get cold keys.",
                "<b>Shared money needs a multisig.</b> For a club, team or project treasury, Squads requires e.g. 2 of 3 "
                "members to approve.",
                "<b>Swap fees differ.</b> Phantom charges 0.85% on in-app swaps; swapping via Jupiter is cheaper."],
        faq=[("What is the best wallet for Solana?",
              "Phantom for ease of use, Solflare for Solana-focused features and hardware support, Backpack if you "
              "also use its exchange. All three are free."),
             ("Do I need a hardware wallet?",
              "If you hold more than you would be fine losing, yes. A Trezor Safe 3 ($50) or Tangem 2-card set "
              "($54.90) protects you from most hacks that empty browser wallets."),
             ("Does Ledger support Solana?",
              "Yes. Install the Solana app on the device and connect it to Phantom, Solflare or Ledger Live."),
             ("What is a multisig wallet?",
              "A wallet that needs several approvals for each transaction, e.g. 2 of 3 people. On Solana the standard "
              "is Squads; it charges a one-time deployment fee and Solana network fees.")]),
    hr=dict(
        tag="Novčanici i čuvanje", short="Novčanici i hladno čuvanje",
        h1="Najbolji kripto novčanici za Solanu 2026: vrući, hardverski i multisig",
        title="Najbolji Solana novčanici 2026: Phantom, Solflare, Backpack, Ledger, Trezor, Tangem | MemeSonar",
        desc="Gdje sigurno čuvati kripto: najbolji Solana novčanici (Phantom, Solflare, Backpack), hardverski novčanici "
             "(Ledger, Trezor, Tangem) i multisig (Squads), s cijenama i naknadama za zamjenu.",
        tldr="Koristi dva novčanika: <b>vrući novčanik</b> za trgovanje (Phantom, Solflare ili Backpack, svi besplatni) "
             "i <b>hladno čuvanje</b> za ono što držiš (hardverski novčanik od oko $50: Trezor Safe 3, Tangem kartice, "
             "Ledger Nano). Zajednički ili veći novac ide u <b>multisig</b> poput Squadsa, gdje više ljudi mora odobriti "
             "svaki prijenos.",
        intro="<p>Kripto novčanik ne drži novčiće; drži ključ koji njima upravlja. Tko ima ključ (ili frazu za oporavak "
              "od 12/24 riječi), taj ima novac. Zato je čuvanje jednostavno pitanje: s koliko mjesta može procuriti "
              "tvoj ključ? Novčanik u pregledniku je praktičan, ali online; hardverski novčanik drži ključ na uređaju "
              "koji nikad ne dira internet.</p>",
        chart_note="<p>Cijene hardverskih novčanika u službenim trgovinama proizvođača (američki dolari, bez poreza i "
                   "dostave; mijenjaju se s akcijama).</p>",
        choose=["<b>Frazu za oporavak nikad ne upisuj na web, u bota ili chat.</b> Nijedna prava podrška je neće "
                "tražiti. Ni MemeSonar je nikad ne traži.",
                "<b>Odvoji vruće i hladno.</b> Iznos za trgovanje drži u Phantomu ili Solflareu, ostalo prebaci na "
                "hardverski novčanik.",
                "<b>Spoji hardver s aplikacijom.</b> Phantom, Solflare i Backpack mogu koristiti Ledger za potpis, pa "
                "zadržiš aplikaciju i dobiješ hladne ključeve.",
                "<b>Zajednički novac traži multisig.</b> Za klub, tim ili blagajnu projekta Squads traži npr. odobrenje "
                "2 od 3 člana.",
                "<b>Naknade za zamjenu se razlikuju.</b> Phantom naplaćuje 0,85% na zamjene u aplikaciji; preko "
                "Jupitera je jeftinije."],
        faq=[("Koji je najbolji novčanik za Solanu?",
              "Phantom za jednostavnost, Solflare za Solana funkcije i podršku hardveru, Backpack ako koristiš i "
              "njegovu burzu. Sva tri su besplatna."),
             ("Trebam li hardverski novčanik?",
              "Ako držiš više nego što bi mogao mirno izgubiti, da. Trezor Safe 3 ($50) ili Tangem set od 2 kartice "
              "($54,90) štite od većine hakova koji prazne novčanike u pregledniku."),
             ("Podržava li Ledger Solanu?",
              "Da. Instaliraj Solana aplikaciju na uređaj i spoji ga s Phantomom, Solflareom ili Ledger Liveom."),
             ("Što je multisig novčanik?",
              "Novčanik kojem za svaku transakciju treba više odobrenja, npr. 2 od 3 osobe. Na Solani je standard "
              "Squads; naplaćuje jednokratnu naknadu za izradu i Solana mrežne naknade.")]),
    tools=[
        tool("Phantom", "https://phantom.com", "Solana, Ethereum, Bitcoin, Base and more",
             ("Easiest everyday wallet", "Free", "0.85% fee on in-app swaps",
              "The most popular Solana wallet: browser extension and mobile app with swaps, staking, NFTs and Ledger "
              "support.",
              ["Browser and mobile", "Ledger hardware support", "Built-in swaps and staking",
               "Warnings on suspicious transactions"],
              "In-app swaps cost 0.85%; for big swaps use Jupiter."),
             ("Najjednostavniji novčanik za svaki dan", "Besplatno", "0,85% naknade na zamjene u aplikaciji",
              "Najpopularniji Solana novčanik: dodatak za preglednik i aplikacija za mobitel sa zamjenama, stakingom, "
              "NFT-ovima i podrškom za Ledger.",
              ["Preglednik i mobitel", "Podrška za Ledger", "Ugrađene zamjene i staking",
               "Upozorenja na sumnjive transakcije"],
              "Zamjene u aplikaciji koštaju 0,85%; za velike zamjene koristi Jupiter.")),
        tool("Solflare", "https://solflare.com", "Solana",
             ("Solana-only power users", "Free", "Swap fee shown in each quote",
              "A Solana-only wallet with strong staking, Ledger and Keystone hardware support, and a clear transaction "
              "preview.",
              ["Solana focused", "Ledger and Keystone support", "Staking built in", "Transaction simulation"],
              "Only Solana; you need a second wallet for other chains."),
             ("Napredni korisnici samo na Solani", "Besplatno", "Naknada za zamjenu vidi se u svakoj ponudi",
              "Novčanik samo za Solanu s dobrim stakingom, podrškom za Ledger i Keystone hardver i jasnim pregledom "
              "transakcije.",
              ["Usmjeren na Solanu", "Podrška za Ledger i Keystone", "Ugrađen staking", "Simulacija transakcije"],
              "Samo Solana; za druge mreže treba drugi novčanik.")),
        tool("Backpack", "https://backpack.app", "Solana, Ethereum and more",
             ("Wallet plus exchange account", "Free", "Says no wallet-level swap fee on Solana",
              "A multi-chain wallet from the team behind the Backpack exchange, with swaps and a simple interface.",
              ["Multi-chain", "Swaps in the wallet", "Links to the Backpack exchange"],
              "Fee claim is Backpack's own; confirm in the quote before swapping."),
             ("Novčanik uz račun na burzi", "Besplatno", "Kaže da nema naknade novčanika na Solana zamjene",
              "Novčanik za više mreža od tima burze Backpack, sa zamjenama i jednostavnim sučeljem.",
              ["Više mreža", "Zamjene u novčaniku", "Povezan s burzom Backpack"],
              "Tvrdnja o naknadi je Backpackova; provjeri u ponudi prije zamjene.")),
        tool("Trezor Safe 3 / Safe 5", "https://trezor.io", "Bitcoin, Ethereum, Solana and more",
             ("Cheapest serious cold storage", "–", "Safe 3 $50, Safe 5 $109 (trezor.io)",
              "Open-source hardware wallets with a secure element; Safe 5 adds a colour touchscreen.",
              ["Open-source firmware", "Secure element chip", "Bitcoin-only editions available",
               "Works with Trezor Suite and many wallets"],
              "Solana use goes through Trezor Suite or compatible wallets; check the app you want supports it."),
             ("Najjeftinije ozbiljno hladno čuvanje", "–", "Safe 3 $50, Safe 5 $109 (trezor.io)",
              "Hardverski novčanici otvorenog koda sa sigurnosnim čipom; Safe 5 ima zaslon u boji na dodir.",
              ["Firmware otvorenog koda", "Sigurnosni čip", "Postoje Bitcoin-only izdanja",
               "Radi s Trezor Suiteom i mnogim novčanicima"],
              "Solana ide preko Trezor Suitea ili kompatibilnih novčanika; provjeri podržava li ga tvoja aplikacija.")),
        tool("Ledger", "https://www.ledger.com", "5,000+ assets incl. Solana",
             ("Widest app and coin support", "–",
              "Nano S Plus from about $69, Nano Gen5 $179, Flex $249, Stax $399",
              "The best-known hardware wallets, supported as a signer by Phantom, Solflare and Backpack.",
              ["Signer for Phantom, Solflare, Backpack", "Ledger Live app", "Bluetooth on newer models",
               "Large coin support"],
              "Firmware is partly closed; the optional Recover service is paid and controversial."),
             ("Najšira podrška aplikacija i kriptovaluta", "–",
              "Nano S Plus od oko $69, Nano Gen5 $179, Flex $249, Stax $399",
              "Najpoznatiji hardverski novčanici, podržani kao potpisnik u Phantomu, Solflareu i Backpacku.",
              ["Potpisnik za Phantom, Solflare, Backpack", "Aplikacija Ledger Live", "Bluetooth na novijim modelima",
               "Velika podrška kriptovalutama"],
              "Firmware je dijelom zatvoren; dodatna usluga Recover se plaća i kontroverzna je.")),
        tool("Tangem", "https://tangem.com", "Bitcoin, Ethereum, Solana and many more",
             ("Cold storage on a card", "–", "2 cards $54.90, 3 cards $69.90, Ring $160",
              "NFC cards that act as hardware wallets: tap the card on your phone to sign. Backup cards replace the "
              "paper phrase.",
              ["No cable or battery", "Backup on extra cards", "Mobile app with swaps", "Optional seed phrase"],
              "Phone only; if you lose all cards and had no seed phrase, funds are gone."),
             ("Hladno čuvanje na kartici", "–", "2 kartice $54,90, 3 kartice $69,90, prsten $160",
              "NFC kartice koje rade kao hardverski novčanik: prisloniš karticu na mobitel i potpišeš. Rezervne "
              "kartice zamjenjuju papirnatu frazu.",
              ["Bez kabela i baterije", "Rezerva na dodatnim karticama", "Aplikacija sa zamjenama",
               "Fraza za oporavak po želji"],
              "Samo mobitel; ako izgubiš sve kartice bez fraze, novac je izgubljen.")),
        tool("Squads", "https://squads.so", "Solana",
             ("Shared and treasury funds (multisig)", "Protocol is free to use",
              "0.1 SOL deployment fee, 0.25% on limit orders, optional Business plan $49/mo",
              "Solana's standard multisig: a shared account where a set number of members must approve each "
              "transaction. Used by many Solana projects for treasuries.",
              ["M-of-N approvals", "Works with hardware wallets as members", "Spending limits", "Audited"],
              "Every approval is a Solana transaction, so network fees are a bit higher than a normal wallet."),
             ("Zajednički novac i blagajne (multisig)", "Protokol je besplatan",
              "0,1 SOL za izradu, 0,25% na limit naloge, po želji Business plan $49/mj",
              "Standardni multisig na Solani: zajednički račun gdje zadani broj članova mora odobriti svaku "
              "transakciju. Mnogi Solana projekti tako čuvaju blagajnu.",
              ["Odobrenja M od N", "Članovi mogu biti hardverski novčanici", "Ograničenja potrošnje", "Auditiran"],
              "Svako odobrenje je Solana transakcija, pa su mrežne naknade nešto veće nego u običnom novčaniku.")),
    ],
    chart=dict(fmt="usd2", hl=None, source=PRICES, rows=[
        (("Trezor Safe 3", "Trezor Safe 3"), 50, ("trezor.io", "trezor.io")),
        (("Tangem, 2 cards", "Tangem, 2 kartice"), 54.90, ("tangem.com", "tangem.com")),
        (("Ledger Nano S Plus", "Ledger Nano S Plus"), 69, ("about $69 to $79 by promotion", "oko $69 do $79 ovisno o akciji")),
        (("Trezor Safe 5", "Trezor Safe 5"), 109, ("touchscreen", "zaslon na dodir")),
        (("Ledger Nano Gen5", "Ledger Nano Gen5"), 179, ("", "")),
        (("Ledger Flex", "Ledger Flex"), 249, ("E Ink touchscreen", "E Ink zaslon na dodir")),
        (("Ledger Stax", "Ledger Stax"), 399, ("", "")),
    ], title=("Hardware wallet prices", "Cijene hardverskih novčanika"), sub=("USD, makers' stores", "USD, trgovine proizvođača")),
    sources=[("Trezor Safe 3", "https://trezor.io/trezor-safe-3"), ("Trezor Safe 5", "https://trezor.io/trezor-safe-5"),
             ("Tangem pricing", "https://tangem.com/en/pricing/"),
             ("Ledger hardware wallet comparison", "https://shop.ledger.com/pages/hardware-wallets-comparison"),
             ("Squads docs: costs", "https://docs.squads.so/main/frequently-asked-questions/costs-of-using-squads"),
             ("Phantom", "https://phantom.com"), ("Solflare", "https://solflare.com"),
             ("Backpack", "https://backpack.app")],
    blog=("how-to-spot-a-rug-pull", "what-is-pump-fun", "how-to-trade-meme-coins"),
    terms=("crypto-wallet", "hardware-wallet", "multisig", "contract-address", "dex", "cex"))


# 5 ── rug checkers ────────────────────────────────────────────────────────────────────────────────────────────
cat("rug", "rug-checkers", "provjera-ruga",
    en=dict(
        tag="Rug check", short="Rug checkers",
        h1="Best rug checkers for Solana tokens in 2026",
        title="Best rug checker 2026: RugCheck vs Solsniffer vs Bubblemaps vs GoPlus (Solana) | MemeSonar",
        desc="Free tools that check a Solana token before you buy: RugCheck, Solsniffer, Bubblemaps, GoPlus and Token "
             "Sniffer. What each one checks, what they miss, and the checks our data says matter most.",
        kw=["rug checker", "solana rug checker", "rugcheck", "rug check", "token scanner"],
        tldr="Use <b>RugCheck</b> (free) on every Solana token: it shows mint and freeze authority, liquidity and top "
             "holders in seconds. Add <b>Bubblemaps</b> to see whether the top holders are one team, and "
             "<b>Solsniffer</b> for a second score. No scanner sees the creator's history, which in our data was the "
             "strongest warning: tokens from creators with 20+ earlier launches doubled 1.4% of the time.",
        intro="<p>A rug checker reads a token's contract and holders and flags the usual tricks: the creator can still "
              "mint new tokens, can freeze your wallet, holds most of the supply, or the liquidity is tiny or not "
              "locked. All the tools below are free for single checks. They catch the obvious rugs; the quiet ones "
              "need context they don't show.</p>",
        chart_note="<p>What a contract scanner can't see: the creator's track record. Share of tokens that later "
                   "doubled, by how many tokens the same wallet had launched before.</p>",
        choose=["<b>Solana tokens:</b> RugCheck and Solsniffer are built for Solana; Token Sniffer and De.Fi are mostly "
                "for EVM chains.",
                "<b>Read the reasons, not only the score.</b> 'Mint authority on' or 'freeze authority on' is a hard no; "
                "'low holders' on a 5-minute-old token is normal.",
                "<b>Check holders as a group.</b> Ten wallets funded from one source are one holder. Bubblemaps shows that.",
                "<b>Look at the creator.</b> Open the creator's wallet on Solscan: many earlier tokens that died is the "
                "biggest red flag in our data.",
                "<b>Use an API if you scan many tokens.</b> RugCheck and GoPlus have APIs for bots and dashboards."],
        faq=[("Is RugCheck free?",
              "Yes. Paste any Solana token address at rugcheck.xyz for a risk report; it also has a public API."),
             ("What does a rug checker check?",
              "Mint and freeze authority, liquidity size and whether LP tokens are burned or locked, top holder share, "
              "and known risky patterns. Better ones also show insider and linked wallets."),
             ("Can a token pass a rug check and still rug?",
              "Yes. A creator can sell their supply slowly, or a group of linked wallets can dump together. Contract "
              "checks catch mechanics, not intentions; that is why creator history and holder clusters matter."),
             ("What is the best rug checker for Solana?",
              "RugCheck for the contract report, Bubblemaps for holder clusters. Use both; they answer different "
              "questions.")]),
    hr=dict(
        tag="Provjera ruga", short="Provjera ruga",
        h1="Najbolji alati za provjeru ruga na Solana tokenima 2026.",
        title="Najbolji rug checker 2026: RugCheck, Solsniffer, Bubblemaps, GoPlus (Solana) | MemeSonar",
        desc="Besplatni alati koji provjere Solana token prije kupnje: RugCheck, Solsniffer, Bubblemaps, GoPlus i Token "
             "Sniffer. Što koji provjerava, što propušta i koje su provjere prema našim podacima najvažnije.",
        tldr="Koristi <b>RugCheck</b> (besplatan) na svakom Solana tokenu: u par sekundi pokaže mint i freeze ovlast, "
             "likvidnost i najveće holdere. Dodaj <b>Bubblemaps</b> da vidiš jesu li najveći holderi jedan tim i "
             "<b>Solsniffer</b> za drugu ocjenu. Nijedan skener ne vidi povijest kreatora, a to je u našim podacima "
             "najjače upozorenje: tokeni kreatora s 20+ ranijih lansiranja udvostručili su se u 1,4% slučajeva.",
        intro="<p>Rug checker čita ugovor tokena i holdere i označava uobičajene trikove: kreator još može kovati nove "
              "tokene, može zamrznuti tvoj novčanik, drži većinu ponude, ili je likvidnost mala ili nije zaključana. "
              "Svi alati ispod besplatni su za pojedinačne provjere. Hvataju očite rugove; tihi traže kontekst koji "
              "ne pokazuju.</p>",
        chart_note="<p>Što skener ugovora ne vidi: povijest kreatora. Udio tokena koji su se kasnije udvostručili, "
                   "prema tome koliko je tokena isti novčanik lansirao prije.</p>",
        choose=["<b>Solana tokeni:</b> RugCheck i Solsniffer su napravljeni za Solanu; Token Sniffer i De.Fi su uglavnom "
                "za EVM mreže.",
                "<b>Čitaj razloge, ne samo ocjenu.</b> 'Mint authority on' ili 'freeze authority on' je sigurno ne; "
                "'malo holdera' na tokenu starom 5 minuta je normalno.",
                "<b>Gledaj holdere kao grupu.</b> Deset novčanika financiranih iz istog izvora je jedan holder. "
                "Bubblemaps to pokaže.",
                "<b>Pogledaj kreatora.</b> Otvori kreatorov novčanik na Solscanu: puno ranijih tokena koji su umrli je "
                "najveća crvena zastavica u našim podacima.",
                "<b>Za puno tokena koristi API.</b> RugCheck i GoPlus imaju API za botove i preglede."],
        faq=[("Je li RugCheck besplatan?",
              "Da. Zalijepi adresu bilo kojeg Solana tokena na rugcheck.xyz i dobiješ izvještaj o riziku; ima i javni API."),
             ("Što provjerava rug checker?",
              "Mint i freeze ovlast, veličinu likvidnosti i jesu li LP tokeni spaljeni ili zaključani, udio najvećih "
              "holdera i poznate rizične obrasce. Bolji pokazuju i insajdere i povezane novčanike."),
             ("Može li token proći provjeru i ipak biti rug?",
              "Da. Kreator može prodavati polako, ili grupa povezanih novčanika može prodati zajedno. Provjera ugovora "
              "hvata mehaniku, ne namjeru; zato su važni povijest kreatora i grupe holdera."),
             ("Koji je najbolji rug checker za Solanu?",
              "RugCheck za izvještaj o ugovoru, Bubblemaps za grupe holdera. Koristi oba; odgovaraju na različita "
              "pitanja.")]),
    tools=[
        tool("RugCheck", "https://rugcheck.xyz", "Solana",
             ("Fast contract and holder report", "Free, including a public API", "–",
              "The most used Solana token scanner: risk score with reasons, authorities, liquidity and LP status, top "
              "holders and insider networks.",
              ["Mint and freeze authority", "Liquidity and LP lock/burn", "Top holders and insiders",
               "Public API"],
              "A good score is not a guarantee; read the listed risks."),
             ("Brz izvještaj o ugovoru i holderima", "Besplatno, uključujući javni API", "–",
              "Najkorišteniji Solana skener tokena: ocjena rizika s razlozima, ovlasti, likvidnost i stanje LP-a, "
              "najveći holderi i mreže insajdera.",
              ["Mint i freeze ovlast", "Likvidnost i zaključan/spaljen LP", "Najveći holderi i insajderi",
               "Javni API"],
              "Dobra ocjena nije jamstvo; pročitaj navedene rizike.")),
        tool("Solsniffer", "https://solsniffer.com", "Solana",
             ("A second opinion score", "Free checks", "Paid extras (no public price)",
              "A Solana scanner that turns 20+ indicators into a 0 to 100 safety score.",
              ["Score from 20+ indicators", "Authority and liquidity checks", "Holder concentration"],
              "Scores differ between scanners; when they disagree, read why."),
             ("Druga ocjena", "Besplatne provjere", "Plaćeni dodaci (nema javne cijene)",
              "Solana skener koji 20+ pokazatelja pretvara u sigurnosnu ocjenu od 0 do 100.",
              ["Ocjena iz 20+ pokazatelja", "Provjera ovlasti i likvidnosti", "Koncentracija holdera"],
              "Ocjene se razlikuju među skenerima; kad se ne slažu, pročitaj zašto.")),
        tool("Bubblemaps", "https://bubblemaps.io", "Solana, Ethereum, Base, BNB Chain and more",
             ("Seeing if holders are one team", "Basic maps free", "Pro features paid (no public price)",
              "A visual map of the top holders and the transfers between them, which exposes bundles and clusters.",
              ["Holder bubble map", "Linked wallet clusters", "Share of supply per cluster"],
              "Exchanges and pools appear as big bubbles too; check what a bubble is."),
             ("Vidjeti jesu li holderi jedan tim", "Osnovne mape besplatne", "Pro funkcije plaćene (nema javne cijene)",
              "Vizualna mapa najvećih holdera i prijenosa među njima, koja otkriva bundleove i grupe.",
              ["Mapa holdera u mjehurićima", "Grupe povezanih novčanika", "Udio ponude po grupi"],
              "Burze i poolovi su također veliki mjehurići; provjeri što je koji.")),
        tool("GoPlus Security", "https://gopluslabs.io", "EVM chains + Solana (beta)",
             ("Developers and multi-chain checks", "Free web checks and API tier", "Paid API plans for volume",
              "A security data provider whose token API is built into many wallets and bots; Solana token checks are "
              "in beta.",
              ["Token security API", "Honeypot and tax checks on EVM", "Solana SPL and Token-2022 checks (beta)",
               "Transaction simulation"],
              "Solana coverage is newer than its EVM coverage."),
             ("Developeri i provjere na više mreža", "Besplatne web provjere i API razina",
              "Plaćeni API planovi za veći volumen",
              "Pružatelj sigurnosnih podataka čiji je token API ugrađen u mnoge novčanike i botove; provjere Solana "
              "tokena su u beti.",
              ["Token security API", "Provjera honeypota i poreza na EVM", "Provjera Solana SPL i Token-2022 (beta)",
               "Simulacija transakcije"],
              "Pokrivenost Solane je novija od EVM pokrivenosti.")),
        tool("Token Sniffer", "https://tokensniffer.com", "Ethereum, BNB Chain, Base and other EVM chains",
             ("EVM tokens (honeypots, taxes)", "Free", "Enterprise API",
              "An automated scanner for EVM tokens that flags honeypots, high taxes, copied contracts and liquidity "
              "problems.",
              ["Honeypot and tax detection", "Similar-contract detection", "Liquidity checks"],
              "Built for EVM; for Solana use RugCheck."),
             ("EVM tokeni (honeypoti, porezi)", "Besplatno", "Enterprise API",
              "Automatski skener EVM tokena koji označava honeypote, visoke poreze, kopirane ugovore i probleme s "
              "likvidnošću.",
              ["Otkrivanje honeypota i poreza", "Otkrivanje sličnih ugovora", "Provjera likvidnosti"],
              "Napravljen za EVM; za Solanu koristi RugCheck.")),
        tool("MemeSonar rug filter", "/", "Solana",
             ("Automatic check before every alert", "Invite only (free for members)", "–",
              "Our own filter. Every token we show is checked for authorities, real liquidity in a known pool, fake "
              "pools, creator history and bundled supply, and rugged tokens are dropped from the app.",
              ["Rejects mint/freeze authority on", "Liquidity at least $10k in a real pool",
               "Creator's earlier launches", "Learns rug profiles daily"],
              "Our tool, invite only, Solana only."),
             ("Automatska provjera prije svakog signala", "Samo uz pozivnicu (besplatno za članove)", "–",
              "Naš filtar. Svaki token koji pokažemo provjeren je na ovlasti, stvarnu likvidnost u poznatom poolu, "
              "lažne poolove, povijest kreatora i bundleanu ponudu, a rugani tokeni se izbacuju iz aplikacije.",
              ["Odbija uključenu mint/freeze ovlast", "Likvidnost najmanje $10k u pravom poolu",
               "Ranija lansiranja kreatora", "Svaki dan uči profile rugova"],
              "Naš alat, samo uz pozivnicu, samo Solana."), ours=True),
    ],
    chart=dict(fmt="pct", hl=(3,), source=RETRO, rows=[
        (("First token from this wallet", "Prvi token tog novčanika"), 16.8, ("2,598 tokens", "2.598 tokena")),
        (("1-5 earlier tokens", "1-5 ranijih tokena"), 9.2, ("769 tokens", "769 tokena")),
        (("6-20 earlier tokens", "6-20 ranijih tokena"), 3.8, ("764 tokens", "764 tokena")),
        (("More than 20 earlier tokens", "Više od 20 ranijih tokena"), 1.4, ("1,528 tokens", "1.528 tokena")),
    ], title=("Tokens that later doubled, by the creator's earlier launches",
              "Tokeni koji su se kasnije udvostručili, prema ranijim lansiranjima kreatora"),
        sub=("Measured 15 minutes after launch", "Mjereno 15 minuta nakon lansiranja")),
    sources=[("RugCheck", "https://rugcheck.xyz"), ("Solsniffer", "https://solsniffer.com"),
             ("Bubblemaps", "https://bubblemaps.io"), ("GoPlus docs", "https://docs.gopluslabs.io/"),
             ("Token Sniffer", "https://tokensniffer.com")],
    blog=("how-to-spot-a-rug-pull", "bundles-and-snipers", "what-is-pump-fun"),
    terms=("rug-checker", "rug-pull", "mint-authority", "liquidity", "holders", "bundler", "dev-wallet"))


# 6 ── APIs ────────────────────────────────────────────────────────────────────────────────────────────────────
cat("api", "crypto-apis", "kripto-api",
    en=dict(
        tag="APIs", short="Crypto APIs",
        h1="Best crypto and Solana APIs in 2026: RPC, token data and prices",
        title="Best crypto APIs 2026: Helius vs QuickNode vs Birdeye vs CoinGecko vs DexScreener (pricing) | MemeSonar",
        desc="The best APIs for building crypto bots and dashboards: Solana RPC (Helius, QuickNode), token and DEX "
             "data (Birdeye, DexScreener, Solana Tracker) and prices (CoinGecko). Free tiers and plans compared.",
        kw=["best crypto api", "solana api", "solana rpc", "crypto price api", "dexscreener api"],
        tldr="For Solana RPC and webhooks, <b>Helius</b> (free 1M credits, Developer $49/month) is the default; "
             "<b>QuickNode</b> (Build $49/month) if you need many chains. For token data start with the free "
             "<b>DexScreener API</b>, then <b>Birdeye</b> (from $99) or <b>Solana Tracker</b> (from €50). For prices of "
             "listed coins, <b>CoinGecko</b> (free demo, Basic $35/month). This is the stack MemeSonar itself runs on.",
        intro="<p>If you build anything on crypto data, a trading bot, an alert channel, a dashboard, you need two "
              "kinds of API: an <b>RPC node</b> to read the blockchain and send transactions, and a <b>data API</b> "
              "that has already turned raw transactions into prices, pools, holders and trades. We run MemeSonar on "
              "these APIs every day, so this page also tells you what we use and where the free tiers stopped "
              "working for us.</p>",
        chart_note="<p>Monthly price of the first paid plan. Credits are not comparable between vendors (each counts "
                   "calls differently), so compare the price, then test your own calls on the free tier.</p>",
        choose=["<b>Solana-only?</b> Helius has the best Solana extras: webhooks, parsed transactions, DAS for tokens "
                "and NFTs.",
                "<b>Many chains?</b> QuickNode covers dozens of chains on one account.",
                "<b>Token prices and pools for new tokens:</b> DexScreener's free API, Birdeye, or Solana Tracker.",
                "<b>Listed coins (BTC, SOL, big meme coins):</b> CoinGecko's API.",
                "<b>Cloud servers get blocked.</b> Some free APIs block datacenter IPs; we saw GeckoTerminal fail from "
                "our cloud host. Test from where your bot runs."],
        faq=[("What is the best Solana API?",
              "Helius for RPC, webhooks and parsed transactions; its free plan gives 1M credits and 10 requests per "
              "second. Add a data API (DexScreener free, Birdeye or Solana Tracker) for prices and pools."),
             ("Is the DexScreener API free?",
              "Yes, no key needed, with rate limits of roughly 60 to 300 requests per minute depending on the endpoint."),
             ("Is the CoinGecko API free?",
              "There is a free Demo plan with 10,000 calls a month. Paid plans start at $35/month (Basic, 100,000 calls)."),
             ("What does MemeSonar use?",
              "Helius (Developer plan) for wallets and transactions, DexScreener for pools and price snapshots, Jupiter "
              "for swap quotes, plus our own database. Every number on our pages comes from that pipeline.")]),
    hr=dict(
        tag="API", short="Kripto API-ji",
        h1="Najbolji kripto i Solana API-ji 2026: RPC, podaci o tokenima i cijene",
        title="Najbolji kripto API 2026: Helius, QuickNode, Birdeye, CoinGecko, DexScreener (cijene) | MemeSonar",
        desc="Najbolji API-ji za kripto botove i preglede: Solana RPC (Helius, QuickNode), podaci o tokenima i "
             "DEX-ovima (Birdeye, DexScreener, Solana Tracker) i cijene (CoinGecko). Besplatne razine i planovi.",
        tldr="Za Solana RPC i webhookove standard je <b>Helius</b> (besplatno 1M kredita, Developer $49 mjesečno); "
             "<b>QuickNode</b> (Build $49 mjesečno) ako trebaš puno mreža. Za podatke o tokenima kreni s besplatnim "
             "<b>DexScreener API-jem</b>, zatim <b>Birdeye</b> (od $99) ili <b>Solana Tracker</b> (od €50). Za cijene "
             "listanih kriptovaluta <b>CoinGecko</b> (besplatni demo, Basic $35 mjesečno). Na tome radi i sam MemeSonar.",
        intro="<p>Ako gradiš bilo što na kripto podacima, trading bota, kanal s upozorenjima, pregled, trebaju ti dvije "
              "vrste API-ja: <b>RPC čvor</b> za čitanje blockchaina i slanje transakcija, i <b>API za podatke</b> koji "
              "je sirove transakcije već pretvorio u cijene, poolove, holdere i tradeove. MemeSonar svaki dan radi na "
              "ovim API-jima, pa ova stranica kaže i što koristimo i gdje su nam besplatne razine prestale "
              "biti dovoljne.</p>",
        chart_note="<p>Mjesečna cijena prvog plaćenog plana. Krediti se ne mogu uspoređivati među pružateljima (svaki "
                   "drukčije broji pozive), pa usporedi cijenu, a zatim isprobaj svoje pozive na besplatnoj razini.</p>",
        choose=["<b>Samo Solana?</b> Helius ima najbolje Solana dodatke: webhookove, raščlanjene transakcije, DAS za "
                "tokene i NFT-ove.",
                "<b>Puno mreža?</b> QuickNode pokriva desetke mreža na jednom računu.",
                "<b>Cijene i poolovi novih tokena:</b> besplatni DexScreener API, Birdeye ili Solana Tracker.",
                "<b>Listane kriptovalute (BTC, SOL, veliki meme coini):</b> CoinGecko API.",
                "<b>Cloud serveri budu blokirani.</b> Neki besplatni API-ji blokiraju IP-jeve podatkovnih centara; "
                "GeckoTerminal nam nije radio s cloud servera. Testiraj s mjesta gdje ti bot radi."],
        faq=[("Koji je najbolji Solana API?",
              "Helius za RPC, webhookove i raščlanjene transakcije; besplatni plan daje 1M kredita i 10 zahtjeva u "
              "sekundi. Dodaj API za podatke (DexScreener besplatno, Birdeye ili Solana Tracker) za cijene i poolove."),
             ("Je li DexScreener API besplatan?",
              "Da, bez ključa, s ograničenjem od otprilike 60 do 300 zahtjeva u minuti, ovisno o endpointu."),
             ("Je li CoinGecko API besplatan?",
              "Postoji besplatni Demo plan s 10.000 poziva mjesečno. Plaćeni planovi počinju od $35 mjesečno (Basic, "
              "100.000 poziva)."),
             ("Što koristi MemeSonar?",
              "Helius (Developer plan) za novčanike i transakcije, DexScreener za poolove i snimke cijena, Jupiter za "
              "ponude zamjene, plus vlastitu bazu. Svaki broj na našim stranicama dolazi iz tog sustava.")]),
    tools=[
        tool("Helius", "https://www.helius.dev", "Solana",
             ("Solana RPC, webhooks, parsed data", "1M credits/month, 10 requests/s",
              "Developer $49 (10M credits, 50 req/s), Business $499, Professional $999",
              "The leading Solana-only RPC provider, with webhooks, enhanced (parsed) transactions, the DAS API for "
              "tokens and NFTs, and LaserStream streaming.",
              ["RPC with staked connections on paid plans", "Webhooks on wallet activity", "Parsed transaction history",
               "Extra credits $5 per million"],
              "Credits go fast with history queries; we watch usage daily."),
             ("Solana RPC, webhookovi, raščlanjeni podaci", "1M kredita mjesečno, 10 zahtjeva/s",
              "Developer $49 (10M kredita, 50 zaht./s), Business $499, Professional $999",
              "Vodeći RPC pružatelj samo za Solanu, s webhookovima, raščlanjenim transakcijama, DAS API-jem za tokene i "
              "NFT-ove i LaserStream streamingom.",
              ["RPC sa staked vezama na plaćenim planovima", "Webhookovi na aktivnost novčanika",
               "Raščlanjena povijest transakcija", "Dodatni krediti $5 za milijun"],
              "Krediti brzo nestaju na upitima povijesti; mi potrošnju pratimo svaki dan.")),
        tool("QuickNode", "https://www.quicknode.com", "60+ chains incl. Solana",
             ("Many chains on one account", "1-month free trial (10M credits, 15 req/s)",
              "Build $49 (80M credits, 50 req/s), Accelerate $249, Scale $499, Business $999",
              "A multi-chain node provider with a marketplace of add-ons (including Solana token and swap APIs) and "
              "streams.",
              ["Dozens of chains", "Add-on marketplace", "Streams and webhooks", "About 15% off with yearly billing"],
              "Free access is a trial, not a permanent free tier."),
             ("Puno mreža na jednom računu", "Besplatna proba 1 mjesec (10M kredita, 15 zaht./s)",
              "Build $49 (80M kredita, 50 zaht./s), Accelerate $249, Scale $499, Business $999",
              "Pružatelj čvorova za više mreža s tržnicom dodataka (uključujući Solana API-je za tokene i zamjene) i "
              "streamovima.",
              ["Desetci mreža", "Tržnica dodataka", "Streamovi i webhookovi", "Oko 15% popusta uz godišnje plaćanje"],
              "Besplatni pristup je proba, ne trajna besplatna razina.")),
        tool("DexScreener API", "https://docs.dexscreener.com", "80+ chains incl. Solana",
             ("Free pools, prices and new token profiles", "Free, no API key", "–",
              "The public API behind DexScreener: pairs by token or pool, search, latest token profiles and boosts.",
              ["Pairs, price, liquidity, volume", "Search by token or symbol", "Latest profiles and boosts",
               "No sign-up"],
              "No history candles and per-minute rate limits; we take our own snapshots every 20 minutes."),
             ("Besplatni poolovi, cijene i profili novih tokena", "Besplatno, bez API ključa", "–",
              "Javni API iza DexScreenera: parovi po tokenu ili poolu, pretraga, najnoviji profili tokena i boostovi.",
              ["Parovi, cijena, likvidnost, volumen", "Pretraga po tokenu ili simbolu", "Najnoviji profili i boostovi",
               "Bez registracije"],
              "Nema povijesnih svijeća i ima ograničenje po minuti; mi sami snimamo stanje svakih 20 minuta.")),
        tool("Birdeye Data", "https://bds.birdeye.so", "Solana + major EVM chains",
             ("Token, trade and wallet data", "Standard: 30k compute units",
              "Starter $99 (3M CU), Premium $199 (10M), Premium Plus $250 (15M), Business $699 (70M)",
              "Market data API with token prices, OHLCV candles, trades, top traders and wallet portfolios.",
              ["Price history and candles", "Trades and top traders", "Wallet portfolio", "WebSockets on higher plans"],
              "Some endpoints are only on Business and higher."),
             ("Podaci o tokenima, tradeovima i novčanicima", "Standard: 30k compute jedinica",
              "Starter $99 (3M CU), Premium $199 (10M), Premium Plus $250 (15M), Business $699 (70M)",
              "API tržišnih podataka s cijenama tokena, OHLCV svijećama, tradeovima, najvećim traderima i portfeljima "
              "novčanika.",
              ["Povijest cijena i svijeće", "Tradeovi i najveći traderi", "Portfelj novčanika",
               "WebSockets na višim planovima"],
              "Neki endpointi su samo na Business i višim planovima.")),
        tool("Solana Tracker", "https://www.solanatracker.io", "Solana",
             ("Pump.fun and new token data", "2,500 requests/month",
              "Advanced €50 (200k), Pro €200 (1M), Premium €397 (10M), Business €599 (25M)",
              "Solana token data API: prices, charts, holders, trades, PnL and new tokens from launchpads, plus a swap "
              "API.",
              ["New and graduating tokens", "Holders and top traders", "Wallet PnL", "30% off with yearly billing"],
              "Priced in euros; free tier is small."),
             ("Podaci o pump.fun i novim tokenima", "2.500 zahtjeva mjesečno",
              "Advanced €50 (200k), Pro €200 (1M), Premium €397 (10M), Business €599 (25M)",
              "API za podatke o Solana tokenima: cijene, grafovi, holderi, tradeovi, dobit i novi tokeni s launchpadova, "
              "plus API za zamjenu.",
              ["Novi tokeni i tokeni koji diplomiraju", "Holderi i najveći traderi", "Dobit novčanika",
               "30% popusta uz godišnje plaćanje"],
              "Cijene su u eurima; besplatna razina je mala.")),
        tool("CoinGecko API", "https://www.coingecko.com/en/api", "Listed coins, 200+ networks via GeckoTerminal",
             ("Prices of listed coins", "Demo: 10k calls/month, 100/min",
              "Basic $35 (100k calls), Analyst $129 (500k), Lite $499 (2M), Pro $999 (5M+)",
              "The best-known coin price API: prices, market caps, history and exchange data for listed coins, plus "
              "on-chain DEX data.",
              ["Prices and market caps", "Historical data", "Exchange and category data", "On-chain DEX endpoints"],
              "New meme coins appear only once listed; from cloud servers we hit rate limits on the free tier."),
             ("Cijene listanih kriptovaluta", "Demo: 10k poziva mjesečno, 100/min",
              "Basic $35 (100k poziva), Analyst $129 (500k), Lite $499 (2M), Pro $999 (5M+)",
              "Najpoznatiji API za cijene: cijene, tržišne kapitalizacije, povijest i podaci burzi za listane "
              "kriptovalute, plus on-chain DEX podaci.",
              ["Cijene i tržišne kapitalizacije", "Povijesni podaci", "Podaci o burzama i kategorijama",
               "On-chain DEX endpointi"],
              "Novi meme coini pojave se tek kad su listani; s cloud servera smo na besplatnoj razini dobivali "
              "ograničenja.")),
    ],
    chart=dict(fmt="usd2", hl=None, source=PRICES, rows=[
        (("DexScreener API", "DexScreener API"), 0, ("free, no key", "besplatno, bez ključa")),
        (("CoinGecko Basic", "CoinGecko Basic"), 35, ("100k calls", "100k poziva")),
        (("Helius Developer", "Helius Developer"), 49, ("10M credits", "10M kredita")),
        (("QuickNode Build", "QuickNode Build"), 49, ("80M credits", "80M kredita")),
        (("Solana Tracker Advanced", "Solana Tracker Advanced"), 50, ("€50, 200k requests", "€50, 200k zahtjeva")),
        (("Birdeye Starter", "Birdeye Starter"), 99, ("3M compute units", "3M compute jedinica")),
    ], title=("First paid plan per API", "Prvi plaćeni plan po API-ju"), sub=("Per month", "Mjesečno")),
    sources=[("Helius pricing", "https://www.helius.dev/pricing"), ("QuickNode pricing", "https://www.quicknode.com/pricing"),
             ("CoinGecko API pricing", "https://www.coingecko.com/en/api/pricing"),
             ("Birdeye Data Services pricing", "https://docs.birdeye.so/docs/pricing"),
             ("Solana Tracker data API", "https://www.solanatracker.io/data-api"),
             ("DexScreener API reference", "https://docs.dexscreener.com/api/reference")],
    blog=("what-is-wallet-tracking", "market-cap-liquidity-slippage", "what-is-pump-fun"),
    terms=("crypto-api", "dex", "liquidity", "trading-volume", "holders", "token"))


# 7 ── copy trading ────────────────────────────────────────────────────────────────────────────────────────────
cat("copy", "copy-trading-platforms", "copy-trading-platforme",
    en=dict(
        tag="Copy trading", short="Copy trading platforms",
        h1="Best copy trading platforms for crypto in 2026 (on-chain and exchanges)",
        title="Best crypto copy trading platforms 2026: GMGN, Trojan, Binance, Bybit, Bitget (fees) | MemeSonar",
        desc="On-chain copy trading (GMGN, Trojan, Cielo) vs exchange copy trading (Binance, Bybit, Bitget): fees, "
             "copy speed, and why only 2 of 50 active wallets we tracked were worth copying.",
        kw=["best copy trading platform", "crypto copy trading platforms", "solana copy trading", "copy trading"],
        tldr="There are two kinds. <b>On-chain</b> (GMGN, Trojan) copies any Solana wallet for about 1% per trade, "
             "1 to 5 seconds behind it. <b>Exchange</b> copy trading (Binance, Bybit, Bitget) copies a lead trader "
             "inside the exchange and charges a <b>profit share</b>, usually 10% to 20% of profit, only on winning "
             "trades. The platform matters less than who you copy: 22% of active wallets we tracked were profitable.",
        intro="<p>Copy trading means your account buys and sells automatically when someone else does. On Solana you "
              "copy a wallet address; on an exchange you copy a 'lead trader' with a public track record. Both can "
              "lose money fast if the trader you copy is a sniper, a bot or simply lucky, so every platform below "
              "should be used with a fixed amount per trade and a daily limit.</p>",
        chart_note="<p>Why picking matters more than the platform: the median active wallet in our tracker, with 10+ "
                   "closed trades.</p>",
        choose=["<b>On-chain vs exchange.</b> On-chain copies meme coins and anything on Solana; exchange copy trading "
                "is mostly futures and big coins, with KYC.",
                "<b>Fee type.</b> 1% per trade costs you on losers too; a profit share only costs on winners, but "
                "exchange futures add leverage risk.",
                "<b>Speed.</b> On-chain copies land seconds after the wallet; on fast tokens that alone can turn a win "
                "into a loss.",
                "<b>Filter the trader.</b> At least 10 closed trades, holding time you can follow, no sniper or "
                "insider labels.",
                "<b>Cap it.</b> A fixed $ per trade and a daily maximum (we default to $25 and 10 trades)."],
        faq=[("Which copy trading platform is best for beginners?",
              "An exchange's copy trading (Bitget, Bybit, Binance) is simpler: you pick a trader with a public record "
              "and set an amount. Avoid leverage until you understand it. For Solana meme coins, start with tiny "
              "amounts on GMGN or Trojan."),
             ("How much does copy trading cost?",
              "On-chain bots charge about 1% on each buy and sell plus network fees. Exchanges charge normal trading "
              "fees plus a profit share for the lead trader, typically 10% to 20% of profit."),
             ("Is copy trading profitable?",
              "Only if you copy the rare trader with a real edge. In our tracker the median active Solana wallet lost "
              "money (profit factor 0.65) and 2 of 50 passed our copy filter."),
             ("Can I practise copy trading without money?",
              "Yes. MemeSonar members copy influencers and wallets with a virtual $1,000 in our competition before "
              "risking real money.")]),
    hr=dict(
        tag="Copy trading", short="Copy trading platforme",
        h1="Najbolje platforme za kripto copy trading 2026. (on-chain i burze)",
        title="Najbolje copy trading platforme 2026: GMGN, Trojan, Binance, Bybit, Bitget (naknade) | MemeSonar",
        desc="On-chain copy trading (GMGN, Trojan, Cielo upozorenja) i copy trading na burzama (Binance, Bybit, "
             "Bitget): kako naplaćuju, koliko brzo kopiraju i zašto je samo 2 od 50 novčanika vrijedilo kopirati.",
        tldr="Postoje dvije vrste. <b>On-chain</b> (GMGN, Trojan) kopira bilo koji Solana novčanik za oko 1% po "
             "tradeu, 1 do 5 sekundi iza njega. Copy trading na <b>burzi</b> (Binance, Bybit, Bitget) kopira glavnog "
             "tradera unutar burze i naplaćuje <b>udio u dobiti</b>, obično 10% do 20% dobiti, samo na dobitnim "
             "tradeovima. Platforma je manje važna od toga koga kopiraš: samo 22% aktivnih novčanika koje smo pratili "
             "bilo je u plusu.",
        intro="<p>Copy trading znači da tvoj račun automatski kupuje i prodaje kad to napravi netko drugi. Na Solani "
              "kopiraš adresu novčanika; na burzi kopiraš 'glavnog tradera' s javnim rezultatima. Oboje može brzo "
              "izgubiti novac ako je trader kojeg kopiraš snajper, bot ili samo sretnik, pa svaku platformu ispod "
              "koristi s fiksnim iznosom po tradeu i dnevnim ograničenjem.</p>",
        chart_note="<p>Zašto je odabir važniji od platforme: medijan aktivnog novčanika u našem praćenju, s 10+ "
                   "zatvorenih tradeova.</p>",
        choose=["<b>On-chain ili burza.</b> On-chain kopira meme coine i sve na Solani; copy trading na burzi je "
                "uglavnom futures i velike kriptovalute, uz KYC.",
                "<b>Vrsta naknade.</b> 1% po tradeu plaćaš i na gubitke; udio u dobiti plaćaš samo na dobitke, ali "
                "futures na burzi dodaju rizik poluge.",
                "<b>Brzina.</b> On-chain kopije stignu sekundama nakon novčanika; na brzim tokenima to samo može "
                "pretvoriti dobitak u gubitak.",
                "<b>Filtriraj tradera.</b> Najmanje 10 zatvorenih tradeova, vrijeme držanja koje možeš pratiti, bez "
                "oznaka snajpera ili insajdera.",
                "<b>Ograniči.</b> Fiksni iznos po tradeu i dnevni maksimum (kod nas zadano $25 i 10 tradeova)."],
        faq=[("Koja je copy trading platforma najbolja za početnike?",
              "Copy trading na burzi (Bitget, Bybit, Binance) je jednostavniji: odabereš tradera s javnim rezultatima "
              "i upišeš iznos. Izbjegavaj polugu dok je ne razumiješ. Za Solana meme coine kreni s malim iznosima na "
              "GMGN-u ili Trojanu."),
             ("Koliko košta copy trading?",
              "On-chain botovi naplaćuju oko 1% na svaku kupnju i prodaju plus mrežne naknade. Burze naplaćuju "
              "uobičajene naknade plus udio u dobiti za glavnog tradera, obično 10% do 20% dobiti."),
             ("Je li copy trading isplativ?",
              "Samo ako kopiraš rijetkog tradera sa stvarnom prednošću. U našem praćenju medijan aktivnog Solana "
              "novčanika gubio je novac (profit faktor 0,65), a 2 od 50 prošla su naš copy filtar."),
             ("Mogu li vježbati copy trading bez novca?",
              "Da. Članovi MemeSonara kopiraju influencere i novčanike s virtualnih $1.000 u našem natjecanju prije "
              "nego riskiraju pravi novac.")]),
    tools=[
        tool("GMGN", "https://gmgn.ai", "Solana, Ethereum, Base, BNB Chain",
             ("Finding and copying Solana wallets", "Free to browse", "1% per copied trade",
              "Wallet discovery and copy trading in one app: pick a wallet from its PnL page and copy its buys with "
              "your own amount, take profit and stop loss.",
              ["Wallet leaderboards and PnL", "Copy with own amount and limits", "Multi-chain"],
              "Reported copy latency 1 to 3 seconds."),
             ("Pronalazak i kopiranje Solana novčanika", "Pregledavanje besplatno", "1% po kopiranom tradeu",
              "Otkrivanje novčanika i copy trading u jednoj aplikaciji: odabereš novčanik s njegove stranice dobiti i "
              "kopiraš kupnje s vlastitim iznosom, take profitom i stop lossom.",
              ["Ljestvice i dobit novčanika", "Kopiranje s vlastitim iznosom i limitima", "Više mreža"],
              "Prijavljeno kašnjenje kopije 1 do 3 sekunde.")),
        tool("Trojan", "https://trojan.com", "Solana",
             ("Copy trading from Telegram", "No subscription", "1% per trade, 0.9% with referral",
              "Telegram bot with copy trading of any Solana wallet, plus limit orders and DCA.",
              ["Copy any wallet from chat", "Per-wallet amount and slippage", "Limit and DCA orders"],
              "No built-in wallet discovery; find wallets elsewhere. Users report 2 to 5 second copy delay."),
             ("Copy trading iz Telegrama", "Bez pretplate", "1% po tradeu, 0,9% uz referral",
              "Telegram bot s kopiranjem bilo kojeg Solana novčanika, plus limit nalozi i DCA.",
              ["Kopiranje novčanika iz chata", "Iznos i slippage po novčaniku", "Limit i DCA nalozi"],
              "Nema ugrađenog otkrivanja novčanika; nađi ih drugdje. Korisnici javljaju kašnjenje 2 do 5 sekundi.")),
        tool("Cielo", "https://cielo.finance", "Solana + EVM chains",
             ("Alerts first, then you decide", "Up to 250 wallets (10 Solana)", "Pro $59/mo, Whale $199/mo",
              "Not an auto-copier: Cielo alerts you in Telegram when tracked wallets trade, and you buy yourself. "
              "Slower, but you skip the trades you don't like.",
              ["Telegram alerts", "Wallet PnL", "Many chains"],
              "Manual copying is slower than a bot."),
             ("Prvo upozorenje, onda ti odlučiš", "Do 250 novčanika (10 Solana)", "Pro $59/mj, Whale $199/mj",
              "Ne kopira automatski: Cielo javi na Telegramu kad praćeni novčanici trguju, a ti kupiš sam. Sporije, "
              "ali preskočiš tradeove koji ti se ne sviđaju.",
              ["Upozorenja na Telegramu", "Dobit novčanika", "Puno mreža"],
              "Ručno kopiranje je sporije od bota.")),
        tool("Bitget", "https://www.bitget.com/copy-trading", "Exchange (spot and futures)",
             ("Exchange copy trading with many lead traders", "Copying is free to start",
              "Profit share 10% to 20% set by the lead trader, only on profitable closes, plus trading fees",
              "One of the largest exchange copy trading programmes, for futures and spot, with public trader stats.",
              ["Public lead trader records", "Profit share only on wins", "Spot and futures copying"],
              "Futures copying uses leverage; KYC required; availability depends on your country."),
             ("Copy trading na burzi s puno tradera", "Kopiranje je besplatno za početak",
              "Udio u dobiti 10% do 20% koji postavi trader, samo na dobitna zatvaranja, plus naknade trgovanja",
              "Jedan od najvećih programa copy tradinga na burzi, za futures i spot, s javnom statistikom tradera.",
              ["Javni rezultati tradera", "Udio samo na dobit", "Kopiranje spota i futuresa"],
              "Futures kopiranje koristi polugu; potreban KYC; dostupnost ovisi o zemlji.")),
        tool("Bybit", "https://www.bybit.com/copyTrade", "Exchange (futures and spot)",
             ("Exchange copy trading, futures focus", "Copying is free to start",
              "Profit share for the lead trader (around 10%), plus trading fees",
              "Copy trading of 'master traders' on Bybit, mostly perpetual futures, with filters by ROI, drawdown and "
              "followers.",
              ["Trader filters by ROI and drawdown", "Profit share only on wins", "Futures and spot"],
              "Leverage and liquidation risk; KYC required."),
             ("Copy trading na burzi, naglasak na futuresu", "Kopiranje je besplatno za početak",
              "Udio u dobiti za tradera (oko 10%), plus naknade trgovanja",
              "Kopiranje 'master tradera' na Bybitu, uglavnom perpetual futures, s filtrima po ROI-ju, padu i "
              "pratiteljima.",
              ["Filtri po ROI-ju i padu", "Udio samo na dobit", "Futures i spot"],
              "Rizik poluge i likvidacije; potreban KYC.")),
        tool("Binance", "https://www.binance.com/en/copy-trading", "Exchange (futures and spot)",
             ("Largest exchange, many lead traders", "Copying is free to start",
              "Profit share set by the lead trader (commonly 10%), plus trading fees",
              "Binance's copy trading for futures and spot portfolios, with lead trader rankings and fixed or ratio "
              "copy modes.",
              ["Lead trader rankings", "Fixed amount or ratio copying", "Futures and spot"],
              "Not available in every country; futures carry liquidation risk."),
             ("Najveća burza, puno tradera", "Kopiranje je besplatno za početak",
              "Udio u dobiti koji postavi trader (najčešće 10%), plus naknade trgovanja",
              "Binance copy trading za futures i spot portfelje, s ljestvicom tradera i kopiranjem fiksnim iznosom ili "
              "u omjeru.",
              ["Ljestvica tradera", "Kopiranje fiksnim iznosom ili u omjeru", "Futures i spot"],
              "Nije dostupno u svim zemljama; futures nosi rizik likvidacije.")),
        tool("MemeSonar", "/", "Solana",
             ("Practising copy trading risk-free", "Invite only (free for members)", "–",
              "Our own app: follow an influencer or a wallet and the app enters each fresh call (at most 10 minutes "
              "old) on a virtual $1,000 account, with a daily cap, rug check and automatic exits.",
              ["Copy influencers or wallets", "Virtual $1,000, no real money", "Rug check before each copy",
               "Shows what each copy did"],
              "Practice only (virtual money); real trades you sign yourself in your own wallet."),
             ("Vježba copy tradinga bez rizika", "Samo uz pozivnicu (besplatno za članove)", "–",
              "Naša aplikacija: prati influencera ili novčanik, a aplikacija ulazi na svaki svježi poziv (star najviše "
              "10 minuta) na virtualnom računu od $1.000, uz dnevni limit, provjeru ruga i automatske izlaze.",
              ["Kopiraj influencere ili novčanike", "Virtualnih $1.000, bez pravog novca",
               "Provjera ruga prije svake kopije", "Pokazuje što je napravila svaka kopija"],
              "Samo vježba (virtualni novac); prave tradeove potpisuješ sam u svom novčaniku."), ours=True),
    ],
    chart=dict(fmt="pct", hl=(2,), source=WALLETS, rows=[
        (("Share of trades won", "Udio dobitnih tradeova"), 31, ("median wallet", "medijan novčanika")),
        (("Wallets in profit", "Novčanici u plusu"), 22, ("after all trades", "nakon svih tradeova")),
        (("Passed our copy filter", "Prošli naš copy filtar"), 4, ("2 of 50 wallets", "2 od 50 novčanika")),
    ], title=("Copying the average wallet loses", "Kopiranje prosječnog novčanika gubi"),
        sub=("50 Solana wallets with 10+ closed trades", "50 Solana novčanika s 10+ zatvorenih tradeova")),
    sources=[("Bitget copy trading FAQ", "https://www.bitget.com/support/articles/12560603892733"),
             ("GMGN docs: fees", "https://docs.gmgn.ai/index/gmgn-fees-settings"),
             ("Cielo docs: plans", "https://docs.cielo.finance/wallet-tracking/subscribe"),
             ("Bybit copy trading", "https://www.bybit.com/copyTrade"),
             ("Binance copy trading", "https://www.binance.com/en/copy-trading"), ("Trojan", "https://trojan.com")],
    blog=("what-is-copy-trading", "what-is-wallet-tracking", "what-is-a-kol-in-crypto"),
    terms=("copy-trading", "profit-share", "smart-money", "take-profit", "stop-loss", "roi"))


# ─────────────────────────────────────────────────────────────────────────────────────────────── pillar page
PILLAR = {
    "en": dict(
        h1="The best crypto tools in 2026, compared with real prices",
        title="Best crypto tools 2026: wallet trackers, analysis, trading bots, wallets, rug checkers, APIs | MemeSonar",
        desc="Our guide to the best crypto tools for Solana and meme coin traders: wallet trackers, analysis, trading "
             "bots, wallets and cold storage, rug checkers, APIs and copy trading. Prices checked monthly.",
        lead="Seven categories, almost 40 tools, real prices from each vendor's own pricing page. Written by the team behind "
             "MemeSonar, a Solana research app that uses many of these tools every day.",
        tldr="If you only set up five things: <b>Phantom</b> (free wallet) plus a <b>hardware wallet</b> (from $50) for "
             "savings, <b>DexScreener</b> (free) for charts, <b>RugCheck</b> (free) before every buy, a tracker like "
             "<b>Cielo</b> or <b>GMGN</b> (free tiers) for wallets, and <b>Jupiter</b> for cheap swaps. Pay for a "
             "terminal (about 1% per trade) or Nansen ($49/month) only when you know what they add for you.",
        picks_h="Our pick in each category",
        cols=("Category", "Best free", "Best paid", "Price of paid pick"),
        chart_h="What the popular paid plans cost",
        chart_note="<p>Monthly price of the plan most traders upgrade to first. Trading terminals and bots have no "
                   "subscription: they take about 1% of every trade instead.</p>",
        stack_h="The free starter stack",
        stack=["<b>Wallet:</b> Phantom or Solflare for trading; move savings to a hardware wallet.",
               "<b>Charts:</b> DexScreener or Birdeye.",
               "<b>Safety:</b> RugCheck plus Bubblemaps on every new token.",
               "<b>Wallets to watch:</b> GMGN or Kolscan to find them, Cielo's free plan for alerts.",
               "<b>Swaps:</b> Jupiter (no Jupiter fee on manual swaps).",
               "<b>Learning:</b> our <a href=/blog>blog</a> and <a href=/glossary>glossary</a>."],
        how_h="How we compare tools",
        how=["Prices and limits come from each vendor's own pricing page or docs, checked on 1 November 2026. When a "
             "vendor does not publish a price, we say so.",
             "Where we have our own data (10,650 pump.fun tokens, 469 tracked wallets), we use it to show what "
             "matters more than the tool.",
             "MemeSonar is our product and appears where it fits, marked as ours. We earn nothing from the other "
             "tools: no affiliate links.",
             "Fees and plans change often. Check the vendor's page before you pay or deposit."],
        cats_h="All categories", read="Compare", updated="Prices checked", ours="Our tool",
        faq=[("What crypto tools do I need as a beginner?",
              "A wallet (Phantom), a chart site (DexScreener), a rug checker (RugCheck) and a hardware wallet once you "
              "hold real money. All but the hardware wallet are free."),
             ("Which crypto tools are free?",
              "DexScreener, RugCheck, Bubblemaps (basic), Kolscan, Arkham's explorer, Phantom, Solflare, Jupiter and "
              "the free tiers of Cielo, TradingView, Helius and CoinGecko."),
             ("Are paid crypto tools worth it?",
              "Only when they replace work you already do. A terminal saves seconds on new tokens, Nansen saves hours of "
              "wallet research, an API saves building your own indexer. If you can't name the saving, stay free."),
             ("Do you get paid by these tools?",
              "No. There are no affiliate or referral links on these pages.")]),
    "hr": dict(
        h1="Najbolji kripto alati 2026., usporedba sa stvarnim cijenama",
        title="Najbolji kripto alati 2026: praćenje novčanika, analiza, botovi, novčanici, rug check, API | MemeSonar",
        desc="Naš vodič kroz najbolje kripto alate za Solana i meme coin tradere: praćenje novčanika, analiza, trading "
             "botovi, novčanici i hladno čuvanje, provjera ruga, API-ji i copy trading. Cijene provjeravamo mjesečno.",
        lead="Sedam kategorija, gotovo 40 alata, stvarne cijene sa službenih cjenika. Napisao tim koji stoji iza "
             "MemeSonara, Solana aplikacije za istraživanje koja mnoge od ovih alata koristi svaki dan.",
        tldr="Ako postaviš samo pet stvari: <b>Phantom</b> (besplatni novčanik) plus <b>hardverski novčanik</b> (od $50) "
             "za ušteđevinu, <b>DexScreener</b> (besplatno) za grafove, <b>RugCheck</b> (besplatno) prije svake "
             "kupnje, alat poput <b>Cielo</b> ili <b>GMGN</b> (besplatne razine) za novčanike i <b>Jupiter</b> za jeftine "
             "zamjene. Za terminal (oko 1% po tradeu) ili Nansen ($49 mjesečno) plati tek kad znaš što ti donose.",
        picks_h="Naš izbor u svakoj kategoriji",
        cols=("Kategorija", "Najbolje besplatno", "Najbolje plaćeno", "Cijena plaćenog izbora"),
        chart_h="Koliko koštaju popularni plaćeni planovi",
        chart_note="<p>Mjesečna cijena plana na koji većina tradera prvo prijeđe. Trading terminali i botovi nemaju "
                   "pretplatu: umjesto toga uzimaju oko 1% svakog tradea.</p>",
        stack_h="Besplatni početni komplet",
        stack=["<b>Novčanik:</b> Phantom ili Solflare za trgovanje; ušteđevinu prebaci na hardverski novčanik.",
               "<b>Grafovi:</b> DexScreener ili Birdeye.",
               "<b>Sigurnost:</b> RugCheck i Bubblemaps na svakom novom tokenu.",
               "<b>Novčanici za praćenje:</b> GMGN ili Kolscan za pronalazak, besplatni Cielo za upozorenja.",
               "<b>Zamjene:</b> Jupiter (bez Jupiterove naknade na ručne swapove).",
               "<b>Učenje:</b> naš <a href=/hr/blog>blog</a> i <a href=/hr/rjecnik>rječnik</a>."],
        how_h="Kako uspoređujemo alate",
        how=["Cijene i ograničenja su sa službenog cjenika ili dokumentacije svakog alata, provjereno 1. studenoga 2026. "
             "Kad alat ne objavljuje cijenu, to i napišemo.",
             "Gdje imamo vlastite podatke (10.650 pump.fun tokena, 469 praćenih novčanika), koristimo ih da pokažemo "
             "što je važnije od alata.",
             "MemeSonar je naš proizvod i pojavljuje se gdje odgovara, označen kao naš. Od drugih alata ne "
             "zarađujemo ništa: nema affiliate linkova.",
             "Naknade i planovi se često mijenjaju. Provjeri stranicu alata prije plaćanja ili uplate."],
        cats_h="Sve kategorije", read="Usporedi", updated="Cijene provjerene", ours="Naš alat",
        faq=[("Koji kripto alati trebaju početniku?",
              "Novčanik (Phantom), stranica s grafovima (DexScreener), provjera ruga (RugCheck) i hardverski novčanik "
              "kad držiš pravi novac. Sve osim hardverskog novčanika je besplatno."),
             ("Koji su kripto alati besplatni?",
              "DexScreener, RugCheck, Bubblemaps (osnovno), Kolscan, Arkham explorer, Phantom, Solflare, Jupiter i "
              "besplatne razine Ciela, TradingViewa, Heliusa i CoinGecka."),
             ("Isplate li se plaćeni kripto alati?",
              "Samo kad zamijene posao koji već radiš. Terminal štedi sekunde na novim tokenima, Nansen štedi sate "
              "istraživanja novčanika, API štedi izradu vlastitog indeksa. Ako ne znaš imenovati uštedu, ostani na "
              "besplatnom."),
             ("Plaćaju li vas ovi alati?",
              "Ne. Na ovim stranicama nema affiliate ni referral linkova.")]),
}

# (category key, best free, best paid, price of paid pick) per language
PICKS = {
    "wallets": (("GMGN, Kolscan, Arkham", "Cielo Pro", "$59/mo"), ("GMGN, Kolscan, Arkham", "Cielo Pro", "$59/mj")),
    "analysis": (("DexScreener, Bubblemaps", "Nansen Pro", "$49/mo yearly"), ("DexScreener, Bubblemaps", "Nansen Pro", "$49/mj godišnje")),
    "trading": (("Jupiter (swaps)", "Axiom", "1% per trade, 0.75-0.95% net"), ("Jupiter (zamjene)", "Axiom", "1% po tradeu, neto 0,75-0,95%")),
    "storage": (("Phantom, Solflare", "Trezor Safe 3 / Ledger", "from $50"), ("Phantom, Solflare", "Trezor Safe 3 / Ledger", "od $50")),
    "rug": (("RugCheck + Bubblemaps", "–", "all free"), ("RugCheck + Bubblemaps", "–", "sve besplatno")),
    "api": (("DexScreener API, Helius free", "Helius Developer", "$49/mo"), ("DexScreener API, Helius besplatno", "Helius Developer", "$49/mj")),
    "copy": (("Cielo alerts (manual)", "GMGN / Bitget", "1% per trade / 10-20% of profit"), ("Cielo upozorenja (ručno)", "GMGN / Bitget", "1% po tradeu / 10-20% dobiti")),
}

PILLAR_CHART = dict(fmt="usd2", source=PRICES, rows=[
    (("TradingView Essential", "TradingView Essential"), 12.95, ("analysis, billed yearly", "analiza, godišnje")),
    (("CoinGecko API Basic", "CoinGecko API Basic"), 35, ("API", "API")),
    (("Squads Business", "Squads Business"), 49, ("multisig, optional", "multisig, po želji")),
    (("Helius Developer", "Helius Developer"), 49, ("Solana API", "Solana API")),
    (("Nansen Pro", "Nansen Pro"), 49, ("billed yearly ($69 monthly)", "godišnje ($69 mjesečno)")),
    (("Cielo Pro", "Cielo Pro"), 59, ("wallet tracker", "praćenje novčanika")),
    (("Dune Analyst", "Dune Analyst"), 75, ("analysis", "analiza")),
], title=("Popular paid plans", "Popularni plaćeni planovi"), sub=("USD per month", "USD mjesečno"))
