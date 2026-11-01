"""Automatic send of the digest to the WhatsApp group through a gateway service. Off until its settings are on Render.

WhatsApp's official API (Meta / Twilio) cannot post into an ordinary group, so this uses a gateway that runs a
WhatsApp account on a separate phone number, and that number is a member of the group:

  WHATSAPP_PROVIDER   whapi (whapi.cloud) or greenapi (green-api.com)
  WHATSAPP_TOKEN      the service's API token
  WHATSAPP_GROUP_ID   the group's id, e.g. 120363012345678901@g.us (the service lists the groups of the number)
  WHATSAPP_INSTANCE_ID  greenapi only: idInstance
  WHATSAPP_API_URL    optional: the service's own address if it differs from the default
  WHATSAPP_HOUR       hour (Zagreb) of the daily digest, default 19

Never the owner's private number: gateways run an unofficial client and WhatsApp may block such a number.
One message a day keeps that risk low.
"""
import json
import os
import urllib.request

PROVIDERS = {"whapi": "Whapi.cloud", "greenapi": "Green API"}


def provider():
    p = (os.environ.get("WHATSAPP_PROVIDER") or "").strip().lower().replace("-", "").replace("_", "")
    return p if p in PROVIDERS else None


def missing():
    """Settings still to add on Render before the automatic send works (empty list = ready)."""
    p = provider()
    need = ["WHATSAPP_PROVIDER"] if not p else []
    need += [k for k in ("WHATSAPP_TOKEN", "WHATSAPP_GROUP_ID") if not os.environ.get(k)]
    if p == "greenapi" and not os.environ.get("WHATSAPP_INSTANCE_ID"):
        need.append("WHATSAPP_INSTANCE_ID")
    return need


def configured():
    return not missing()


def request(text):
    """(url, headers, json body) of the send call for the configured provider."""
    p, token, group = provider(), os.environ.get("WHATSAPP_TOKEN", ""), os.environ.get("WHATSAPP_GROUP_ID", "")
    api = (os.environ.get("WHATSAPP_API_URL") or "").rstrip("/")
    if p == "whapi":
        return ((api or "https://gate.whapi.cloud") + "/messages/text",
                {"Authorization": f"Bearer {token}"}, {"to": group, "body": text})
    if p == "greenapi":
        inst = os.environ.get("WHATSAPP_INSTANCE_ID", "")
        return (f"{api or 'https://api.green-api.com'}/waInstance{inst}/sendMessage/{token}", {},
                {"chatId": group, "message": text})
    raise RuntimeError("WhatsApp slanje nije postavljeno: " + ", ".join(missing()))


def send(text, timeout=30):
    if missing():
        raise RuntimeError("WhatsApp slanje nije postavljeno: " + ", ".join(missing()))
    url, headers, body = request(text)
    req = urllib.request.Request(url, data=json.dumps(body).encode("utf-8"), method="POST",
                                 headers={"Content-Type": "application/json", "Accept": "application/json", **headers})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        out = r.read(2000).decode("utf-8", "replace")
    return f"{PROVIDERS[provider()]}: {out[:200]}"
