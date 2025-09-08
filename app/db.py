## app/db.py
from __future__ import annotations

import os
from sqlalchemy.ext.asyncio import (
    create_async_engine,
    async_sessionmaker,   # ✅ ESTE es el correcto
    AsyncSession,
)

# Normaliza la URL para psycopg (SQLAlchemy 2.x)
DATABASE_URL = os.getenv("DATABASE_URL", "")
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql+psycopg://", 1)
elif DATABASE_URL.startswith("postgresql://") and "+psycopg" not in DATABASE_URL:
    DATABASE_URL = DATABASE_URL.replace("postgresql://", "postgresql+psycopg://", 1)

engine = create_async_engine(DATABASE_URL, echo=False, future=True)

# ✅ usa async_sessionmaker
SessionLocal = async_sessionmaker(bind=engine, expire_on_commit=False, class_=AsyncSession)

# Dependencia para FastAPI
async def get_session() -> AsyncSession:
    async with SessionLocal() as session:
        yield session

# 👇👇👇 AÑADE ESTAS 3 LÍNEAS 👇👇👇
# Alias compat para routers que importan get_db
get_db = get_session
__all__ = ["engine", "SessionLocal", "get_session", "get_db"]
# 👆👆👆