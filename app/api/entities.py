from __future__ import annotations

import uuid
from datetime import time

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.deps import require_permission
from app.core.database import get_db
from app.core.models import (
    AdminUser,
    Branch,
    Department,
    Employee,
    Report,
    Priority,
    ReportStatus,
    ReportSchedule,
    Role,
    ScheduleKind,
)
from app.schemas import EmployeeCreate, EmployeeRead, EmployeeUpdate, NamedEntityCreate, NamedEntityRead, RoleCreate

router = APIRouter(tags=["administration"])


@router.get("/departments", response_model=list[NamedEntityRead])
async def list_departments(_: AdminUser = Depends(require_permission("view_structure")), session: AsyncSession = Depends(get_db)):
    return list((await session.scalars(select(Department).order_by(Department.name_uz))).all())


@router.post("/departments", response_model=NamedEntityRead, status_code=status.HTTP_201_CREATED)
async def create_department(payload: NamedEntityCreate, _: AdminUser = Depends(require_permission("manage_structure")), session: AsyncSession = Depends(get_db)):
    item = Department(
        code=payload.code,
        name_uz=payload.name_uz,
        name_ru=payload.name_ru,
        group_code=payload.group_code or "office",
    )
    session.add(item)
    await session.commit()
    await session.refresh(item)
    return item


@router.get("/branches", response_model=list[NamedEntityRead])
async def list_branches(_: AdminUser = Depends(require_permission("view_structure")), session: AsyncSession = Depends(get_db)):
    return list((await session.scalars(select(Branch).order_by(Branch.name_uz))).all())


@router.post("/branches", response_model=NamedEntityRead, status_code=status.HTTP_201_CREATED)
async def create_branch(payload: NamedEntityCreate, _: AdminUser = Depends(require_permission("manage_structure")), session: AsyncSession = Depends(get_db)):
    item = Branch(code=payload.code, name_uz=payload.name_uz, name_ru=payload.name_ru)
    session.add(item)
    await session.commit()
    await session.refresh(item)
    return item


@router.get("/roles", response_model=list[NamedEntityRead])
async def list_roles(_: AdminUser = Depends(require_permission("view_structure")), session: AsyncSession = Depends(get_db)):
    return list((await session.scalars(select(Role).order_by(Role.name_uz))).all())


@router.post("/roles", response_model=NamedEntityRead, status_code=status.HTTP_201_CREATED)
async def create_role(payload: RoleCreate, _: AdminUser = Depends(require_permission("manage_structure")), session: AsyncSession = Depends(get_db)):
    item = Role(
        code=payload.code,
        name_uz=payload.name_uz,
        name_ru=payload.name_ru,
        permissions=payload.permissions,
        is_manager=payload.is_manager,
    )
    session.add(item)
    await session.commit()
    await session.refresh(item)
    return item


async def _load_entities(session: AsyncSession, model, ids: list[uuid.UUID]):
    if not ids:
        return []
    result = list((await session.scalars(select(model).where(model.id.in_(ids)))).all())
    if len(result) != len(set(ids)):
        raise HTTPException(status_code=400, detail=f"One or more {model.__name__.lower()} IDs are invalid")
    return result


@router.get("/employees", response_model=list[EmployeeRead])
async def list_employees(
    q: str | None = Query(default=None),
    active_only: bool = True,
    _: AdminUser = Depends(require_permission("view_employees")),
    session: AsyncSession = Depends(get_db),
):
    stmt = select(Employee).options(
        selectinload(Employee.roles),
        selectinload(Employee.departments),
        selectinload(Employee.branches),
    ).order_by(Employee.full_name)
    if q:
        stmt = stmt.where(Employee.full_name.ilike(f"%{q}%"))
    if active_only:
        stmt = stmt.where(Employee.is_active.is_(True))
    return list((await session.scalars(stmt)).unique().all())


@router.post("/employees", response_model=EmployeeRead, status_code=status.HTTP_201_CREATED)
async def create_employee(payload: EmployeeCreate, _: AdminUser = Depends(require_permission("manage_employees")), session: AsyncSession = Depends(get_db)):
    employee = Employee(
        full_name=payload.full_name,
        phone=payload.phone,
        language=payload.language,
        direct_manager_id=payload.direct_manager_id,
        amocrm_user_id=payload.amocrm_user_id,
        visibility_scopes=payload.visibility_scopes,
        can_receive_reports=payload.can_receive_reports,
        can_view_confidential=payload.can_view_confidential,
    )
    employee.roles = await _load_entities(session, Role, payload.role_ids)
    employee.departments = await _load_entities(session, Department, payload.department_ids)
    employee.branches = await _load_entities(session, Branch, payload.branch_ids)
    employee.extra_recipients = await _load_entities(session, Employee, payload.extra_recipient_ids)
    session.add(employee)
    await session.commit()
    stmt = select(Employee).where(Employee.id == employee.id).options(
        selectinload(Employee.roles), selectinload(Employee.departments), selectinload(Employee.branches)
    )
    return (await session.execute(stmt)).scalar_one()


@router.patch("/employees/{employee_id}", response_model=EmployeeRead)
async def update_employee(employee_id: uuid.UUID, payload: EmployeeUpdate, _: AdminUser = Depends(require_permission("manage_employees")), session: AsyncSession = Depends(get_db)):
    stmt = select(Employee).where(Employee.id == employee_id).options(
        selectinload(Employee.roles),
        selectinload(Employee.departments),
        selectinload(Employee.branches),
        selectinload(Employee.extra_recipients),
    )
    employee = (await session.execute(stmt)).scalar_one_or_none()
    if not employee:
        raise HTTPException(status_code=404, detail="Employee not found")
    data = payload.model_dump(exclude_unset=True)
    role_ids = data.pop("role_ids", None)
    department_ids = data.pop("department_ids", None)
    branch_ids = data.pop("branch_ids", None)
    extra_recipient_ids = data.pop("extra_recipient_ids", None)
    for key, value in data.items():
        setattr(employee, key, value)
    if role_ids is not None:
        employee.roles = await _load_entities(session, Role, role_ids)
    if department_ids is not None:
        employee.departments = await _load_entities(session, Department, department_ids)
    if branch_ids is not None:
        employee.branches = await _load_entities(session, Branch, branch_ids)
    if extra_recipient_ids is not None:
        employee.extra_recipients = await _load_entities(session, Employee, extra_recipient_ids)
    await session.commit()
    return employee


@router.get("/dashboard")
async def dashboard(_: AdminUser = Depends(require_permission("view_dashboard")), session: AsyncSession = Depends(get_db)):
    employees = await session.scalar(select(func.count(Employee.id)).where(Employee.is_active.is_(True)))
    unlinked = await session.scalar(select(func.count(Employee.id)).where(Employee.is_active.is_(True), Employee.telegram_user_id.is_(None)))
    submitted_today = await session.scalar(select(func.count(Report.id)).where(Report.submitted_at.is_not(None), func.date(Report.submitted_at) == func.current_date()))
    critical_open = await session.scalar(select(func.count(Report.id)).where(Report.priority == Priority.CRITICAL, Report.status.notin_([ReportStatus.RESOLVED, ReportStatus.CANCELLED])))
    return {
        "employees": employees or 0,
        "unlinked_employees": unlinked or 0,
        "submitted_today": submitted_today or 0,
        "critical_open": critical_open or 0,
    }


@router.get("/schedules")
async def list_schedules(_: AdminUser = Depends(require_permission("view_schedules")), session: AsyncSession = Depends(get_db)):
    items = list((await session.scalars(select(ReportSchedule).order_by(ReportSchedule.local_time))).all())
    return [
        {
            "id": str(item.id),
            "name": item.name,
            "kind": item.kind.value,
            "group_code": item.group_code,
            "local_time": item.local_time.isoformat(timespec="minutes"),
            "weekday": item.weekday,
            "grace_minutes": item.grace_minutes,
            "is_active": item.is_active,
        }
        for item in items
    ]


@router.post("/schedules", status_code=201)
async def create_schedule(payload: dict, _: AdminUser = Depends(require_permission("manage_schedules")), session: AsyncSession = Depends(get_db)):
    try:
        parsed_time = time.fromisoformat(payload["local_time"])
        kind = ScheduleKind(payload["kind"])
    except (KeyError, ValueError) as exc:
        raise HTTPException(status_code=400, detail="Invalid schedule payload") from exc
    item = ReportSchedule(
        name=payload["name"],
        kind=kind,
        group_code=payload.get("group_code"),
        local_time=parsed_time,
        weekday=payload.get("weekday"),
        grace_minutes=int(payload.get("grace_minutes", 60)),
        first_reminder_minutes=int(payload.get("first_reminder_minutes", 20)),
        final_reminder_minutes=int(payload.get("final_reminder_minutes", 45)),
    )
    session.add(item)
    await session.commit()
    await session.refresh(item)
    return {"id": str(item.id)}
