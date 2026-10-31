"""Verdict web server: the festival court, the city desk and their APIs.

Keys stay in .env or server environment variables. Qloo, Ticketmaster and Last.fm replies are cached privately in
cache/ (git-ignored); model calls happen only for plain-word booker orders the patterns cannot read, the openers
and tour tools, and the model-alone baseline.

uvicorn app:app --port 8000
"""
import io
import os
import tarfile
import urllib.request

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

import qloo
from clash.api import router as clash_router
from clash.city_api import router as city_router

ROOT = os.path.dirname(__file__)


def fetch_cache():
    """On a host, fill the cache once from a private Hugging Face dataset (CACHE_DATASET, read with HF_TOKEN), so the
    recorded court sittings and Qloo replies never sit in the public repo. Locally, with no CACHE_DATASET, nothing
    happens. If the download fails the site still starts and answers from the live APIs, only slower."""
    dataset, token = os.environ.get("CACHE_DATASET"), os.environ.get("HF_TOKEN")
    have = os.listdir(qloo.CACHE) if os.path.isdir(qloo.CACHE) else []
    if not dataset or not token or any(n.startswith("council_") for n in have):
        return
    url = f"https://huggingface.co/datasets/{dataset}/resolve/main/cache.tar.gz"
    try:
        data = urllib.request.urlopen(urllib.request.Request(url, headers={"Authorization": f"Bearer {token}"}), timeout=300).read()
        os.makedirs(qloo.CACHE, exist_ok=True)
        with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as t:
            t.extractall(qloo.CACHE, filter="data")
        print(f"cache ready: {len(os.listdir(qloo.CACHE))} entries from {dataset}", flush=True)
    except Exception as e:
        print(f"cache not fetched ({type(e).__name__}: {e}); answering from the live APIs", flush=True)


fetch_cache()

app = FastAPI(title="Verdict")
app.mount("/static", StaticFiles(directory=os.path.join(ROOT, "static")), name="static")
app.include_router(clash_router)
app.include_router(city_router)


@app.api_route("/", methods=["GET", "HEAD"])  # HEAD: uptime monitors check with it
@app.get("/v2")
def index():
    """The site: the festival court first, then pages for fans, promoters and the evidence."""
    return FileResponse(os.path.join(ROOT, "static", "site", "index.html"), headers={"Cache-Control": "no-cache"})


@app.get("/classic")
def classic():
    """The earlier one-page site, kept as the backup."""
    return FileResponse(os.path.join(ROOT, "static", "court.html"), headers={"Cache-Control": "no-cache"})


@app.get("/clash")
def war_room():
    """The first version of the page (a plain war-room), kept for reference."""
    return FileResponse(os.path.join(ROOT, "static", "clash.html"))


@app.get("/llms.txt")
@app.get("/llms-full.txt")
@app.get("/llms.md")
def llms():
    """The whole project for readers that are language models: features, architecture, decisions and every test."""
    return FileResponse(os.path.join(ROOT, "llms.txt"), media_type="text/plain; charset=utf-8")


@app.api_route("/health", methods=["GET", "HEAD"])
def health():
    return {"ok": True}
