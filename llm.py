"""One interface for every model provider. Pick the provider with LLM_PROVIDER in .env.

Kie (default): OpenAI Responses-compatible endpoint serving GPT-6 Astra.
Notes from testing: Kie injects a long Codex system prompt unless `instructions` is set,
so we always send our own; Kie can report errors with HTTP 200, so we check the body.
"""
import json
import os
import time
import urllib.error
import urllib.request

ROOT = os.path.dirname(__file__)


def _env():
    vals = dict(os.environ)
    with open(os.path.join(ROOT, ".env")) as f:
        for line in f:
            if "=" in line and not line.startswith("#"):
                k, v = line.strip().split("=", 1)
                vals.setdefault(k, v)
    return vals


ENV = _env()
PROVIDER = ENV.get("LLM_PROVIDER", "kie")
MODEL = ENV.get("LLM_MODEL", "gpt-6-astra")


class LLMError(Exception):
    pass


def _post(url, headers, body, timeout=180):
    req = urllib.request.Request(url, data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json", **headers})
    for attempt in range(3):
        try:
            return json.load(urllib.request.urlopen(req, timeout=timeout))
        except urllib.error.HTTPError as e:
            msg = e.read()[:400].decode(errors="replace")
            if e.code in (429, 500, 502, 503) and attempt < 2:
                time.sleep(3 * (attempt + 1))
                continue
            raise LLMError(f"HTTP {e.code}: {msg}")
        except (TimeoutError, urllib.error.URLError) as e:
            if attempt == 2:
                raise LLMError(str(e))
            time.sleep(3)


def complete_json(instructions, prompt, check=None, effort="low", retries=1):
    """Ask for JSON in the instructions and validate in code.

    Kie's strict json_schema mode takes about 90 s per call versus about 10 s this way.
    `check(obj)` should raise on invalid content; one retry feeds the error back.
    """
    note = ""
    for attempt in range(retries + 1):
        text, meta = complete(instructions + "\nReply with JSON only, no prose, no code fences.",
                              prompt + note, effort=effort)
        try:
            obj = json.loads(text.strip().removeprefix("```json").removesuffix("```"))
            if check:
                check(obj)
            meta["attempts"] = attempt + 1
            return obj, meta
        except Exception as e:
            note = f"\n\nYour previous reply was rejected: {e}. Return corrected JSON."
    raise LLMError(f"invalid JSON after {retries + 1} attempts: {note}")


def complete(instructions, prompt, effort="low", max_output=4000):
    """Return (text, meta)."""
    if PROVIDER != "kie":
        raise LLMError(f"provider {PROVIDER} not wired yet")
    body = {
        "model": MODEL, "instructions": instructions, "input": prompt, "stream": False,
        "reasoning": {"effort": effort}, "max_output_tokens": max_output,
    }
    t = time.time()
    d = _post("https://api.kie.ai/codex/v1/responses", {"Authorization": "Bearer " + ENV["KIE_API_KEY"]}, body)
    if d.get("status") != "completed":
        raise LLMError(f"not completed: {json.dumps(d)[:400]}")
    text = "".join(c.get("text", "") for o in d.get("output", []) for c in (o.get("content") or [])
                   if c.get("type") in ("output_text", "text"))
    meta = {"seconds": round(time.time() - t, 1), "credits": d.get("credits_consumed"),
            "tokens_in": d.get("usage", {}).get("input_tokens"),
            "tokens_out": d.get("usage", {}).get("output_tokens"), "model": d.get("model")}
    return text, meta
