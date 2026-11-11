"""Fast path (flag fast_path, G24; 11.11. Jure: "svaki signal praćenog novčanika ili influencera dobiva punu analizu
ODMAH, prije odluke").

Every buy of a followed wallet (wallet_follow: the Autopilot's wallet follows; insider: kol/precall confirmed
pre-call wallets; pre_shill: kol/preshill confirmed wallets; group: kol/groupdisc quality wallet groups) and every
call of a followed influencer (the Autopilot's KOL / crew follows: X webhook, X collector, kol_mentions, Telegram)
becomes ONE job fast_check in fast.db's priority queue, decided by run_fast.py within seconds (target < 10 s from the
wallet's buy, at most WORKERS = 20 checks at once). No dependency on the "top 20 proposals" any more: the rug check
and the holders run for every signal's token.

    store.py     fast.db (DATA_DIR, WAL): signals (the queue and every decision with all its checks), price points for
                 the outcomes, the followed sources, costs per source per day, reports, kv
    sources.py   who is followed and as what (kind, label, follow), refreshed every 60 s; the source's record (e)
    enqueue.py   enqueue(): dedupe (one check per (token, source) per 10 min), wake file; the ingestion hooks
                 (Helius webhook, PumpPortal mirror, X webhook, the copy loop) and the worker's own scan as backup
    checks.py    the five checks a) rug b) holders c) fresh flow d) price vs the wallet's entry e) source quality, each
                 {status ok | fail | error, values, threshold, text, ms}; token data cached 60 s and shared by every
                 signal on the token; the network behind one injectable Net
    decide.py    EV = P(TP) x TP - (1 - P) x SL - cost(liq); P shrunk toward the base rate; BUY_PAPER / BUY_LIVE /
                 SKIP (the failing check and its number) / CHECK_FAILED (an API error: retried, never a skip)
    worker.py    the loop of run_fast.py: scan, queue, thread pool, retries (3x within 30 s), outcomes, daily lines
    outcomes.py  +1 / +5 / +15 / +60 min and the max within 60 min of every signal, "propušteno" (SKIP and max >= +20 %)
    paper.py     the trades (league/auto.loop in run_ui.py, league.db's only writer): paper = BUY_PAPER and BUY_LIVE on
                 the demo account with the fast exit plan; live = BUY_LIVE through the real-trade copy path; the copy
                 exit when the source wallet sells; the live gate (LIVE_GATES)
    report.py    the 23:30 day: decisions, latency, false rejects per check, cost per source
    view.py      the Autopilot card (under "Još"), the skip pop-up block, MCP get_fast_checks

Modes (trade settings flag fast_path): off nothing at all (hooks return at once, the worker idles); shadow every check
and every decision, logged, no trade; paper the demo account (autopilot-paper) trades BUY_PAPER and BUY_LIVE (BUY_LIVE
only labelled); live never set by code (LIVE_GATES: >= 30 closed fast-path paper trades with EV > 0). The existing
copy loop (league/copy.py) is unchanged.
"""
