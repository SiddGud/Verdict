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
    """Environment variables first (the host's settings), then .env for local development."""
    vals = dict(os.environ)
    path = os.path.join(ROOT, ".env")
    if os.path.exists(path):
        with open(path) as f:
            for line in f:
                if "=" in line and not line.startswith("#"):
                    k, v = line.strip().split("=", 1)
                    vals.setdefault(k, v)
    return vals


ENV = _env()
PROVIDER = ENV.get("LLM_PROVIDER", "kie")
MODEL = ENV.get("LLM_MODEL", "gpt-6-astra")
# Optional outage fallback (Azure OpenAI, v1 Responses API). Used only when the primary call fails or
# times out, and every fallback is labelled in the call's meta so the trace shows it.
FALLBACK_URL = ENV.get("AZURE_OPENAI_ENDPOINT", "").rstrip("/")   # e.g. https://<name>.openai.azure.com/openai/v1
FALLBACK_KEY = ENV.get("AZURE_OPENAI_API_KEY", "")
FALLBACK_MODEL = ENV.get("AZURE_OPENAI_DEPLOYMENT", "gpt-5-mini")


class LLMError(Exception):
    pass


def _post(url, headers, body, timeout=180, deadline=None):
    """POST with retries on 429/5xx and connection errors, but never past `deadline` (epoch seconds).
    A timeout is not retried: a slow provider stays slow, so the caller falls back instead."""
    req = urllib.request.Request(url, data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json", **headers})
    for attempt in range(3):
        left = timeout if deadline is None else deadline - time.time()
        if left <= 1:
            raise LLMError("timed out")
        try:
            return json.load(urllib.request.urlopen(req, timeout=min(timeout, left)))
        except urllib.error.HTTPError as e:
            msg = e.read()[:400].decode(errors="replace")
            if e.code in (429, 500, 502, 503) and attempt < 2:
                time.sleep(3 * (attempt + 1))
                continue
            raise LLMError(f"HTTP {e.code}: {msg}")
        except TimeoutError:
            raise LLMError("timed out")
        except urllib.error.URLError as e:
            if "timed out" in str(e.reason) or attempt == 2:
                raise LLMError(str(e))
            time.sleep(3)


def complete_json(instructions, prompt, check=None, effort="low", retries=1, timeout=120):
    """Ask for JSON in the instructions and validate in code.

    Kie's strict json_schema mode takes about 90 s per call versus about 10 s this way.
    `check(obj)` should raise on invalid content; one retry feeds the error back.
    """
    note = ""
    for attempt in range(retries + 1):
        try:
            text, meta = complete(instructions + "\nReply with JSON only, no prose, no code fences.",
                                  prompt + note, effort=effort, timeout=timeout)
        except LLMError as e:  # a slow or failed call gets one more try, like a bad reply
            note = ""
            if attempt == retries:
                raise
            continue
        try:
            obj = json.loads(text.strip().removeprefix("```json").removesuffix("```"))
            if check:
                check(obj)
            meta["attempts"] = attempt + 1
            return obj, meta
        except Exception as e:
            note = f"\n\nYour previous reply was rejected: {e}. Return corrected JSON."
    raise LLMError(f"invalid JSON after {retries + 1} attempts: {note}")


def complete(instructions, prompt, effort="low", max_output=4000, timeout=90):
    """Return (text, meta). Tries the primary provider within `timeout` seconds, then the fallback if set."""
    if PROVIDER != "kie":
        raise LLMError(f"provider {PROVIDER} not wired yet")
    t = time.time()
    try:
        # Streamed under the hood: Kie sends keep-alives while it reasons, so only real silence (60 s) or the
        # total cap ends a call, instead of a fixed wait that cut off slow but healthy replies.
        return stream_complete(instructions, prompt, lambda d: None, effort=effort, max_output=max_output,
                               idle_timeout=60, total_timeout=timeout)
    except LLMError as e:
        if not (FALLBACK_URL and FALLBACK_KEY):
            raise
        text, meta = _azure(instructions, prompt, effort, max_output, deadline=time.time() + timeout)
        meta.update(fallback=True, primary_error=str(e)[:120], seconds=round(time.time() - t, 1))
        return text, meta


def _text(d):
    return "".join(c.get("text", "") for o in d.get("output", []) for c in (o.get("content") or [])
                   if c.get("type") in ("output_text", "text"))


def _kie(instructions, prompt, effort, max_output, deadline):
    body = {
        "model": MODEL, "instructions": instructions, "input": prompt, "stream": False,
        "reasoning": {"effort": effort}, "max_output_tokens": max_output,
    }
    t = time.time()
    d = _post("https://api.kie.ai/codex/v1/responses", {"Authorization": "Bearer " + ENV["KIE_API_KEY"]}, body,
              deadline=deadline)
    if d.get("status") != "completed":
        raise LLMError(f"not completed: {json.dumps(d)[:400]}")
    return _text(d), {"seconds": round(time.time() - t, 1), "credits": d.get("credits_consumed"),
                      "tokens_in": d.get("usage", {}).get("input_tokens"),
                      "tokens_out": d.get("usage", {}).get("output_tokens"), "model": d.get("model")}


def _azure(instructions, prompt, effort, max_output, deadline):
    body = {"model": FALLBACK_MODEL, "instructions": instructions, "input": prompt,
            "reasoning": {"effort": effort}, "max_output_tokens": max_output}
    t = time.time()
    d = _post(FALLBACK_URL + "/responses", {"api-key": FALLBACK_KEY}, body, deadline=deadline)
    if d.get("status") not in (None, "completed"):
        raise LLMError(f"fallback not completed: {json.dumps(d)[:400]}")
    return _text(d), {"seconds": round(time.time() - t, 1), "credits": 0,
                      "tokens_in": d.get("usage", {}).get("input_tokens"),
                      "tokens_out": d.get("usage", {}).get("output_tokens"), "model": d.get("model", FALLBACK_MODEL)}


def stream_complete(instructions, prompt, on_delta, effort="low", max_output=4000, idle_timeout=60, total_timeout=180):
    """Streaming call to the primary provider. on_delta(text) receives text as it arrives.
    idle_timeout: longest silence allowed (Kie sends keep-alives while it reasons); total_timeout: hard cap."""
    body = {"model": MODEL, "instructions": instructions, "input": prompt, "stream": True,
            "reasoning": {"effort": effort}, "max_output_tokens": max_output}
    req = urllib.request.Request("https://api.kie.ai/codex/v1/responses", data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json", "Authorization": "Bearer " + ENV["KIE_API_KEY"]})
    t, parts, final, event = time.time(), [], None, None
    try:
        with urllib.request.urlopen(req, timeout=idle_timeout) as r:
            for raw in r:
                if time.time() - t > total_timeout:
                    raise LLMError("timed out")
                line = raw.decode(errors="replace").strip()
                if line.startswith("event:"):
                    event = line[6:].strip()
                    continue
                if not line.startswith("data:"):
                    continue
                try:
                    d = json.loads(line[5:])
                except ValueError:
                    continue
                kind = d.get("type") or event
                if kind == "response.output_text.delta":
                    parts.append(d.get("delta", ""))
                    on_delta(d.get("delta", ""))
                elif kind in ("response.completed", "response.done"):
                    final = d.get("response", {})
                elif kind in ("error", "response.failed"):
                    raise LLMError(f"stream error: {json.dumps(d)[:300]}")
    except urllib.error.HTTPError as e:
        raise LLMError(f"HTTP {e.code}: {e.read()[:300].decode(errors='replace')}")
    except (TimeoutError, urllib.error.URLError) as e:
        raise LLMError(f"timed out ({e})")
    text = "".join(parts)
    if not text:
        raise LLMError("stream ended without text")
    final = final or {}
    usage = final.get("usage", {})
    # Kie reports no credits on streams; estimate from tokens with rates fitted to its non-stream replies.
    est = round(0.000573 * (usage.get("input_tokens") or 0) + 0.0028 * (usage.get("output_tokens") or 0), 2)
    return text, {"seconds": round(time.time() - t, 1), "credits": final.get("credits_consumed") or est,
                  "credits_estimated": not final.get("credits_consumed"),
                  "tokens_in": final.get("usage", {}).get("input_tokens"),
                  "tokens_out": final.get("usage", {}).get("output_tokens"), "model": final.get("model", MODEL),
                  "streamed": True}


def stream_response(body, idle_timeout=60, total_timeout=150):
    """Streamed Responses call for tool use: returns {"output": [items], "credits": float}.
    Items are collected from output_item.done events, so function calls arrive whole."""
    body = {**body, "stream": True}
    req = urllib.request.Request("https://api.kie.ai/codex/v1/responses", data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json", "Authorization": "Bearer " + ENV["KIE_API_KEY"]})
    t, items, final, event = time.time(), [], {}, None
    try:
        with urllib.request.urlopen(req, timeout=idle_timeout) as r:
            for raw in r:
                if time.time() - t > total_timeout:
                    raise LLMError("timed out")
                line = raw.decode(errors="replace").strip()
                if line.startswith("event:"):
                    event = line[6:].strip(); continue
                if not line.startswith("data:"):
                    continue
                try:
                    d = json.loads(line[5:])
                except ValueError:
                    continue
                kind = d.get("type") or event
                if kind == "response.output_item.done":
                    items.append(d.get("item", {}))
                elif kind in ("response.completed", "response.done"):
                    final = d.get("response", {})
                elif kind in ("error", "response.failed"):
                    raise LLMError(f"stream error: {json.dumps(d)[:300]}")
    except urllib.error.HTTPError as e:
        raise LLMError(f"HTTP {e.code}: {e.read()[:300].decode(errors='replace')}")
    except (TimeoutError, urllib.error.URLError) as e:
        raise LLMError(f"timed out ({e})")
    usage = final.get("usage", {})
    est = round(0.000573 * (usage.get("input_tokens") or 0) + 0.0028 * (usage.get("output_tokens") or 0), 2)
    return {"output": items, "credits": final.get("credits_consumed") or est, "status": "completed"}
