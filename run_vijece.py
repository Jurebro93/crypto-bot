"""Vijeće (the council): Grok, OpenAI and Claude review each other's proposals; what both reviewers accept is applied
or queued for the coding session (18.11., vlasnik: "automatski prihvati sve prijedloge koji imaju smisla ... neka alat
sam sebe popravlja i uči i odlučuje kako i u kojem smjeru ići"). vijece/ has the details.

    python3 run_vijece.py tick      # one pass (start.sh every 15 min): seed once, the direction session when due,
                                    # the waiting reviews of OpenAI and Claude, the decisions, the log lines
    python3 run_vijece.py smjer     # the same pass, and a direction session opened now
    python3 run_vijece.py stanje    # the queue and the last decisions (no API call, no review, no decision)

Env: VIJECE=0 switches it off; VIJECE_OPENAI_DAY_USD / VIJECE_CLAUDE_DAY_USD (0.60 each) the members' day budgets;
VIJECE_GROK_WAIT_S (21600) how long Grok's review is waited for; VIJECE_CLAUDE_MODEL / VIJECE_OPENAI_MODEL the models.
Without a key a member is "nedostupan" and its notes wait. Exit code 0 (a failed call is logged and tried again).
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


def main(argv=None):
    try:   # errors go to Sentry like the other loops (a no-op without SENTRY_DSN)
        from ops import sentry
        sentry.init("vijece")
    except Exception as e:  # noqa: BLE001
        print(f"sentry: {type(e).__name__}: {e}", file=sys.stderr, flush=True)
    ap = argparse.ArgumentParser(description="Vijeće (Grok, OpenAI, Claude)")
    ap.add_argument("cmd", choices=("tick", "smjer", "stanje"))
    a = ap.parse_args(argv)
    from vijece import posao
    if a.cmd == "stanje":
        posao.ispis()
        return 0
    posao.tick(smjer_sada=a.cmd == "smjer")
    return 0


if __name__ == "__main__":
    sys.exit(main())
