from __future__ import annotations

import asyncio
import re
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import and_, or_, select
from sqlalchemy.orm import selectinload

from app.core.database import SessionLocal, dispose_engine
from app.core.models import (
    Employee,
    IntegrationOutbox,
    IntegrationStatus,
    Priority,
    Report,
    ReportRecipient,
    SystemSetting,
)
from app.services.amocrm import amocrm_client
from app.services.reporting import render_structured_report
from app.services.risk_rules import load_risk_thresholds
from app.tasks.celery_app import celery_app


def strip_html(value: str) -> str:
    return re.sub(r"<[^>]+>", "", value).replace("&lt;", "<").replace("&gt;", ">")


async def _load_report(session, report_id: uuid.UUID) -> Report:
    stmt = (
        select(Report)
        .where(Report.id == report_id)
        .options(
            selectinload(Report.employee).selectinload(Employee.departments),
            selectinload(Report.employee).selectinload(Employee.roles),
            selectinload(Report.employee).selectinload(Employee.branches),
            selectinload(Report.current_responsible),
            selectinload(Report.recipients).selectinload(ReportRecipient.employee),
        )
    )
    return (await session.execute(stmt)).scalar_one()




def _as_text(value) -> str:
    if value is None:
        return ""
    if isinstance(value, list):
        return "\n".join(str(item) for item in value)
    if isinstance(value, bool):
        return "Yes" if value else "No"
    return str(value)


async def _custom_fields(session, report: Report) -> list[dict]:
    setting = await session.get(SystemSetting, "amocrm.custom_field_mapping")
    mapping = setting.value if setting and isinstance(setting.value, dict) else {}
    structured = report.structured_data or {}
    employee = report.employee
    source = {
        "report_id": report.id,
        "employee": employee.full_name,
        "department": [item.name_uz for item in employee.departments],
        "branch": [item.name_uz for item in employee.branches],
        "role": [item.name_uz for item in employee.roles],
        "report_type": report.report_type.value,
        "report_date": report.report_date.isoformat(),
        "priority": report.priority.value,
        "completed": structured.get("completed", []),
        "measurable_results": structured.get("measurable_results", []),
        "unfinished": structured.get("unfinished", []),
        "blockers": structured.get("blockers", []),
        "help_or_approval": structured.get("help_or_approval", []),
        "tomorrow_plan": structured.get("tomorrow_plan", []),
        "urgent_summary": structured.get("urgent_summary"),
        "ai_confidence": report.ai_confidence,
        "confidential": report.is_confidential,
    }
    result: list[dict] = []
    for source_key, raw_field in mapping.items():
        if source_key not in source:
            continue
        field_id = raw_field.get("field_id") if isinstance(raw_field, dict) else raw_field
        try:
            field_id = int(field_id)
        except (TypeError, ValueError):
            continue
        value = _as_text(source[source_key])
        if value:
            result.append({"field_id": field_id, "values": [{"value": value}]})
    return result


async def _save_payload_state(session, item: IntegrationOutbox, state: dict) -> None:
    item.payload = dict(state)
    await session.commit()


async def _process_item(item_id: uuid.UUID) -> None:
    async with SessionLocal() as session:
        item = await session.get(IntegrationOutbox, item_id)
        if not item or item.status != IntegrationStatus.PROCESSING:
            return
        state = dict(item.payload)

        try:
            report = await _load_report(session, uuid.UUID(state["report_id"]))
            responsible_user_id = report.current_responsible.amocrm_user_id if report.current_responsible else None
            note_text = strip_html(render_structured_report(report, "uz"))
            lead_id = report.amocrm_deal_id or report.amocrm_lead_id

            if item.event_type in {"report.submitted", "report.task_requested"}:
                if not lead_id:
                    lead_id = await amocrm_client.create_report_lead(
                        name=f"{report.employee.full_name} — {report.report_type.value} — {report.report_date}",
                        responsible_user_id=responsible_user_id,
                        critical=report.priority == Priority.CRITICAL,
                        tags=["employee-report", report.report_type.value, report.priority.value],
                        custom_fields_values=await _custom_fields(session, report),
                    )
                    report.amocrm_lead_id = lead_id
                    state["lead_created"] = True
                    await _save_payload_state(session, item, state)

                if not state.get("note_added"):
                    note_id = await amocrm_client.add_lead_note(lead_id, note_text)
                    state["note_added"] = True
                    state["note_id"] = note_id
                    await _save_payload_state(session, item, state)

                if (report.requires_action or item.event_type == "report.task_requested") and not report.amocrm_task_id:
                    thresholds = await load_risk_thresholds(session)
                    due = datetime.now(UTC) + (
                        timedelta(hours=thresholds.critical_acknowledgement_hours)
                        if report.priority == Priority.CRITICAL
                        else timedelta(days=1)
                    )
                    task_id = await amocrm_client.create_task(
                        entity_id=lead_id,
                        responsible_user_id=responsible_user_id,
                        text=state.get("reason") or f"Review employee report {report.id}",
                        complete_till=due,
                    )
                    report.amocrm_task_id = task_id
                    state["task_created"] = True
                    state["task_id"] = task_id
                    await _save_payload_state(session, item, state)

            elif item.event_type == "report.resolved" and report.amocrm_lead_id and not state.get("resolved_synced"):
                await amocrm_client.mark_resolved(report.amocrm_lead_id)
                state["resolved_synced"] = True
                await _save_payload_state(session, item, state)

            item.status = IntegrationStatus.SUCCEEDED
            item.last_error = None
            item.next_attempt_at = None
            await session.commit()
        except Exception as exc:
            item = await session.get(IntegrationOutbox, item_id)
            if not item:
                return
            item.last_error = str(exc)[:5000]
            item.status = IntegrationStatus.DEAD if item.attempts >= 10 else IntegrationStatus.FAILED
            item.next_attempt_at = datetime.now(UTC) + timedelta(minutes=min(2**item.attempts, 60))
            await session.commit()


async def _claim_outbox() -> list[uuid.UUID]:
    now = datetime.now(UTC)
    stale_before = now - timedelta(minutes=15)
    async with SessionLocal() as session:
        retryable = and_(
            IntegrationOutbox.status.in_([IntegrationStatus.PENDING, IntegrationStatus.FAILED]),
            or_(IntegrationOutbox.next_attempt_at.is_(None), IntegrationOutbox.next_attempt_at <= now),
        )
        stale_processing = and_(
            IntegrationOutbox.status == IntegrationStatus.PROCESSING,
            IntegrationOutbox.updated_at <= stale_before,
        )
        stmt = (
            select(IntegrationOutbox)
            .where(or_(retryable, stale_processing))
            .order_by(IntegrationOutbox.created_at)
            .with_for_update(skip_locked=True)
            .limit(50)
        )
        items = list((await session.scalars(stmt)).all())
        for item in items:
            item.status = IntegrationStatus.PROCESSING
            item.attempts += 1
            item.next_attempt_at = None
        await session.commit()
        return [item.id for item in items]


async def _process_outbox() -> None:
    for item_id in await _claim_outbox():
        await _process_item(item_id)


async def _run() -> None:
    try:
        await _process_outbox()
    finally:
        await dispose_engine()


@celery_app.task(name="app.tasks.amocrm_sync.process_outbox")
def process_outbox() -> None:
    asyncio.run(_run())
