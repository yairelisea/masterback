# app/main.py
import os
from fastapi import FastAPI, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse

# Importa Base y engine para crear tablas en startup
from .models import Base
from .db import engine

# Importa routers (haz que existan estos archivos según tu proyecto)
from .routers import campaigns, sources, ingest, analyses, news, ai_analysis

# ---- Crea la app ANTES de usar include_router ----
app = FastAPI(title="BBX API", version="0.1.0")

# ---- CORS ----
origins = []
raw_origins = os.getenv("ALLOWED_ORIGINS", "")
if raw_origins:
    # separar por coma y limpiar espacios
    origins = [o.strip() for o in raw_origins.split(",") if o.strip()]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins or ["*"],  # si no mandas env var, permite todo (ajústalo en prod)
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---- Rutas base útiles ----
@app.get("/health")
def health():
    return {"ok": True}

@app.get("/")
def root():
    # redirige a la documentación interactiva
    return RedirectResponse(url="/docs")

@app.get("/favicon.ico")
def favicon_empty():
    # evita 404 por favicon hasta que subas uno real
    return Response(status_code=204)

# ---- Incluye routers (DESPUÉS de crear app) ----
app.include_router(campaigns.router)
app.include_router(sources.router)
app.include_router(ingest.router)
app.include_router(analyses.router)
app.include_router(news.router)
app.include_router(ai_analysis.router)

# ---- Startup: crea tablas si no existen ----
@app.on_event("startup")
async def on_startup():
    # crea tablas de forma asíncrona
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)