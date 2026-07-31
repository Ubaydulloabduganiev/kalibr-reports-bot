from __future__ import annotations

import uuid
from html import escape
from datetime import UTC, date, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.models import (
    Employee,
    EmployeeKPITarget,
    KPIDefinition,
    IntegrationOutbox,
    ManagerAction,
    ManagerActionType,
    MessageKind,
    Priority,
    Report,
    ReportMessage,
    ReportRecipient,
    PromptDelivery,
    ReportSchedule,
    ScheduleKind,
    ReportStatus,
    ReportTemplate,
    ReportType,
)
from app.schemas import StructuredReport
from app.services.gemini import gemini_service
from app.services.risk_rules import apply_deterministic_risk_rules, load_risk_thresholds


async def employee_context(session: AsyncSession, employee: Employee, report_type: ReportType, report_date: date) -> str:
    roles = ", ".join(role.name_uz for role in employee.roles) or "unspecified"
    departments = ", ".join(dep.name_uz for dep in employee.departments) or "unspecified"
    branches = ", ".join(branch.name_uz for branch in employee.branches) or "unspecified"
    period = "weekly" if report_type == ReportType.WEEKLY else "daily"
    targets = list((await session.execute(
        select(EmployeeKPITarget, KPIDefinition)
        .join(KPIDefinition, KPIDefinition.id == EmployeeKPITarget.kpi_definition_id)
        .where(
            EmployeeKPITarget.employee_id == employee.id,
            EmployeeKPITarget.period == period,
            EmployeeKPITarget.effective_from <= report_date,
            (EmployeeKPITarget.effective_to.is_(None) | (EmployeeKPITarget.effective_to >= report_date)),
            KPIDefinition.is_active.is_(True),
        )
    )).all())
    target_text = "; ".join(
        f"{definition.name_uz}: {target.target_value:g} {definition.unit}"
        for target, definition in targets
    ) or "none configured"
    return (
        f"Employee: {employee.full_name}; roles: {roles}; departments: {departments}; "
        f"branches: {branches}; {period} KPI targets: {target_text}"
    )


async def get_employee_by_telegram(session: AsyncSession, telegram_user_id: int) -> Employee | None:
    stmt = (
        select(Employee)
        .where(Employee.telegram_user_id == telegram_user_id, Employee.is_active.is_(True))
        .options(
            selectinload(Employee.roles),
            selectinload(Employee.departments),
            selectinload(Employee.branches),
            selectinload(Employee.extra_recipients),
            selectinload(Employee.direct_manager),
        )
    )
    return (await session.execute(stmt)).scalar_one_or_none()


async def create_report_draft(
    session: AsyncSession,
    *,
    employee: Employee,
    report_type: ReportType,
    report_date: date | None = None,
) -> Report:
    selected_date = report_date or date.today()
    if selected_date < date.today() - timedelta(days=3):
        raise ValueError("Reports older than three days require manager approval")
    report = Report(
        employee_id=employee.id,
        report_type=report_type,
        report_date=selected_date,
        language=employee.language.value,
        status=ReportStatus.DRAFT,
    )
    session.add(report)
    await session.commit()
    await session.refresh(report)
    return report


async def append_message(
    session: AsyncSession,
    *,
    report_id: uuid.UUID,
    kind: MessageKind,
    text: str,
    telegram_message_id: int | None = None,
    file_key: str | None = None,
    mime_type: str | None = None,
    file_size: int | None = None,
) -> ReportMessage:
    report = await session.get(Report, report_id)
    if not report or report.status not in {ReportStatus.DRAFT, ReportStatus.RETURNED, ReportStatus.AWAITING_CONFIRMATION}:
        raise ValueError("Report is not editable")
    message = ReportMessage(
        report_id=report_id,
        kind=kind,
        text=text,
        telegram_message_id=telegram_message_id,
        file_key=file_key,
        mime_type=mime_type,
        file_size=file_size,
    )
    session.add(message)
    await session.commit()
    await session.refresh(message)
    return message


async def _load_report(session: AsyncSession, report_id: uuid.UUID) -> Report:
    stmt = (
        select(Report)
        .where(Report.id == report_id)
        .options(
            selectinload(Report.employee).selectinload(Employee.roles),
            selectinload(Report.employee).selectinload(Employee.departments),
            selectinload(Report.employee).selectinload(Employee.branches),
            selectinload(Report.employee).selectinload(Employee.extra_recipients),
            selectinload(Report.employee).selectinload(Employee.direct_manager),
            selectinload(Report.messages),
            selectinload(Report.recipients),
        )
    )
    report = (await session.execute(stmt)).scalar_one_or_none()
    if not report:
        raise ValueError("Report not found")
    return report


async def _role_questions(session: AsyncSession, report: Report) -> list[str]:
    department_ids = [dep.id for dep in report.employee.departments]
    role_ids = [role.id for role in report.employee.roles]
    stmt = select(ReportTemplate).where(
        ReportTemplate.report_type == report.report_type,
        ReportTemplate.is_active.is_(True),
    )
    templates = list((await session.scalars(stmt)).all())
    result: list[str] = []
    for template in templates:
        if template.department_id and template.department_id not in department_ids:
            continue
        if template.role_id and template.role_id not in role_ids:
            continue
        result.extend(template.questions_uz if report.language == "uz" else template.questions_ru)
    return list(dict.fromkeys(result))


async def process_report(
    session: AsyncSession,
    *,
    report_id: uuid.UUID,
    correction: str | None = None,
) -> Report:
    report = await _load_report(session, report_id)
    previous_status = report.status
    report.status = ReportStatus.PROCESSING
    await session.commit()

    original = "\n".join(message.text for message in sorted(report.messages, key=lambda m: m.created_at) if message.text)
    if not original.strip():
        report.status = ReportStatus.DRAFT
        await session.commit()
        raise ValueError("The report has no readable content")

    prior = StructuredReport.model_validate(report.structured_data) if report.structured_data else None
    try:
        structured = await gemini_service.extract_report(
            original_text=original,
            employee_context=await employee_context(session, report.employee, report.report_type, report.report_date),
            report_type=report.report_type.value,
            role_questions=await _role_questions(session, report),
            prior_structured=prior,
            correction=correction,
        )
    except Exception:
        report.status = previous_status if previous_status != ReportStatus.PROCESSING else ReportStatus.DRAFT
        await session.commit()
        raise

    structured = apply_deterministic_risk_rules(structured, await load_risk_thresholds(session))
    report.original_text = original
    report.structured_data = structured.model_dump(mode="json")
    report.ai_confidence = structured.confidence
    report.ai_questions = structured.clarification_questions
    report.priority = structured.suggested_priority
    report.is_confidential = structured.confidential
    report.requires_action = structured.requires_action
    report.status = ReportStatus.AWAITING_CONFIRMATION
    report.version += 1
    await session.commit()
    await session.refresh(report)
    return report


async def confirm_report(session: AsyncSession, *, report_id: uuid.UUID) -> Report:
    report = await _load_report(session, report_id)
    if report.status != ReportStatus.AWAITING_CONFIRMATION:
        raise ValueError("Report is not awaiting confirmation")

    now = datetime.now(UTC)
    report.status = ReportStatus.SUBMITTED
    report.submitted_at = now
    report.confirmed_at = now
    if report.priority == Priority.CRITICAL:
        thresholds = await load_risk_thresholds(session)
        report.acknowledgement_due_at = now + timedelta(hours=thresholds.critical_acknowledgement_hours)

    recipient_ids: set[uuid.UUID] = set()
    responsible_id: uuid.UUID | None = None
    recipients: list[tuple[Employee, str]] = []
    if report.employee.direct_manager:
        recipients.append((report.employee.direct_manager, "direct_manager"))
    recipients.extend((recipient, "additional_recipient") for recipient in report.employee.extra_recipients)

    # Confidential reports are never routed by title alone. The recipient must
    # have explicit confidential access. If the configured chain has no such
    # person, route to approved all-company confidential recipients instead.
    if report.is_confidential:
        recipients = [(employee, reason) for employee, reason in recipients if employee.can_view_confidential]
        if not recipients:
            fallbacks = list((await session.scalars(
                select(Employee).where(
                    Employee.is_active.is_(True),
                    Employee.can_receive_reports.is_(True),
                    Employee.can_view_confidential.is_(True),
                )
            )).all())
            recipients.extend(
                (employee, "confidential_fallback")
                for employee in fallbacks
                if "all_company" in employee.visibility_scopes
            )

    for employee, reason in recipients:
        if employee.id in recipient_ids:
            continue
        recipient_ids.add(employee.id)
        responsible_id = responsible_id or employee.id
        session.add(ReportRecipient(report_id=report.id, employee_id=employee.id, routing_reason=reason))

    report.current_responsible_id = responsible_id

    deliveries = list((await session.scalars(
        select(PromptDelivery).where(
            PromptDelivery.employee_id == report.employee_id,
            PromptDelivery.delivery_date == report.report_date,
            PromptDelivery.completed_report_id.is_(None),
        )
    )).all())
    for delivery in deliveries:
        schedule = await session.get(ReportSchedule, delivery.schedule_id)
        if not schedule:
            continue
        expected_kind = ScheduleKind.WEEKLY_PROMPT if report.report_type == ReportType.WEEKLY else ScheduleKind.DAILY_PROMPT
        if schedule.kind == expected_kind:
            delivery.completed_report_id = report.id

    if report.requires_action or report.priority in {Priority.HIGH, Priority.CRITICAL} or report.amocrm_deal_id:
        session.add(
            IntegrationOutbox(
                event_type="report.submitted",
                aggregate_id=report.id,
                idempotency_key=f"report.submitted:{report.id}:v{report.version}",
                payload={"report_id": str(report.id)},
            )
        )
    await session.commit()
    return await _load_report(session, report_id)


async def record_manager_action(
    session: AsyncSession,
    *,
    report_id: uuid.UUID,
    actor: Employee,
    action_type: ManagerActionType,
    reason: str | None = None,
    metadata: dict | None = None,
) -> Report:
    report = await _load_report(session, report_id)
    allowed_ids = {recipient.employee_id for recipient in report.recipients}
    if report.is_confidential and not actor.can_view_confidential:
        raise PermissionError("Confidential report access denied")
    if actor.id not in allowed_ids and "all_company" not in actor.visibility_scopes:
        raise PermissionError("You are not a recipient of this report")
    if action_type == ManagerActionType.RETURN and not reason:
        raise ValueError("A reason is required when returning a report")

    session.add(
        ManagerAction(
            report_id=report.id,
            actor_employee_id=actor.id,
            action_type=action_type,
            reason=reason,
            metadata_json=metadata or {},
        )
    )
    now = datetime.now(UTC)
    if action_type == ManagerActionType.APPROVE:
        report.status = ReportStatus.APPROVED
        report.acknowledged_at = now
    elif action_type == ManagerActionType.RETURN:
        report.status = ReportStatus.RETURNED
        report.acknowledged_at = now
    elif action_type == ManagerActionType.ESCALATE:
        report.status = ReportStatus.ESCALATED
    elif action_type == ManagerActionType.RESOLVE:
        report.status = ReportStatus.RESOLVED
        report.acknowledged_at = report.acknowledged_at or now
        if report.amocrm_lead_id:
            session.add(
                IntegrationOutbox(
                    event_type="report.resolved",
                    aggregate_id=report.id,
                    idempotency_key=f"report.resolved:{report.id}:v{report.version}",
                    payload={"report_id": str(report.id)},
                )
            )
    elif action_type == ManagerActionType.CREATE_TASK:
        report.requires_action = True
        report.status = ReportStatus.ACTION_REQUIRED
        session.add(
            IntegrationOutbox(
                event_type="report.task_requested",
                aggregate_id=report.id,
                idempotency_key=f"report.task_requested:{report.id}:{uuid.uuid4().hex}",
                payload={"report_id": str(report.id), "reason": reason or "Manager requested a task"},
            )
        )
    await session.commit()
    return await _load_report(session, report_id)


def render_structured_report(report: Report, language: str = "uz") -> str:
    data = StructuredReport.model_validate(report.structured_data)
    if language == "ru":
        labels = {
            "title": "Отчёт",
            "completed": "Выполнено",
            "results": "Измеримые результаты",
            "unfinished": "Не завершено",
            "blockers": "Проблемы и блокеры",
            "help": "Нужна помощь/согласование",
            "plan": "План на завтра",
            "urgent": "Срочно",
            "priority": "Приоритет",
        }
    else:
        labels = {
            "title": "Hisobot",
            "completed": "Bajarildi",
            "results": "O‘lchanadigan natijalar",
            "unfinished": "Tugallanmagan",
            "blockers": "Muammo va blokatorlar",
            "help": "Yordam/tasdiq kerak",
            "plan": "Ertangi reja",
            "urgent": "Shoshilinch",
            "priority": "Ustuvorlik",
        }

    def block(label: str, items: list[str]) -> str:
        return f"\n<b>{escape(label)}:</b>\n" + ("\n".join(f"• {escape(str(item))}" for item in items) if items else "—")

    text = f"<b>{labels['title']} — {report.report_date.isoformat()}</b>"
    text += block(labels["completed"], data.completed)
    text += block(labels["results"], data.measurable_results)
    if data.kpis:
        text += "\n<b>KPI:</b>\n" + "\n".join(f"• {escape(kpi.label)}: {kpi.value:g} {escape(kpi.unit)}" for kpi in data.kpis)
    text += block(labels["unfinished"], data.unfinished)
    text += block(labels["blockers"], data.blockers)
    text += block(labels["help"], data.help_or_approval)
    text += block(labels["plan"], data.tomorrow_plan)
    if data.urgent_summary:
        text += f"\n<b>{labels['urgent']}:</b> {data.urgent_summary}"
    text += f"\n\n<b>{labels['priority']}:</b> {report.priority.value.upper()}"
    return text
