"""Clash Court web server: the festival court, the city desk and their APIs.

Keys stay in .env or server environment variables. Qloo, Ticketmaster and Last.fm replies are cached privately in
cache/ (git-ignored); model calls happen only for plain-word booker orders the patterns cannot read, the openers
and tour tools, and the model-alone baseline.

uvicorn app:app --port 8000
"""
import os

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from clash.api import router as clash_router
from clash.city_api import router as city_router

ROOT = os.path.dirname(__file__)

app = FastAPI(title="Clash Court")
app.mount("/static", StaticFiles(directory=os.path.join(ROOT, "static")), name="static")
app.include_router(clash_router)
app.include_router(city_router)


@app.get("/")
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


@app.get("/health")
def health():
    return {"ok": True}
