from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_permission, require_superadmin
from app.core.database import get_db
from app.core.models import (
    AdminUser,
    Employee,
    EmployeeKPITarget,
    KPIDefinition,
    ReportTemplate,
    SystemSetting,
)
from app.core.security import hash_password
from app.schemas import (
    AdminUserCreate,
    AdminUserRead,
    EmployeeKPITargetCreate,
    KPIDefinitionCreate,
    KPIDefinitionRead,
    ReportTemplateCreate,
    ReportTemplateRead,
    RiskThresholds,
)

router = APIRouter(tags=["configuration"])


@router.get("/admins", response_model=list[AdminUserRead])
async def list_admins(_: AdminUser = Depends(require_superadmin), session: AsyncSession = Depends(get_db)):
    return list((await session.scalars(select(AdminUser).order_by(AdminUser.full_name))).all())


@router.post("/admins", response_model=AdminUserRead, status_code=status.HTTP_201_CREATED)
async def create_admin(
    payload: AdminUserCreate,
    _: AdminUser = Depends(require_superadmin),
    session: AsyncSession = Depends(get_db),
):
    if await session.scalar(select(AdminUser).where(AdminUser.email == payload.email.lower())):
        raise HTTPException(status_code=409, detail="Administrator email already exists")
    admin = AdminUser(
        email=payload.email.lower(),
        full_name=payload.full_name,
        password_hash=hash_password(payload.password),
        language=payload.language,
        permissions=payload.permissions,
        is_superadmin=payload.is_superadmin,
    )
    session.add(admin)
    await session.commit()
    await session.refresh(admin)
    return admin


@router.patch("/admins/{admin_id}", response_model=AdminUserRead)
async def update_admin(
    admin_id: uuid.UUID,
    payload: dict,
    current: AdminUser = Depends(require_superadmin),
    session: AsyncSession = Depends(get_db),
):
    admin = await session.get(AdminUser, admin_id)
    if not admin:
        raise HTTPException(status_code=404, detail="Administrator not found")
    if admin.id == current.id and payload.get("is_active") is False:
        raise HTTPException(status_code=400, detail="You cannot deactivate your own account")
    allowed = {"full_name", "language", "permissions", "is_active", "is_superadmin"}
    for key, value in payload.items():
        if key in allowed:
            setattr(admin, key, value)
    if password := payload.get("password"):
        if len(password) < 10:
            raise HTTPException(status_code=400, detail="Password must contain at least 10 characters")
        admin.password_hash = hash_password(password)
    await session.commit()
    await session.refresh(admin)
    return admin


@router.get("/report-templates", response_model=list[ReportTemplateRead])
async def list_report_templates(
    _: AdminUser = Depends(require_permission("manage_configuration")), session: AsyncSession = Depends(get_db)
):
    return list((await session.scalars(select(ReportTemplate).order_by(ReportTemplate.name))).all())


@router.post("/report-templates", response_model=ReportTemplateRead, status_code=status.HTTP_201_CREATED)
async def create_report_template(
    payload: ReportTemplateCreate,
    _: AdminUser = Depends(require_permission("manage_configuration")),
    session: AsyncSession = Depends(get_db),
):
    item = ReportTemplate(**payload.model_dump())
    session.add(item)
    await session.commit()
    await session.refresh(item)
    return item


@router.patch("/report-templates/{template_id}", response_model=ReportTemplateRead)
async def update_report_template(
    template_id: uuid.UUID,
    payload: dict,
    _: AdminUser = Depends(require_permission("manage_configuration")),
    session: AsyncSession = Depends(get_db),
):
    item = await session.get(ReportTemplate, template_id)
    if not item:
        raise HTTPException(status_code=404, detail="Template not found")
    allowed = {
        "name",
        "report_type",
        "department_id",
        "role_id",
        "questions_uz",
        "questions_ru",
        "extraction_instructions",
        "is_active",
    }
    for key, value in payload.items():
        if key in allowed:
            setattr(item, key, value)
    await session.commit()
    await session.refresh(item)
    return item


@router.get("/kpis", response_model=list[KPIDefinitionRead])
async def list_kpis(_: AdminUser = Depends(require_permission("manage_configuration")), session: AsyncSession = Depends(get_db)):
    return list((await session.scalars(select(KPIDefinition).order_by(KPIDefinition.name_uz))).all())


@router.post("/kpis", response_model=KPIDefinitionRead, status_code=status.HTTP_201_CREATED)
async def create_kpi(
    payload: KPIDefinitionCreate,
    _: AdminUser = Depends(require_permission("manage_configuration")),
    session: AsyncSession = Depends(get_db),
):
    item = KPIDefinition(**payload.model_dump())
    session.add(item)
    await session.commit()
    await session.refresh(item)
    return item


@router.post("/employees/{employee_id}/kpi-targets", status_code=status.HTTP_201_CREATED)
async def create_employee_kpi_target(
    employee_id: uuid.UUID,
    payload: EmployeeKPITargetCreate,
    _: AdminUser = Depends(require_permission("manage_configuration")),
    session: AsyncSession = Depends(get_db),
):
    if not await session.get(Employee, employee_id):
        raise HTTPException(status_code=404, detail="Employee not found")
    if not await session.get(KPIDefinition, payload.kpi_definition_id):
        raise HTTPException(status_code=404, detail="KPI definition not found")
    target = EmployeeKPITarget(employee_id=employee_id, **payload.model_dump())
    session.add(target)
    await session.commit()
    await session.refresh(target)
    return {"id": str(target.id)}


@router.get("/settings/risk-thresholds", response_model=RiskThresholds)
async def get_risk_thresholds_endpoint(
    _: AdminUser = Depends(require_permission("manage_configuration")), session: AsyncSession = Depends(get_db)
):
    values = {}
    for key in RiskThresholds.model_fields:
        setting = await session.get(SystemSetting, f"risk.{key}")
        if setting is not None:
            values[key] = setting.value
    return RiskThresholds(**values)


@router.put("/settings/risk-thresholds", response_model=RiskThresholds)
async def set_risk_thresholds_endpoint(
    payload: RiskThresholds,
    _: AdminUser = Depends(require_superadmin),
    session: AsyncSession = Depends(get_db),
):
    for key, value in payload.model_dump().items():
        db_key = f"risk.{key}"
        setting = await session.get(SystemSetting, db_key)
        if setting:
            setting.value = value
        else:
            session.add(SystemSetting(key=db_key, value=value))
    await session.commit()
    return payload


@router.get("/settings/amocrm-mapping")
async def get_amocrm_mapping(
    _: AdminUser = Depends(require_permission("manage_configuration")), session: AsyncSession = Depends(get_db)
):
    setting = await session.get(SystemSetting, "amocrm.custom_field_mapping")
    return setting.value if setting else {}


@router.put("/settings/amocrm-mapping")
async def set_amocrm_mapping(
    payload: dict,
    _: AdminUser = Depends(require_superadmin),
    session: AsyncSession = Depends(get_db),
):
    setting = await session.get(SystemSetting, "amocrm.custom_field_mapping")
    if setting:
        setting.value = payload
    else:
        session.add(SystemSetting(key="amocrm.custom_field_mapping", value=payload))
    await session.commit()
    return payload
