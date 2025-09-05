# app/routers/auth.py
from __future__ import annotations
import os
from fastapi import APIRouter, HTTPException, Depends
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel

from ..security import create_access_token, decode_token
from ..db import get_session
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from ..models import User

router = APIRouter(prefix="/auth", tags=["auth"])

ADMIN_EMAIL = os.getenv("ADMIN_EMAIL", "admin@example.com")
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "changeme")
JWT_SECRET = os.getenv("JWT_SECRET", "please-change-me")
JWT_EXPIRE_MINUTES = int(os.getenv("JWT_EXPIRE_MINUTES", "120"))

bearer = HTTPBearer(auto_error=False)

class LoginIn(BaseModel):
    email: str
    password: str

class LoginOut(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: dict

def _ensure_user_sync(email: str) -> dict:
    # Por si quieres meter “role” en el token para admin
    role = "admin" if email.lower() == ADMIN_EMAIL.lower() else "user"
    # user_id simple (email) — si ya usas UUIDs, cámbialo aquí.
    uid = email.lower()
    return {"id": uid, "email": email, "role": role}

@router.post("/login", response_model=LoginOut)
async def login(payload: LoginIn, db: AsyncSession = Depends(get_session)):
    # MVP: un admin desde variables de entorno
    if payload.email.lower() == ADMIN_EMAIL.lower() and payload.password == ADMIN_PASSWORD:
        user_claims = _ensure_user_sync(payload.email)
    else:
        # Si quisieras permitir “usuarios abiertos” sin tabla, comenta el raise:
        raise HTTPException(status_code=401, detail="Invalid credentials")

    # Asegura que exista el usuario en DB para FKs de campañas
    existing = (await db.execute(select(User).where(User.id == user_claims["id"]))).scalar_one_or_none()
    if not existing:
        db.add(User(id=user_claims["id"], email=user_claims["email"], name=user_claims["email"]))
        await db.commit()

    token = create_access_token(data=user_claims, secret=JWT_SECRET, minutes=JWT_EXPIRE_MINUTES)
    return LoginOut(access_token=token, user=user_claims)

@router.get("/me")
async def me(credentials: HTTPAuthorizationCredentials = Depends(bearer)):
    if not credentials:
        raise HTTPException(status_code=401, detail="Missing Authorization")
    payload = decode_token(credentials.credentials, JWT_SECRET)
    if not payload:
        raise HTTPException(status_code=401, detail="Invalid token")
    return payload