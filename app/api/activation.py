import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_permission
from app.core.database import get_db
from app.core.models import AdminUser
from app.schemas import ActivationCodeResponse
from app.services.activation import create_activation_code

router = APIRouter(prefix="/employees", tags=["activation"])


@router.post("/{employee_id}/activation-code", response_model=ActivationCodeResponse)
async def issue_activation_code(
    employee_id: uuid.UUID,
    admin: AdminUser = Depends(require_permission("manage_employees")),
    session: AsyncSession = Depends(get_db),
):
    try:
        code, record = await create_activation_code(session, employee_id=employee_id, created_by_id=admin.id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return ActivationCodeResponse(code=code, expires_at=record.expires_at)
