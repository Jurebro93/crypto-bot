"""Pure counting for the accuracy table: no database, no clock (now is always passed in).

A row is {"subject", "ts", "bucket", "outcome", "resolved_ts"}: the score as it was at ts (never recomputed), the
outcome 1/0 (None = unknown, never counted) and when that outcome became known (ts + the horizon at the latest).

No lookahead (aggregate):
  * only rows whose outcome was known by `now` (resolved_ts <= now) and whose whole horizon has passed
    (ts + horizon <= now): a short horizon that ended early (a stop) cannot leave the slow ones out;
  * only rows shown after the score's last tuning (`since`) and in the last `days` days;
  * one row per subject and UTC day (the first shown), so one token viewed 200 times is one fact.
"""
import math

Z90 = 1.6448536269514722   # two-sided 90 %
MIN_N = 10                 # under this a bucket is "premalo podataka"
DAY = 86400


def wilson(k, n, z=Z90):
    """(lo, hi) of a share k/n, Wilson score interval; (None, None) for n = 0."""
    if not n:
        return None, None
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return max(0.0, c - h), min(1.0, c + h)


def window(now, days, since):
    """(lo, hi) of the ts a row may have: [max(now - days, since), now]."""
    lo = now - days * DAY
    if since is not None:
        lo = max(lo, since)
    return lo, now


def usable(rows, now, horizon_s, lo):
    """The rows that may be counted at `now` (see the module doc), deduplicated per subject and UTC day."""
    seen, out = set(), []
    for r in sorted(rows, key=lambda r: (r["ts"], str(r["subject"]))):
        if r.get("outcome") not in (0, 1) or r["bucket"] is None:
            continue
        if r["ts"] < lo or r["ts"] + horizon_s > now:
            continue
        if (r.get("resolved_ts") or r["ts"] + horizon_s) > now:
            continue
        key = (r["subject"], int(r["ts"] // DAY))
        if key in seen:
            continue
        seen.add(key)
        out.append(r)
    return out


def aggregate(rows, spec, now, days=30, min_n=MIN_N):
    """[{bucket, dir, n, k, rate, lo, hi, correct, acc, acc_lo, acc_hi, base_n, base_k, base, enough}] per bucket
    of spec["buckets"] (in that order), counted over usable() rows.
      k        rows of the bucket whose outcome happened (outcome 1)
      base     the share over every bucket of the score (what happens to any shown subject)
      dir      +1: the bucket says the outcome will happen, -1: it will not, 0: no claim (rate only)
      correct  rows where the bucket was right (k for +1, n - k for -1, None for 0); acc its share and interval"""
    lo, _ = window(now, days, spec.get("since"))
    use = usable(rows, now, spec["horizon_s"], lo)
    base_n = len(use)
    base_k = sum(r["outcome"] for r in use)
    out = []
    for b, d in spec["buckets"]:
        g = [r for r in use if r["bucket"] == b]
        n, k = len(g), sum(r["outcome"] for r in g)
        rlo, rhi = wilson(k, n)
        correct = k if d > 0 else (n - k) if d < 0 else None
        alo, ahi = wilson(correct, n) if correct is not None else (None, None)
        out.append({"bucket": b, "dir": d, "n": n, "k": k, "rate": k / n if n else None, "lo": rlo, "hi": rhi,
                    "correct": correct, "acc": (correct / n) if (correct is not None and n) else None,
                    "acc_lo": alo, "acc_hi": ahi, "base_n": base_n, "base_k": base_k,
                    "base": base_k / base_n if base_n else None, "enough": n >= min_n, "since": lo})
    return out
