from __future__ import annotations

import hashlib
import hmac
import secrets
import string
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.config import settings
from app.core.models import ActivationCode, Employee

ALPHABET = string.ascii_uppercase + string.digits


def normalize_code(code: str) -> str:
    return code.strip().upper().replace(" ", "")


def hash_code(code: str) -> str:
    return hmac.new(settings.secret_key.encode(), normalize_code(code).encode(), hashlib.sha256).hexdigest()


def generate_code() -> str:
    raw = "".join(secrets.choice(ALPHABET) for _ in range(8))
    return f"KB-{raw[:4]}-{raw[4:]}"


async def create_activation_code(
    session: AsyncSession,
    *,
    employee_id: uuid.UUID,
    created_by_id: uuid.UUID | None,
    expires_hours: int = 72,
) -> tuple[str, ActivationCode]:
    employee = await session.get(Employee, employee_id)
    if not employee or not employee.is_active:
        raise ValueError("Employee not found or inactive")

    plain_code = generate_code()
    record = ActivationCode(
        employee_id=employee_id,
        code_hash=hash_code(plain_code),
        expires_at=datetime.now(UTC) + timedelta(hours=expires_hours),
        created_by_id=created_by_id,
    )
    session.add(record)
    await session.commit()
    await session.refresh(record)
    return plain_code, record


async def activate_employee(
    session: AsyncSession,
    *,
    code: str,
    telegram_user_id: int,
    telegram_username: str | None,
) -> Employee:
    now = datetime.now(UTC)
    stmt = (
        select(ActivationCode)
        .where(ActivationCode.code_hash == hash_code(code))
        .options(selectinload(ActivationCode.employee))
    )
    record = (await session.execute(stmt)).scalar_one_or_none()
    if not record or record.used_at is not None or record.expires_at <= now:
        raise ValueError("Invalid or expired activation code")

    existing = await session.scalar(select(Employee).where(Employee.telegram_user_id == telegram_user_id))
    if existing and existing.id != record.employee_id:
        raise ValueError("This Telegram account is already linked")

    employee = record.employee
    employee.telegram_user_id = telegram_user_id
    employee.telegram_username = telegram_username
    record.used_at = now
    await session.commit()
    await session.refresh(employee)
    return employee
