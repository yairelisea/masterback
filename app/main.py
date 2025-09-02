# app/main.py
import os
from fastapi import FastAPI, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse
from fastapi.routing import APIRoute

# Importa Base y engine para crear tablas en startup
from .models import Base
from .db import engine

# Importa routers
from .routers import campaigns, sources, ingest, analyses, news, ai_analysis


# ---- Generador de operation_id únicos ----
def custom_generate_unique_id(route: APIRoute) -> str:
    # Construye un ID basado en tags, método y path (garantiza unicidad)
    return f"{route.tags[0] if route.tags else 'default'}_{list(route.methods)[0]}_{route.path}".replace("/", "_").strip("_")


# ---- Instancia de FastAPI ----
app = FastAPI(
    title="BBX API",
    version="0.1.0",
    generate_unique_id_function=custom_generate_unique_id
)


# ---- CORS ----
origins = []
raw_origins = os.getenv("ALLOWED_ORIGINS", "")
if raw_origins:
    origins = [o.strip() for o in raw_origins.split(",") if o.strip()]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins or ["*"],  # en producción especifica tus dominios
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---- Rutas base ----
@app.get("/health")
def health():
    return {"ok": True}

@app.get("/")
def root():
    return RedirectResponse(url="/docs")

@app.get("/favicon.ico")
def favicon_empty():
    return Response(status_code=204)


# ---- Routers ----
app.include_router(campaigns.router)
app.include_router(sources.router)
app.include_router(ingest.router)
app.include_router(analyses.router)
app.include_router(news.router)
app.include_router(ai_analysis.router)


# ---- Startup: crea tablas si no existen ----
@app.on_event("startup")
async def on_startup():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)