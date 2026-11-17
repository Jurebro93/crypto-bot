"""Declared state machines of MemeSonar (17.11., owner: "Find all of the implicit state machines in my app. Make the
best decision that will elevate all three: UX, DX and AX, without breaking anything").

The app had ~80 small state machines whose states lived only as string literals next to the code that moves them
(positions.status, a flag's mode, a request's status, a breaker in a module global ...). Nobody could answer "what
state is X in, who put it there, what moves it" without reading code: on 17.11. neither the owner nor the assistant
could say whether Grok was "paused". This package is the one place that says it:

  registar.py   every machine: its states (the exact literals + the Croatian word for them), the moves, where the
                state is stored, who may change it, the known caveats. Declarations only: it runs nothing and no
                trading code imports it for a decision.
  provjera.py   reads the source and compares its literals with the registry (tests/test_stanja_offline.py): a new
                undeclared state, or a declared one the code dropped, fails the test. DX: the list cannot rot.
  ploca.py      the state NOW of the global machines (Autopilot, kill switch, real-money switches, Grok autotrade,
                exit plans, MCP access, BTC and macro regime, the bot's heartbeat, flags), each with since / who /
                what changes it. Read-only. UX: the owner's page /stanje; AX: the MCP tool get_system_state.

python3 -m stanja prints the drift (nothing = the registry matches the code).
"""
