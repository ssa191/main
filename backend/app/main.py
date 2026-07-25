"""Application entry point.

Creates the FastAPI app, registers every module router, builds the database
schema on startup, seeds demo data if the database is empty, and serves the
single-page frontend.
"""
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .config import settings
from .database import Base, SessionLocal, engine
from .routers import (
    accounting,
    auth,
    crm,
    dashboard,
    hr,
    inventory,
    purchasing,
    sales,
)
from .seed import seed_if_empty

app = FastAPI(title=settings.app_name, version="1.0.0")

for module in (auth, dashboard, inventory, sales, purchasing, accounting, hr, crm):
    app.include_router(module.router)


@app.on_event("startup")
def on_startup() -> None:
    Base.metadata.create_all(bind=engine)
    with SessionLocal() as db:
        seed_if_empty(db)


@app.get("/api/health")
def health() -> dict:
    return {"status": "ok", "app": settings.app_name, "company": settings.company_name}


# ---- Static frontend --------------------------------------------------------
STATIC_DIR = Path(__file__).resolve().parent.parent / "static"
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/")
def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")
