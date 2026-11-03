"""SimianX second opinion on the long-term list + demo test of its long signals (simianx/).

    python3 run_simianx.py once      one pass (start.sh runs it every SIMIANX_EVERY_MIN, default 180)

Needs SIMIANX_API_KEY (Render env). Real money never from here: see league/simianx_feed.py and /pravi-trade."""
import sys

from simianx import client, run


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if not argv or argv[0] != "once":
        print(__doc__)
        return 2
    try:
        print(run.once())
    except client.Error as e:
        print(f"simianx: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
