from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import get_db
from app.core.models import AdminUser
from app.api.deps import current_admin
from app.core.security import create_access_token, hash_password, verify_password
from app.schemas import BootstrapAdminRequest, LoginRequest, TokenResponse

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/bootstrap", response_model=TokenResponse, status_code=status.HTTP_201_CREATED)
async def bootstrap_admin(payload: BootstrapAdminRequest, response: Response, session: AsyncSession = Depends(get_db)):
    count = await session.scalar(select(func.count(AdminUser.id)))
    if count:
        raise HTTPException(status_code=409, detail="An administrator already exists")
    if payload.bootstrap_key != settings.bootstrap_key:
        raise HTTPException(status_code=403, detail="Invalid bootstrap key")
    admin = AdminUser(
        email=payload.email.lower(),
        full_name=payload.full_name,
        password_hash=hash_password(payload.password),
        language=payload.language,
        permissions=["*"] ,
        is_superadmin=True,
    )
    session.add(admin)
    await session.commit()
    await session.refresh(admin)
    token = create_access_token(str(admin.id), extra={"superadmin": True})
    response.set_cookie(
        "access_token",
        token,
        httponly=True,
        secure=settings.admin_cookie_secure,
        samesite="lax",
        max_age=8 * 60 * 60,
    )
    return TokenResponse(access_token=token)


@router.post("/login", response_model=TokenResponse)
async def login(payload: LoginRequest, response: Response, session: AsyncSession = Depends(get_db)):
    admin = await session.scalar(select(AdminUser).where(AdminUser.email == payload.email.lower()))
    if not admin or not admin.is_active or not verify_password(payload.password, admin.password_hash):
        raise HTTPException(status_code=401, detail="Invalid email or password")
    token = create_access_token(str(admin.id), extra={"superadmin": admin.is_superadmin})
    response.set_cookie(
        "access_token",
        token,
        httponly=True,
        secure=settings.admin_cookie_secure,
        samesite="lax",
        max_age=8 * 60 * 60,
    )
    return TokenResponse(access_token=token)


@router.post("/logout", status_code=204)
async def logout(response: Response):
    response.delete_cookie("access_token")


@router.get("/me")
async def me(admin: AdminUser = Depends(current_admin)):
    return {
        "id": str(admin.id),
        "email": admin.email,
        "full_name": admin.full_name,
        "language": admin.language.value,
        "permissions": admin.permissions,
        "is_superadmin": admin.is_superadmin,
    }
