"""Exit rules learned from price paths: when to take profit, how loose to trail, when to give up.

paths.py builds compact price paths (seed from the retrospective study + live paper ticks), learn.py replays
candidate rule sets over them with paper/sim.py and keeps the best one per token class behind guardrails,
profiles.py stores the result on the persistent disk and hands it to new paper trades.
"""
