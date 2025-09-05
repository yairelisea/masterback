# app/security.py
from __future__ import annotations
import os, time
from typing import Optional, Dict, Any
from jose import jwt, JWTError

# Debe existir en Render:
# Settings -> Environment -> JWT_SECRET = algo_muy_largo_y_secreto
JWT_SECRET = os.getenv("JWT_SECRET", "please-change-me")
JWT_ALG = "HS256"

def create_access_token(payload: Dict[str, Any], expires_in: int = 60 * 60 * 12) -> str:
    to_encode = payload.copy()
    to_encode["exp"] = int(time.time()) + expires_in
    return jwt.encode(to_encode, JWT_SECRET, algorithm=JWT_ALG)

def decode_token(token: str, secret: Optional[str] = None) -> Optional[Dict[str, Any]]:
    secret = secret or JWT_SECRET
    try:
        data = jwt.decode(token, secret, algorithms=[JWT_ALG])
        return data
    except JWTError:
        return None