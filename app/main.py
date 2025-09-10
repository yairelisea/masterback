# app/main.py
from __future__ import annotations

import os
from fastapi import FastAPI, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse
from fastapi.routing import APIRoute
from .routers import reports
from app.routers import search_local
from .routers import analyses_extra

# Base y engine (para crear tablas/índices en startup)
from .models import Base
from .db import engine
from .scheduler import start_scheduler

# Routers (ajusta si alguno no existe en tu proyecto)
from .routers import campaigns, sources, ingest, analyses, news, ai_analysis, auth, admin_tools


# ---------- Operation IDs únicos (evita warnings en /docs) ----------
def custom_generate_unique_id(route: APIRoute) -> str:
    tag = (route.tags[0] if route.tags else "default").lower().replace(" ", "_")
    method = list(route.methods)[0].lower()
    path = route.path.replace("/", "_").strip("_").replace("{", "").replace("}", "")
    return f"{tag}_{method}_{path}"


# ---------- FastAPI app ----------
app = FastAPI(
    title="BBX API",
    version="0.2.0",
    generate_unique_id_function=custom_generate_unique_id,
)


# ---------- CORS ----------
# Dominios permitidos por defecto (prod y dev)
default_allowed = [
    "https://app.blackboxmonitor.com",  # Netlify custom domain
    "http://localhost:5173",            # Vite local
]

# También permitimos todos los subdominios *.netlify.app (deploy previews)
allow_origin_regex = r"https://.*\.netlify\.app"

# Si defines ALLOWED_ORIGINS en Render, se usa eso (coma-separado)
raw_origins = os.getenv("ALLOWED_ORIGINS", "")
if raw_origins.strip():
    allowed_origins = [o.strip() for o in raw_origins.split(",") if o.strip()]
else:
    allowed_origins = default_allowed

app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_origin_regex=allow_origin_regex,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------- Rutas base ----------
@app.get("/health", tags=["meta"])
async def health():
    return {"ok": True}

@app.get("/", include_in_schema=False)
async def root():
    return RedirectResponse(url="/docs")

@app.get("/favicon.ico", include_in_schema=False)
async def favicon_empty():
    return Response(status_code=204)


# ---------- Routers ----------
# Auth primero para tener login/registro
app.include_router(auth.router, prefix="/auth", tags=["auth"])

# Módulos del app
app.include_router(campaigns.router, tags=["campaigns"])
app.include_router(sources.router, prefix="/sources", tags=["sources"])
app.include_router(ingest.router, prefix="/ingest", tags=["ingest"])
app.include_router(analyses.router, prefix="/analyses", tags=["analyses"])
app.include_router(news.router, prefix="/news", tags=["news"])
app.include_router(ai_analysis.router, tags=["ai"])
app.include_router(reports.router)
app.include_router(search_local.router, tags=["search-local"])
app.include_router(analyses_extra.router)
app.include_router(admin_tools.router)

# ---------- Startup: crea tablas e índices si no existen ----------
@app.on_event("startup")
async def on_startup():
    async with engine.begin() as conn:
        # Crea tablas
        await conn.run_sync(Base.metadata.create_all)

        # Índices/unique idempotentes (no fallan si ya existen)
        await conn.exec_driver_sql(
            'CREATE INDEX IF NOT EXISTS idx_source_campaign_type ON source_links ("campaignId", type)'
        )
        await conn.exec_driver_sql(
            'CREATE INDEX IF NOT EXISTS idx_source_url ON source_links (url)'
        )
        await conn.exec_driver_sql(
            'CREATE UNIQUE INDEX IF NOT EXISTS uq_source_campaign_url ON source_links ("campaignId", url)'
        )