"""Telegram out of every calculation (19.11., vlasnik: "Makni Telegram KOL-ove iz izračuna. Ali zadrži popis kanala,
osvježen jednom tjedno, samo za broj pratitelja.").

A Telegram channel's call is stored in kol.db calls with handle 'tg:<channel>' (kol/collect.from_telegram until
19.11.; nothing creates new ones since). The stored rows stay (nothing is deleted); every calculation that turns a
call into a number, a ranking, a signal or a trade leaves them out through this one predicate:

    is_tg(handle)      True for 'tg:<channel>' (any case)
    sql(col)           the SQL condition "this row is NOT a Telegram call" for a handle column
    drop(handles)      the handles without Telegram ones

X influencers and wallet pseudo-calls ('w:') are untouched. The channel list itself (tg.db channels) stays for the
weekly follower count (tg/pratitelji.py) and the informational page /telegram-kanali (ui/tgkanali.py).
"""
PREFIX = "tg:"
SINCE = "2026-11-19"


def is_tg(handle):
    return str(handle or "").strip().lstrip("@").lower().startswith(PREFIX)


def sql(col="handle"):
    """SQL: the row's caller is not a Telegram channel (NULL handles stay, as before)."""
    return f"COALESCE({col}, '') NOT LIKE '{PREFIX}%'"


def drop(handles):
    return [h for h in (handles or []) if not is_tg(h)]
