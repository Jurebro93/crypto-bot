"""python3 -m stanja: the drift between the registry and the code (nothing printed = they agree)."""
import sys

from stanja import provjera, registar

rows = provjera.drift(registar.MACHINES)
for key, kind, lit, path in rows:
    print(f"{key}: {kind} '{lit}' ({path})")
print(f"strojeva {len(registar.MACHINES)}, odstupanja {len(rows)}")
sys.exit(1 if rows else 0)
