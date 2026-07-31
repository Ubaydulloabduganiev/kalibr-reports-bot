from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_permission
from app.core.database import get_db
from app.core.models import (
    AdminUser,
    AuditLog,
    IntegrationOutbox,
    Priority,
    Report,
    ReportRecipient,
    ReportStatus,
)
from app.schemas import DealMatch, ManagerActionRequest, ReportRead
from app.services.amocrm import amocrm_client

router = APIRouter(prefix="/reports", tags=["reports"])


def _can_view_confidential(admin: AdminUser) -> bool:
    return admin.is_superadmin or "*" in admin.permissions or "view_confidential_reports" in admin.permissions


def _guard_confidential(report: Report, admin: AdminUser) -> None:
    if report.is_confidential and not _can_view_confidential(admin):
        raise HTTPException(status_code=403, detail="Confidential report access denied")


@router.get("", response_model=list[ReportRead])
async def list_reports(
    limit: int = Query(default=100, ge=1, le=500),
    admin: AdminUser = Depends(require_permission("view_reports")),
    session: AsyncSession = Depends(get_db),
):
    stmt = select(Report)
    if not _can_view_confidential(admin):
        stmt = stmt.where(Report.is_confidential.is_(False))
    stmt = stmt.order_by(Report.created_at.desc()).limit(limit)
    return list((await session.scalars(stmt)).all())


@router.get("/{report_id}", response_model=ReportRead)
async def get_report(report_id: uuid.UUID, admin: AdminUser = Depends(require_permission("view_reports")), session: AsyncSession = Depends(get_db)):
    report = await session.get(Report, report_id)
    if not report:
        raise HTTPException(status_code=404, detail="Report not found")
    _guard_confidential(report, admin)
    return report


@router.get("/{report_id}/deal-matches", response_model=list[DealMatch])
async def find_deal_matches(report_id: uuid.UUID, query: str, admin: AdminUser = Depends(require_permission("manage_reports")), session: AsyncSession = Depends(get_db)):
    report = await session.get(Report, report_id)
    if not report:
        raise HTTPException(status_code=404, detail="Report not found")
    _guard_confidential(report, admin)
    try:
        return await amocrm_client.find_leads(query)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.post("/{report_id}/link-deal")
async def link_deal(report_id: uuid.UUID, payload: dict, admin: AdminUser = Depends(require_permission("manage_reports")), session: AsyncSession = Depends(get_db)):
    report = await session.get(Report, report_id)
    if not report:
        raise HTTPException(status_code=404, detail="Report not found")
    _guard_confidential(report, admin)
    report.amocrm_deal_id = int(payload["deal_id"])
    await session.commit()
    return {"ok": True}


@router.post("/{report_id}/actions")
async def admin_report_action(
    report_id: uuid.UUID,
    payload: ManagerActionRequest,
    admin: AdminUser = Depends(require_permission("manage_reports")),
    session: AsyncSession = Depends(get_db),
):
    report = await session.get(Report, report_id)
    if not report:
        raise HTTPException(status_code=404, detail="Report not found")
    _guard_confidential(report, admin)
    if payload.action == "return" and not payload.reason:
        raise HTTPException(status_code=400, detail="A return reason is required")

    if payload.action == "approve":
        report.status = ReportStatus.APPROVED
    elif payload.action == "return":
        report.status = ReportStatus.RETURNED
    elif payload.action == "comment":
        pass
    elif payload.action == "reassign":
        if not payload.assignee_id:
            raise HTTPException(status_code=400, detail="assignee_id is required")
        report.current_responsible_id = payload.assignee_id
        existing = await session.scalar(
            select(ReportRecipient).where(
                ReportRecipient.report_id == report.id,
                ReportRecipient.employee_id == payload.assignee_id,
            )
        )
        if not existing:
            session.add(ReportRecipient(report_id=report.id, employee_id=payload.assignee_id, routing_reason="admin_reassignment"))
    elif payload.action == "create_task":
        report.status = ReportStatus.ACTION_REQUIRED
        report.requires_action = True
        session.add(
            IntegrationOutbox(
                event_type="report.task_requested",
                aggregate_id=report.id,
                idempotency_key=f"report.task_requested:{report.id}:{uuid.uuid4().hex}",
                payload={"report_id": str(report.id), "reason": payload.reason or "Administrator requested a task"},
            )
        )
    elif payload.action == "escalate":
        report.status = ReportStatus.ESCALATED
        if report.priority != Priority.CRITICAL:
            report.priority = Priority.HIGH
    elif payload.action == "resolve":
        report.status = ReportStatus.RESOLVED
        if report.amocrm_lead_id:
            session.add(
                IntegrationOutbox(
                    event_type="report.resolved",
                    aggregate_id=report.id,
                    idempotency_key=f"report.resolved:{report.id}:admin:{uuid.uuid4().hex}",
                    payload={"report_id": str(report.id)},
                )
            )

    session.add(
        AuditLog(
            actor_type="admin",
            actor_id=str(admin.id),
            action=f"report.{payload.action}",
            entity_type="report",
            entity_id=str(report.id),
            details={
                "reason": payload.reason,
                "assignee_id": str(payload.assignee_id) if payload.assignee_id else None,
                "due_at": payload.due_at.isoformat() if payload.due_at else None,
            },
        )
    )
    await session.commit()
    from app.tasks.amocrm_sync import process_outbox
    if payload.action in {"create_task", "resolve"}:
        process_outbox.delay()
    return {"ok": True, "status": report.status.value}
