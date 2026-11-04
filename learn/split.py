"""Time split BEFORE any fit (audit 4.11. C04/C12, R4).

train = the older part, validation = the newer part; training rows whose label window (decision + horizon) reaches
into the validation period are dropped (purge), so no outcome seen in training overlaps a validation decision.
The locked holdout week (learn/config.json model.holdout) is never in either part: it is opened once, later.
Everything learned (weights, bins, scaling, thresholds) comes from train only; validation only says yes/no.
"""


def by_time(rows, val_share=0.3, horizon_s=24 * 3600, key="ts"):
    """(train, val) from rows with a decision time `key`. Empty lists when there are too few rows to split."""
    rows = sorted(rows, key=lambda r: r[key])
    if len(rows) < 4:
        return [], []
    cut_i = int(len(rows) * (1 - val_share))
    val = rows[cut_i:]
    start = val[0][key]
    train = [r for r in rows[:cut_i] if r[key] + horizon_s <= start]
    return train, val
