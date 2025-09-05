# app/main.py
import os
from fastapi import FastAPI, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse
from fastapi.routing import APIRoute
from sqlalchemy import text
from .routers import campaigns

# Importa Base y engine para crear tablas en startup
from .models import Base
from .db import engine

# Importa routers (ajusta si alguno no existe en tu proyecto)
from .routers import campaigns, sources, ingest, analyses, news, ai_analysis


# ---- Generador de operation_id únicos ----
def custom_generate_unique_id(route: APIRoute) -> str:
    tag = (route.tags[0] if route.tags else "default").lower().replace(" ", "_")
    method = list(route.methods)[0].lower()
    path = route.path.replace("/", "_").strip("_").replace("{", "").replace("}", "")
    return f"{tag}_{method}_{path}"


# ---- Instancia de FastAPI ----
app = FastAPI(
    title="BBX API",
    version="0.1.0",
    generate_unique_id_function=custom_generate_unique_id,
)


# ---- CORS ----
origins = []
raw_origins = os.getenv("ALLOWED_ORIGINS", "")
if raw_origins:
    origins = [o.strip() for o in raw_origins.split(",") if o.strip()]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins or ["https://legendary-youtiao-0e1307.netlify.app/"],  # En prod: especifica dominios permitidos
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---- Rutas base ----
@app.get("/health", tags=["meta"])
async def health():
    return {"ok": True}

@app.get("/", include_in_schema=False)
async def root():
    return RedirectResponse(url="/docs")

@app.get("/favicon.ico", include_in_schema=False)
async def favicon_empty():
    return Response(status_code=204)


# ---- Routers ----
app.include_router(campaigns.router, tags=["campaigns"])
app.include_router(sources.router, tags=["sources"])
app.include_router(ingest.router, tags=["ingest"])
app.include_router(analyses.router, tags=["analyses"])
app.include_router(news.router, tags=["news"])
app.include_router(ai_analysis.router, tags=["ai"])


# ---- Startup: crea tablas e índices si no existen ----
@app.on_event("startup")
async def on_startup():
    async with engine.begin() as conn:
        # Crea tablas
        await conn.run_sync(Base.metadata.create_all)

        # Índices / unique idempotentes (no fallan si ya existen)
        await conn.exec_driver_sql(
            'CREATE INDEX IF NOT EXISTS idx_source_campaign_type ON source_links ("campaignId", type)'
        )
        await conn.exec_driver_sql(
            'CREATE INDEX IF NOT EXISTS idx_source_url ON source_links (url)'
        )
        await conn.exec_driver_sql(
            'CREATE UNIQUE INDEX IF NOT EXISTS uq_source_campaign_url ON source_links ("campaignId", url)'
        )