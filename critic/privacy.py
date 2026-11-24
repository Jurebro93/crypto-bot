"""What leaves the server for OpenAI (hard rules, 15.11.): never an environment variable's name or value, an API key,
the owner's wallet, the PumpPortal data wallet, a server host name, an internal service or file name, personal data.
Token mints, symbols and public market numbers are fine.

The payloads are built from numbers and our own words, so none of that should be in them; scrub() is the second line:
it runs over the final text right before the call and
  - replaces every value of a sensitive environment variable (names with KEY, TOKEN, SECRET, PASS, PRIVATE, DSN,
    WEBHOOK, SESSION, AUTH, COOKIE, URL, HOST, WALLET, ADDR, PHONE, MAIL, USER) of 6+ characters, and those names,
  - replaces every Solana address that is not one of the allowed token mints ("[adresa]": followed wallets, the owner's),
  - replaces host names (*.onrender.com, this machine's name), disk paths and internal file names ("[interno]").
leaks() says what would still be there; the caller refuses to send when it finds anything.
"""
import os
import re
import socket

SENSITIVE = re.compile(r"KEY|TOKEN|SECRET|PASS|PRIVATE|DSN|WEBHOOK|SESSION|AUTH|COOKIE|URL|HOST|WALLET|ADDR|PHONE|MAIL|"
                       r"USER|OWNER", re.I)
B58 = re.compile(r"\b[1-9A-HJ-NP-Za-km-z]{32,44}\b")
HOSTS = re.compile(r"\b[\w.-]+\.(?:onrender\.com|render\.com|internal|local)\b", re.I)
PATHS = re.compile(r"(?:/var/data|/opt/render|/home/\w+|/etc|/tmp)[\w./-]*")
FILES = re.compile(r"\b[\w-]+\.(?:py|db|sh|json|log)\b")


def secret_values(env=None):
    env = os.environ if env is None else env
    vals = set()
    for k, v in env.items():
        if SENSITIVE.search(k) and v and len(v.strip()) >= 6:
            vals.add(v.strip())
    return vals


def secret_names(env=None):
    env = os.environ if env is None else env
    return {k for k in env if SENSITIVE.search(k) and len(k) >= 6}


def owner_wallets(tcon=None):
    """The owner's wallet addresses we know of (env public key, the saved one); read-only, never derived from a key."""
    out = {v for v in (os.environ.get("SOLANA_PUBLIC_KEY"),) if v}
    if tcon is not None:
        try:
            from trade import settings
            w = settings.raw(tcon).get("wallet_pub")
            if w:
                out.add(str(w))
        except Exception:  # noqa: BLE001
            pass
    return out


def scrub(text, allowed_mints=(), env=None, extra=()):
    """The text with every secret, foreign address, host, path and internal file name replaced."""
    s = str(text or "")
    for v in sorted(secret_values(env) | {x for x in extra if x}, key=len, reverse=True):
        s = s.replace(v, "[skriveno]")
    for name in sorted(secret_names(env), key=len, reverse=True):
        s = re.sub(rf"\b{re.escape(name)}\b", "[skriveno]", s)
    allowed = set(allowed_mints or ())
    s = B58.sub(lambda m: m.group(0) if m.group(0) in allowed else "[adresa]", s)
    s = HOSTS.sub("[interno]", s)
    try:
        host = socket.gethostname()
    except OSError:
        host = ""
    if host and len(host) >= 6:
        s = s.replace(host, "[interno]")
    s = PATHS.sub("[interno]", s)
    s = FILES.sub("[interno]", s)
    return s


def leaks(text, allowed_mints=(), env=None, extra=()):
    """[what kind of private thing is still in the text] (empty = safe to send)."""
    s = str(text or "")
    out = []
    if any(v in s for v in secret_values(env) | {x for x in extra if x}):
        out.append("tajna vrijednost")
    if any(re.search(rf"\b{re.escape(n)}\b", s) for n in secret_names(env)):
        out.append("ime varijable okoline")
    allowed = set(allowed_mints or ())
    if any(m not in allowed for m in B58.findall(s)):
        out.append("adresa")
    if HOSTS.search(s):
        out.append("host")
    return out
