"""Archive of microcap and rug data (ops/arhiva.py; owner switch arhiva_mikrokapova).

    python3 run_arhiva.py --auto                                start.sh, every 30 min: works only 01-06 Zagreb, once a night
    python3 run_arhiva.py plan                                  the plan now (output/arhiva_plan.md), nothing moves
    python3 run_arhiva.py vrati <baza> <tablica> [--date YYYYMMDD]   puts an archive back into the live table
"""
import sys

from ops import arhiva

if __name__ == "__main__":
    sys.exit(arhiva.main())
