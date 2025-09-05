# app/routers/auth.py
from __future__ import annotations

import uuid
from pydantic import BaseModel, EmailStr, Field
from fastapi import APIRouter, HTTPException, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import get_session
from ..models import User
from ..security import create_access_token

router = APIRouter()

class LoginRequest(BaseModel):
    email: EmailStr
    name: str | None = None

class LoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: dict

@router.post("/login", response_model=LoginResponse)
async def login(payload: LoginRequest, db: AsyncSession = Depends(get_session)):
    # Busca o crea user
    q = select(User).where(User.email == payload.email)
    user = (await db.execute(q)).scalar_one_or_none()

    if not user:
        # crea usuario con id legible (o usa uuid)
        new_id = str(uuid.uuid4())
        user = User(id=new_id, email=payload.email, name=payload.name or payload.email.split("@")[0])
        db.add(user)
        await db.commit()
        await db.refresh(user)

    # role simple (podrías cargar de otra tabla/flag)
    role = "admin" if user.email.endswith("@blackboxmonitor.com") else "user"

    token = create_access_token({
        "id": user.id,
        "email": user.email,
        "role": role,
    })

    return LoginResponse(
        access_token=token,
        user={"id": user.id, "email": user.email, "name": user.name, "role": role},
    )