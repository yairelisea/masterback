# app/security.py
from datetime import datetime, timedelta, timezone
from typing import Any, Optional
from jose import jwt, JWTError

ALGORITHM = "HS256"

def create_access_token(*, data: dict, secret: str, minutes: int = 120) -> str:
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + timedelta(minutes=minutes)
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, secret, algorithm=ALGORITHM)

def decode_token(token: str, secret: str) -> Optional[dict[str, Any]]:
    try:
        return jwt.decode(token, secret, algorithms=[ALGORITHM])
    except JWTError:
        return None