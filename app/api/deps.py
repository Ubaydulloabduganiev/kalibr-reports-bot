from __future__ import annotations

import uuid

from fastapi import Cookie, Depends, Header, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.models import AdminUser
from app.core.security import decode_access_token


async def current_admin(
    session: AsyncSession = Depends(get_db),
    authorization: str | None = Header(default=None),
    access_token: str | None = Cookie(default=None),
) -> AdminUser:
    token = access_token
    if authorization and authorization.lower().startswith("bearer "):
        token = authorization.split(" ", 1)[1]
    if not token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Authentication required")
    payload = decode_access_token(token)
    try:
        admin_id = uuid.UUID(payload["sub"])
    except (KeyError, ValueError) as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token subject") from exc
    admin = await session.get(AdminUser, admin_id)
    if not admin or not admin.is_active:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Inactive administrator")
    return admin


def require_superadmin(admin: AdminUser = Depends(current_admin)) -> AdminUser:
    if not admin.is_superadmin:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Super administrator required")
    return admin


def require_permission(permission: str):
    async def dependency(admin: AdminUser = Depends(current_admin)) -> AdminUser:
        if admin.is_superadmin or "*" in admin.permissions or permission in admin.permissions:
            return admin
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=f"Permission required: {permission}")

    return dependency
