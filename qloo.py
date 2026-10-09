import hashlib
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request

BASE = "https://hackathon.api.qloo.com"
CACHE = os.path.join(os.path.dirname(__file__), "cache")


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
            return json.load(f)
    req = urllib.request.Request(url, headers={"X-Api-Key": _key()})
    for attempt in range(4):
        try:
            data = json.load(urllib.request.urlopen(req, timeout=90))
            break
        except urllib.error.HTTPError as e:
            if e.code in (429, 500, 502, 503) and attempt < 3:
                time.sleep(2 ** attempt)
                continue
            return {"error": e.code, "body": e.read()[:300].decode()}
        except (TimeoutError, urllib.error.URLError):
            if attempt == 3:
                return {"error": "timeout"}
            time.sleep(2 ** attempt)
    os.makedirs(CACHE, exist_ok=True)
    with open(name, "w") as f:
        json.dump(data, f)
    return data


def results(data, field):
    return data.get("results", {}).get(field, [])
