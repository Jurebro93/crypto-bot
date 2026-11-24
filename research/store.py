"""Read the research reports (research/hope.py writes DATA_DIR/research/<name>.json and .md) for the MCP tool
get_research (Grok): a list of reports, the summary, or a page of one list (wallets, calls ...). Read only."""
import json
import os
import re

_NAME = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")
LISTS = ("wallets", "calls", "calls_before_marko", "holders_top20")


def folder():
    from research import hope
    return hope.out_dir()


def reports():
    d = folder()
    out = []
    for f in sorted(os.listdir(d)):
        if f.endswith(".json"):
            st = os.stat(os.path.join(d, f))
            out.append({"name": f[:-5], "bytes": st.st_size, "mtime": int(st.st_mtime)})
    return out


def read(name=None, part=None, limit=None, offset=None, sort=None):
    """name: a report (None: the list of reports). part: "summary" (default: the Markdown and the counts), one of
    LISTS (a page: limit 1-500, default 100, offset), "caller_trades", "bundles" or "all" (the whole JSON, can be
    MBs). sort for wallets: first_buy_ts (default), sol_in, pnl_sol, net_tok (largest first except first_buy_ts)."""
    if not name:
        return {"reports": reports()}
    if not _NAME.match(str(name)):
        return {"error": "bad name"}
    path = os.path.join(folder(), f"{name}.json")
    if not os.path.exists(path):
        return {"error": f"no report {name}", "reports": reports()}
    with open(path) as f:
        r = json.load(f)
    part = part or "summary"
    if part == "all":
        return r
    if part == "summary":
        md = os.path.join(folder(), f"{name}.md")
        head = {k: v for k, v in r.items() if not isinstance(v, (list, dict))}
        head.update({f"n_{k}": len(r.get(k) or []) for k in LISTS})
        head["marko_call"] = r.get("marko_call")
        if os.path.exists(md):
            with open(md) as f:
                head["summary_md"] = f.read()
        return head
    if part == "caller_trades":
        return {"caller_wallets": r.get("caller_wallets"), "caller_trades": r.get("caller_trades")}
    if part == "bundles":
        return {"bundles_first_buy_same_slot": r.get("bundles_first_buy_same_slot")}
    if part not in LISTS:
        return {"error": f"part: summary, all, caller_trades, bundles or one of {', '.join(LISTS)}"}
    rows = list(r.get(part) or [])
    if part == "wallets" and sort in ("sol_in", "pnl_sol", "net_tok"):
        rows.sort(key=lambda w: -(w.get(sort) or 0))
    try:
        limit = max(1, min(500, int(limit or 100)))
        offset = max(0, int(offset or 0))
    except (TypeError, ValueError):
        return {"error": "limit/offset must be integers"}
    return {"name": name, "part": part, "total": len(rows), "offset": offset, "rows": rows[offset:offset + limit]}
