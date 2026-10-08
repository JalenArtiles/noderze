"""FastAPI entry point. Local-first: bind to 127.0.0.1 and require the X-Agent-Token header."""
from __future__ import annotations

import hmac
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

import threading

from . import migrations, scheduler, selfupdate
from .config import settings
from .db import init_db
from .routers import apply, core, focus
from .workflows import mark_interrupted_runs

VERSION = "3.2"


@asynccontextmanager
async def lifespan(_: FastAPI):
    init_db()
    mark_interrupted_runs()
    threading.Thread(target=migrations.run, name="noderze-migrations", daemon=True).start()
    scheduler.reload()
    selfupdate.start()
    yield
    scheduler.shutdown()


app = FastAPI(title="Noderze", version=VERSION, lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=[o.strip() for o in settings.cors_origins.split(",")],
                   allow_methods=["*"], allow_headers=["*"])


@app.middleware("http")
async def token_auth(request: Request, call_next):
    if request.url.path.startswith("/api") and request.method != "OPTIONS":
        supplied = request.headers.get("x-agent-token") or request.query_params.get("token") or ""
        if not hmac.compare_digest(supplied, settings.agent_token):
            return JSONResponse({"detail": "Missing or wrong X-Agent-Token"}, status_code=401)
    return await call_next(request)


app.include_router(core.router)
app.include_router(apply.router)
app.include_router(focus.router)


@app.get("/health")
def health():
    return {"ok": True, "version": VERSION, "managed": selfupdate.managed()}
