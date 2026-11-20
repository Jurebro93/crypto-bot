"""Pages the owner removed on 19.11. (vlasnik: "Makni event i zadnji sken ... Makni 'za whatsapp' I 'ideje' jer je
nepotrebno. Makni natjecanje."). Their addresses never 404: a GET answers 303 to the most relevant living page; a
form sent to them does nothing (gone()). Data and the engines underneath stay (league.db accounts, copy, ideas table,
calendar.db); see the report of that commit for the inventory.

  /events, /watch       Eventi: the calendar and the event tokens (microcap launches matched to a topic)  -> /tokens
  /radar                Zadnji sken: the hype scanner's last pass (off since 15.11.)                      -> /tokens
  /whatsapp             Za WhatsApp: the picture and text for the group (the daily digest job stays)     -> /pregled
  /prijedlozi           Ideje za alat: users' ideas (league.db ideas stays)                               -> /pregled
  /natjecanje, /natjecanje/<x>, /copy-trading
                        Natjecanje: users' own demo accounts, leaderboard, copy on that account           -> /pregled
"""
GET = {"/events": "/tokens", "/watch": "/tokens", "/radar": "/tokens", "/whatsapp": "/pregled",
       "/prijedlozi": "/pregled", "/natjecanje": "/pregled", "/copy-trading": "/pregled"}
PREFIX = (("/natjecanje/", "/pregled"), ("/prijedlozi/", "/pregled"), ("/whatsapp/", "/pregled"))
# POSTs that still work: invite links (an admin's tool, league/roles POSTS) moved with the invite block to /zahtjevi
KEEP_POST = ("/natjecanje/pozivnica/",)


def redirect(path):
    """Where a GET of a removed page goes, else None."""
    if path in GET:
        return GET[path]
    for pre, to in PREFIX:
        if path.startswith(pre):
            return to
    return None


def gone(path):
    """(code, location) for a POST to a removed page: personal demo buys / sells / copy / DCA go back to Pregled
    without doing anything (303); ideas and the WhatsApp "sent" ping are 410. None = a POST that still works."""
    if path.startswith(KEEP_POST):
        return None
    if path.startswith(("/natjecanje/",)):
        return 303, "/pregled"
    if path.startswith(("/prijedlozi/", "/whatsapp/")):
        return 410, None
    return None
