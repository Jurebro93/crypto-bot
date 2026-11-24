"""Kritičar (OpenAI), 15.11. (vlasnik: "OpenAI kao kritičar algoritma: kritičar kao data scientist, kritičar otvorenih
tradeova, analiza i slično"). ADVICE ONLY: nothing here places, changes or closes a trade or changes a setting.

    prompts.py     the prompts (the owner may edit them) and the answer's JSON schemas
    openai_api.py  the stdlib client of the OpenAI Responses API, prices, cost per call
    store.py       trade.db critic_calls / critic_verdicts / critic_kv, the budget caps, the critic's own measurement
    data.py        the numbers it reads (strategy statistics, rules, changes, macro, cost per source, reports)
    privacy.py     the scrub of every outgoing text (no secret, env name, wallet, host, internal name)
    notes.py       its advice as assistant notes (ui/assistnotes, key "openai-kriticar"), shown as "Kritičar (OpenAI)"
    trades.py      the open-trade critic (every 5 min a check, a call only on a change, at least every 15 min with
                   real money open)
    daily.py       the daily algorithm / data-science review incl. the critique of the newest reports
run_critic.py is the command line; run_sched.py schedules it; the switch is trade/settings flag openai_kritika.
"""
