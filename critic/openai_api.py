"""A minimal stdlib client of the OpenAI Responses API for the critic (15.11., vlasnik: "OpenAI kao kritičar").

Endpoint POST https://api.openai.com/v1/responses (the Responses API; Chat Completions is not used):
  {"model", "instructions" (the system prompt), "input" (the user text), "text": {"format": {"type": "json_schema",
   "name", "strict": true, "schema"}} (Structured Outputs: the answer is JSON of that schema), "max_output_tokens",
   "reasoning": {"effort"} (only for reasoning models: gpt-5*, o*), "store": false (OpenAI keeps no copy)}
The answer: output[] items of type "message" whose content[] holds {"type": "output_text", "text"} (or "refusal");
usage {input_tokens, input_tokens_details.cached_tokens, output_tokens (reasoning tokens included, billed as output),
output_tokens_details.reasoning_tokens}; status "completed" | "incomplete" (incomplete_details.reason).

Models (env, 15.11. the owner's choice "Astra"): OPENAI_MODEL (the 15-min re-checks, default gpt-6-astra),
OPENAI_MODEL_LIVE (the comment on every real-money fill, default gpt-6-astra), OPENAI_MODEL_DEEP (the daily review and
the deep session, default gpt-6-astra), OPENAI_MODEL_CHEAP (default gpt-5.4-mini: re-checks and live comments once
more than CHEAP_AT of the day's budget is used, and whenever the strong model's most would not fit the budget).

Prices (USD per 1M tokens: input, cached input, output), standard tier, checked 15.11.2026. From the official model pages
(developers.openai.com/api/docs/models/<model>, seen through search; the pricing page itself was not reachable from the
build sandbox): gpt-5-mini 0.25 / 0.025 / 2.00, gpt-5.4 2.50 / 0.25 / 15.00, gpt-5.4-mini 0.75 / 0.075 / 4.50,
gpt-5.4-nano 0.20 / 0.02 / 1.25, gpt-5.5 5 / 0.50 / 30. gpt-6-astra 10 / 1.00 / 50 is the figure most third-party price
trackers give (eesel.ai, getdeploying, typingmind; one lists the batch rate 5 / 25): NOT verified on openai.com; correct
it with OPENAI_PRICES when the invoice says otherwise. Reasoning tokens are billed as output. A model not in PRICES is
priced UNKNOWN_PRICE (the most expensive tier, gpt-5.4-pro's), so the budget stops early instead of late;
OPENAI_PRICES (JSON {"model": [in, cached, out]}) adds or corrects a price without a deploy.

Function calling (the deep session, critic/deep.py): tools=[{"type": "function", "name", "parameters", "strict"}]; the
answer's output has {"type": "function_call", "call_id", "name", "arguments"} items; the next request resends the
conversation (store is false: no previous_response_id) with the calls (without their ids) and
{"type": "function_call_output", "call_id", "output"} items.

One retry on HTTP 429 / 5xx / a network error (Retry-After honoured, at most RETRY_MAX_S). The key is read from the
environment at call time and never logged, stored or put into an error text.
"""
import json
import os
import socket
import time
import urllib.error
import urllib.request

URL = "https://api.openai.com/v1/responses"
TIMEOUT_S = 120
RETRY_MAX_S = 20
MODEL = os.environ.get("OPENAI_MODEL") or "gpt-6-astra"            # the 15-min re-checks of open positions
MODEL_LIVE = os.environ.get("OPENAI_MODEL_LIVE") or "gpt-6-astra"  # the comment on every real-money fill
MODEL_DEEP = os.environ.get("OPENAI_MODEL_DEEP") or "gpt-6-astra"  # the daily review and the deep session
MODEL_CHEAP = os.environ.get("OPENAI_MODEL_CHEAP") or "gpt-5.4-mini"
CHEAP_AT = 0.70   # share of OPENAI_DAY_USD after which re-checks and live comments use MODEL_CHEAP

PRICES = {   # USD per 1M tokens: (input, cached input, output); a dated snapshot ("gpt-5-mini-2025-08-07") by prefix
    "gpt-6-astra": (10.00, 1.00, 50.00),
    "gpt-5.5": (5.00, 0.50, 30.00),
    "gpt-5.4": (2.50, 0.25, 15.00),
    "gpt-5.4-mini": (0.75, 0.075, 4.50),
    "gpt-5.4-nano": (0.20, 0.02, 1.25),
    "gpt-5.2": (1.75, 0.175, 14.00),
    "gpt-5.1": (1.25, 0.125, 10.00),
    "gpt-5": (1.25, 0.125, 10.00),
    "gpt-5-mini": (0.25, 0.025, 2.00),
    "gpt-5-nano": (0.05, 0.005, 0.40),
    "gpt-4.1": (2.00, 0.50, 8.00),
    "gpt-4.1-mini": (0.40, 0.10, 1.60),
    "gpt-4o-mini": (0.15, 0.075, 0.60),
}
UNKNOWN_PRICE = (30.00, 30.00, 180.00)


class ApiError(Exception):
    """A failed call: .status (HTTP code or None), .usage (tokens billed when the answer came but was unusable)."""
    def __init__(self, msg, status=None, usage=None, model=None):
        super().__init__(msg)
        self.status, self.usage, self.model = status, usage, model


def key():
    return (os.environ.get("OPENAI_API_KEY") or "").strip()


def has_key():
    return bool(key())


def _extra_prices():
    try:
        d = json.loads(os.environ.get("OPENAI_PRICES") or "{}")
        return {str(k): tuple(float(x) for x in v) for k, v in d.items() if isinstance(v, (list, tuple)) and len(v) == 3}
    except (ValueError, TypeError):
        return {}


def price(model):
    """(in, cached in, out) USD per 1M tokens: the longest PRICES key the model name starts with; UNKNOWN_PRICE else."""
    table = {**PRICES, **_extra_prices()}
    m = str(model or "")
    best = max((k for k in table if m == k or m.startswith(k + "-")), key=len, default=None)
    return table[best] if best else UNKNOWN_PRICE


def known(model):
    table = {**PRICES, **_extra_prices()}
    m = str(model or "")
    return any(m == k or m.startswith(k + "-") for k in table)


def cost(model, usage):
    """USD of one answer from its usage dict ({"in", "cached", "out"})."""
    pin, pcached, pout = price(model)
    u = usage or {}
    tin, cached, tout = int(u.get("in") or 0), int(u.get("cached") or 0), int(u.get("out") or 0)
    cached = min(cached, tin)
    return ((tin - cached) * pin + cached * pcached + tout * pout) / 1e6


def max_cost(model, chars_in, max_out):
    """The most one call can cost: the input estimated at 3 characters a token (JSON with numbers is denser than
    prose; an over-estimate is the safe side), every output token used."""
    pin, _c, pout = price(model)
    return (chars_in / 3.0 * pin + max_out * pout) / 1e6


def reasoning_model(model):
    m = str(model or "")
    return m.startswith("gpt-5") or m.startswith("gpt-6") or m[:2] in ("o1", "o3", "o4")


def usage_of(resp):
    u = (resp or {}).get("usage") or {}
    return {"in": int(u.get("input_tokens") or 0),
            "cached": int((u.get("input_tokens_details") or {}).get("cached_tokens") or 0),
            "out": int(u.get("output_tokens") or 0),
            "reasoning": int((u.get("output_tokens_details") or {}).get("reasoning_tokens") or 0)}


def output_text(resp):
    """(text, refusal) of a Responses answer: every output_text part of every message item, joined."""
    texts, refusal = [], None
    for item in (resp or {}).get("output") or []:
        if not isinstance(item, dict) or item.get("type") != "message":
            continue
        for part in item.get("content") or []:
            if not isinstance(part, dict):
                continue
            if part.get("type") == "output_text":
                texts.append(str(part.get("text") or ""))
            elif part.get("type") == "refusal":
                refusal = str(part.get("refusal") or "odbijeno")
    return "".join(texts), refusal


def _urlopen(req, timeout):   # the test seam: tests replace it, nothing here reaches the network then
    return urllib.request.urlopen(req, timeout=timeout)


def _err_text(raw):
    try:
        e = (json.loads(raw or b"{}") or {}).get("error") or {}
        return str(e.get("message") or e.get("code") or "")[:200]
    except (ValueError, AttributeError):
        return ""


def request(body, timeout=TIMEOUT_S, retries=1):
    """POST one body to the Responses API -> the answer as a dict. Raises ApiError (never with the key in it)."""
    k = key()
    if not k:
        raise ApiError("nema ključa")
    data = json.dumps(body, ensure_ascii=False).encode()
    last = None
    for attempt in range(retries + 1):
        req = urllib.request.Request(URL, data=data, method="POST",
                                     headers={"Authorization": f"Bearer {k}", "Content-Type": "application/json"})
        wait = 5.0
        try:
            with _urlopen(req, timeout) as r:
                return json.loads(r.read() or b"{}")
        except urllib.error.HTTPError as e:
            try:
                raw = e.read()
            except Exception:  # noqa: BLE001
                raw = b""
            last = ApiError(f"HTTP {e.code}: {_err_text(raw) or e.reason}", status=e.code, model=body.get("model"))
            if e.code != 429 and e.code < 500:
                raise last from None
            try:
                wait = float((e.headers or {}).get("Retry-After") or wait)
            except (TypeError, ValueError):
                pass
        except (urllib.error.URLError, socket.timeout, TimeoutError, ConnectionError) as e:
            reason = getattr(e, "reason", None) or e
            last = ApiError(f"mreža: {type(e).__name__}: {str(reason)[:120]}", model=body.get("model"))
        except ValueError as e:   # an answer that is not JSON
            raise ApiError(f"odgovor nije JSON ({e})"[:200], model=body.get("model")) from None
        if attempt < retries:
            time.sleep(min(max(wait, 1.0), RETRY_MAX_S))
    raise last


def body(model, instructions, user_text, schema, name, max_output_tokens, effort=None, tools=None):
    b = {"model": model, "instructions": instructions, "input": user_text, "store": False,
         "max_output_tokens": int(max_output_tokens),
         "text": {"format": {"type": "json_schema", "name": name, "strict": True, "schema": schema}}}
    if effort and reasoning_model(model):
        b["reasoning"] = {"effort": effort}
    if tools:
        b["tools"] = tools
    return b


def send(b, timeout=TIMEOUT_S):
    """request() with one adjustment: a model that refuses the reasoning parameter (HTTP 400 naming it) is asked
    again without it, at once (a 400 is not billed)."""
    try:
        return request(b, timeout=timeout)
    except ApiError as e:
        if e.status == 400 and "reasoning" in str(e).lower() and "reasoning" in b:
            b = {k: v for k, v in b.items() if k != "reasoning"}
            return request(b, timeout=timeout)
        raise


def function_calls(resp):
    """[{"call_id", "name", "arguments" (str)}] of an answer's function_call items."""
    return [{"call_id": it.get("call_id"), "name": it.get("name"), "arguments": it.get("arguments") or "{}"}
            for it in (resp or {}).get("output") or [] if isinstance(it, dict) and it.get("type") == "function_call"]


def call_json(model, instructions, user_text, schema, name, max_output_tokens=4000, effort="low", timeout=TIMEOUT_S):
    """One Structured Outputs call -> {"data": parsed JSON, "usage", "model", "cost_usd"}. Raises ApiError; an
    answer that came but is not usable (incomplete, refused, not JSON) carries its usage, so its cost is still booked."""
    resp = send(body(model, instructions, user_text, schema, name, max_output_tokens, effort), timeout=timeout)
    return parse_json(resp, model)


def parse_json(resp, model):
    """{"data", "usage", "model", "cost_usd"} of a final (JSON) answer; raises ApiError with the usage."""
    usage = usage_of(resp)
    used = resp.get("model") or model
    text, refusal = output_text(resp)
    if refusal:
        raise ApiError(f"model odbio: {refusal[:120]}", usage=usage, model=used)
    if resp.get("status") not in (None, "completed"):
        why = ((resp.get("incomplete_details") or {}).get("reason") or resp.get("status"))
        raise ApiError(f"odgovor nije dovršen ({why})", usage=usage, model=used)
    try:
        data = json.loads(text)
    except ValueError:
        raise ApiError("odgovor nije valjan JSON", usage=usage, model=used) from None
    return {"data": data, "usage": usage, "model": used, "cost_usd": cost(used, usage)}
