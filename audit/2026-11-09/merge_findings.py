"""Merge phase-2 workflow outputs into findings.md for the synthesiser. Usage: python3 -I merge_findings.py <output.json>..."""
import json, sys

conf, rej = [], []
for path in sys.argv[1:]:
    d = json.load(open(path))
    res = d.get("result") or {}
    for lens, r in res.items():
        for f in r.get("confirmed", []):
            conf.append((lens, f))
        for f in r.get("rejected", []):
            rej.append((lens, f))

sev_rank = {"kritično": 0, "visoko": 1, "srednje": 2, "nisko": 3}
conf.sort(key=lambda x: (sev_rank.get(x[1].get("severity"), 9), x[1].get("file", "")))

def votes(f):
    out = []
    for v in f.get("votes", []):
        s = f"{v.get('lens')}: {'DA' if v.get('real') else 'NE'} ({v.get('confidence')}) {v.get('reason', '')}"
        if v.get("corrected_claim"):
            s += f" | ISPRAVAK: {v['corrected_claim']}"
        if v.get("severity"):
            s += f" | težina po verifikatoru: {v['severity']}"
        out.append(s)
    return "\n    ".join(out)

lines = [f"# POTVRĐENI NALAZI ({len(conf)})\n"]
for i, (lens, f) in enumerate(conf, 1):
    lines.append(f"## P{i} [{f.get('category')}/{f.get('severity')}] (leća {lens}) {f.get('title')}")
    lines.append(f"- mjesto: {f.get('file')}:{f.get('line')}")
    lines.append(f"- tvrdnja: {f.get('claim')}")
    lines.append(f"- dokaz: {f.get('evidence')}")
    lines.append(f"- popravak: {f.get('fix')}")
    lines.append(f"- učinak na profit: {f.get('profit_impact')}")
    lines.append(f"- glasovi:\n    {votes(f)}\n")

lines.append(f"\n# ODBAČENI NALAZI ({len(rej)})\n")
for i, (lens, f) in enumerate(rej, 1):
    why = " / ".join(v.get("reason", "") for v in f.get("votes", []) if not v.get("real"))
    lines.append(f"- O{i} (leća {lens}) {f.get('file')}:{f.get('line')} {f.get('title')} — tvrdnja: {f.get('claim')} — ZAŠTO ODBAČENO: {why}")

txt = "\n".join(lines)
open("/tmp/claude-0/-home-user/4912361d-d525-5b3e-b714-652a838e02b7/scratchpad/findings.md", "w").write(txt)
print(f"potvrđeno {len(conf)}, odbačeno {len(rej)}, {len(txt)} chars")
by = {}
for lens, f in conf:
    by[lens] = by.get(lens, 0) + 1
print("po lećama:", by)
print("po težini:", {s: sum(1 for _, f in conf if f.get('severity') == s) for s in sev_rank})
