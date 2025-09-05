# app/deps.py
from __future__ import annotations
import os
from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

# IMPORTA DESDE EL MISMO PAQUETE app
from .security import decode_token

bearer = HTTPBearer(auto_error=False)
JWT_SECRET = os.getenv("JWT_SECRET", "please-change-me")

async def get_current_user(credentials: HTTPAuthorizationCredentials = Depends(bearer)) -> dict:
    if not credentials:
        raise HTTPException(status_code=401, detail="Missing Authorization")
    payload = decode_token(credentials.credentials, JWT_SECRET)
    if not payload:
        raise HTTPException(status_code=401, detail="Invalid token")
    # payload esperado: {"id": "...", "email": "...", "role": "...", "exp": ...}
    return payload