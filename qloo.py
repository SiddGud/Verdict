import hashlib
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request

BASE = "https://hackathon.api.qloo.com"
CACHE = os.path.join(os.path.dirname(__file__), "cache")
on_call = None  # optional callback(path, params, status, cached) for the agent trace


def _status(data):
    if "error" in data:
        return "error"
    res = data.get("results", {})
    return "ok" if any(res.get(k) for k in ("entities", "tags", "heatmap", "demographics")) else "empty"


def _report(path, params, data, cached):
    if on_call:
        on_call(path, params, _status(data), cached)


def _key():
    key = os.environ.get("QLOO_API_KEY")
    if key:
        return key
    with open(os.path.join(os.path.dirname(__file__), ".env")) as f:
        for line in f:
            if line.startswith("QLOO_API_KEY="):
                return line.strip().split("=", 1)[1]


def get(path, **params):
    """GET a Qloo endpoint, cached on disk so repeat runs cost no API calls."""
    url = BASE + path + "?" + urllib.parse.urlencode(params)
    name = os.path.join(CACHE, hashlib.md5(url.encode()).hexdigest() + ".json")
    if os.path.exists(name):
        with open(name) as f:
            data = json.load(f)
        _report(path, params, data, True)
        return data
    req = urllib.request.Request(url, headers={"X-Api-Key": _key()})
    for attempt in range(4):
        try:
            data = json.load(urllib.request.urlopen(req, timeout=90))
            break
        except urllib.error.HTTPError as e:
            if e.code in (429, 500, 502, 503) and attempt < 3:
                time.sleep(2 ** attempt)
                continue
            data = {"error": e.code, "body": e.read()[:300].decode()}
            _report(path, params, data, False)
            return data
        except (TimeoutError, urllib.error.URLError):
            if attempt == 3:
                data = {"error": "timeout"}
                _report(path, params, data, False)
                return data
            time.sleep(2 ** attempt)
    os.makedirs(CACHE, exist_ok=True)
    with open(name, "w") as f:
        json.dump(data, f)
    _report(path, params, data, False)
    return data


def results(data, field):
    return data.get("results", {}).get(field, [])
