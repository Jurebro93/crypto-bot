"""Which of an event's tokens is most likely to pump when the event happens.

score_token() is pure (rows in, score + reasons out); load() reads what other modules already
collected (calendar.db event_tokens, rug.db, watch.db, kol.db), so ranking costs no API calls.
"""
