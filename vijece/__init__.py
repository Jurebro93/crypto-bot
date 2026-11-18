"""Vijeće (the council): Grok, OpenAI and Claude review each other's proposals and the tool accepts what makes sense
(18.11., vlasnik: "Automatski šalji upite OpenAI-u i Groku, neka pomognu odlučiti u kojem smjeru ići, i automatski
prihvati sve prijedloge koji imaju smisla. Kad Grok pošalje prijedlog, Claude i OpenAI moraju biti kritični prema
njemu, doraditi ga i prihvatiti ako se slažu. Isto tako, ako OpenAI ima prijedlog, Grok i Claude moraju biti kritični
i prihvatiti ga ako ima smisla. Neka alat sam sebe popravlja i uči i odlučuje kako i u kojem smjeru ići i na što
usmjeriti sve resurse, i zašto.").

  store.py      trade.db tables vijece_ocjene / vijece_odluke / vijece_kv, who proposed a note and who reviews it, the
                queue (suggestion notes, status novo, newer than the feature's start), the day's spend, the log lines
  kriticari.py  one review by OpenAI (critic/openai_api) or Claude (the anthropic SDK, report/ai.py's pattern): verdict
                slazem | doradi | protiv, the critique, an optional refined change, how it raises net profit
  odluka.py     the decision after every new review: both reviewers without a "protiv" = accepted (applied through
                ui/assistnotes.apply when the key is allow-listed and not real money; marked for the coding session
                otherwise); both "protiv" = rejected; a split, two different refinements or a real-money key = the owner
  smjer.py      the direction session: what is measured (brief), "one direction for ALL resources" asked of OpenAI and
                Claude, their proposals stored as notes "Smjer: ..." that go through the same cross-review
  sjeme.py      Claude's four proposals of 18.11., stored once
  mcp.py        Grok's side (it has no API here: Grok Bot polls our MCP server): get_council_queue,
                submit_council_review, get_council, and the tasks of get_grok_tasks
  posao.py      one pass (run_vijece.py tick, every 15 min from start.sh), the state, the page's one line

Real money is switched and sized only by the owner (CLAUDE.md): a change of size_sol, max_open, tp_default,
sl_default, copy.*, or anything naming pravi / live / autotrade / kill is never applied here, whatever the reviewers
say; flags move at most to shadow (ui/assistnotes.apply). Env VIJECE=0 switches the whole council off.
"""


def za_izvedbu(con, limit=50):
    """The accepted proposals that need code (the Claude Code session implements them): see vijece/store.za_izvedbu."""
    from vijece import store
    return store.za_izvedbu(con, limit)
