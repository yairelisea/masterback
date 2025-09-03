# app/db.py
from __future__ import annotations

import os
from sqlalchemy.ext.asyncio import (
    create_async_engine,
    async_sessionmaker,
    AsyncSession,
)

# Normaliza la URL para psycopg (SQLAlchemy 2.x)
DATABASE_URL = os.getenv("DATABASE_URL", "")
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql+psycopg://", 1)
elif DATABASE_URL.startswith("postgresql://") and "+psycopg" not in DATABASE_URL:
    DATABASE_URL = DATABASE_URL.replace("postgresql://", "postgresql+psycopg://", 1)

engine = create_async_engine(
    DATABASE_URL,
    echo=False,   # pon True si quieres ver SQL en logs
    future=True,
)

SessionLocal = get_sessionmaker(bind=engine, expire_on_commit=False, class_=AsyncSession)

# Dependencia FastAPI: inyecta una sesión por request
async def get_session() -> AsyncSession:
    async with SessionLocal() as session:
        yield session