import sys
print("PY:", sys.version)
from .db import engine
print("DB:", engine.dialect.name, getattr(engine.dialect, "driver", "unknown"))
import os
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv
from .routers import campaigns, sources, ingest, analyses, news

from .db import engine, Base, ping_db
from .routers import campaigns, sources, ingest, analyses, news, ai_analysis  # + ai_analysis
...
app.include_router(ai_analysis.router)

load_dotenv()  # carga .env si existe

ALLOWED_ORIGINS = [o.strip() for o in os.getenv("ALLOWED_ORIGINS", "").split(",") if o.strip()]

app = FastAPI(title="BBX FastAPI Backend")

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS or ["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.on_event("startup")
async def on_startup():
    # crea tablas si no existen
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

@app.get("/health")
async def health():
    await ping_db()
    return {"ok": True}

# Routers
app.include_router(campaigns.router)
app.include_router(sources.router)
app.include_router(ingest.router)
app.include_router(analyses.router)
app.include_router(news.router) 