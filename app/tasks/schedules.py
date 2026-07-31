from __future__ import annotations

import asyncio
from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

from aiogram import Bot
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from sqlalchemy import func, or_, select
from sqlalchemy.orm import selectinload

from app.core.config import settings
from app.core.database import SessionLocal, dispose_engine
from app.core.models import (
    ComplianceIncident,
    Department,
    Employee,
    Priority,
    PromptDelivery,
    Report,
    ReportRecipient,
    ReportSchedule,
    ReportStatus,
    ReportType,
    Role,
    ScheduleKind,
    SystemSetting,
)
from app.services.risk_rules import load_risk_thresholds
from app.tasks.celery_app import celery_app

TZ = ZoneInfo(settings.app_timezone)


def _bot() -> Bot:
    return Bot(settings.telegram_bot_token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))


def _matches_minute(schedule: ReportSchedule, now_local: datetime) -> bool:
    if schedule.weekday is not None and schedule.weekday != now_local.weekday():
        return False
    return schedule.local_time.hour == now_local.hour and schedule.local_time.minute == now_local.minute


async def _eligible_employees(session, schedule: ReportSchedule) -> list[Employee]:
    stmt = (
        select(Employee)
        .where(Employee.is_active.is_(True), Employee.telegram_user_id.is_not(None))
        .options(selectinload(Employee.departments), selectinload(Employee.roles), selectinload(Employee.direct_manager))
    )
    employees = list((await session.scalars(stmt)).unique().all())
    result: list[Employee] = []
    for employee in employees:
        if schedule.department_id and all(d.id != schedule.department_id for d in employee.departments):
            continue
        if schedule.role_id and all(r.id != schedule.role_id for r in employee.roles):
            continue
        is_manager = any(role.is_manager for role in employee.roles)
        if schedule.group_code == "managers" and not is_manager:
            continue
        if schedule.group_code not in {"managers", "all", None} and is_manager:
            continue
        if schedule.group_code and schedule.group_code not in {"managers", "all"}:
            if all(department.group_code != schedule.group_code for department in employee.departments):
                continue
        result.append(employee)
    return result


async def _send_prompt(bot: Bot, employee: Employee, schedule: ReportSchedule, report_type: ReportType) -> None:
    language = employee.language.value
    if report_type == ReportType.WEEKLY:
        text = "📊 Haftalik hisobotingizni yuboring." if language == "uz" else "📊 Отправьте еженедельный отчёт."
    else:
        text = "🗓 Kunlik hisobotingizni yuboring." if language == "uz" else "🗓 Отправьте ежедневный отчёт."
    button = "Hisobotni boshlash" if language == "uz" else "Начать отчёт"
    await bot.send_message(
        employee.telegram_user_id,
        text,
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[[InlineKeyboardButton(text=button, callback_data=f"scheduled:{report_type.value}")]]
        ),
    )


async def _summary_text(session, *, weekly: bool = False, monthly: bool = False) -> str:
    today = datetime.now(TZ).date()
    start_date = today.replace(day=1) if monthly else today - timedelta(days=6) if weekly else today
    reports = list((await session.scalars(
        select(Report).where(Report.report_date.between(start_date, today), Report.status.notin_([ReportStatus.DRAFT, ReportStatus.CANCELLED]))
    )).all())
    total_active = await session.scalar(select(func.count(Employee.id)).where(Employee.is_active.is_(True))) or 0
    critical = [r for r in reports if r.priority == Priority.CRITICAL and r.status != ReportStatus.RESOLVED]
    high = [r for r in reports if r.priority == Priority.HIGH and r.status != ReportStatus.RESOLVED]
    unresolved = [r for r in reports if r.requires_action and r.status != ReportStatus.RESOLVED]
    label = "Oylik" if monthly else "Haftalik" if weekly else "Kunlik"
    return (
        f"<b>{label} rahbariyat xulosasi</b>\n"
        f"Davr: {start_date} — {today}\n\n"
        f"• Faol xodimlar: {total_active}\n"
        f"• Hisobotlar: {len(reports)}\n"
        f"• Ochiq kritik: {len(critical)}\n"
        f"• Ochiq yuqori: {len(high)}\n"
        f"• Yechilmagan harakatlar: {len(unresolved)}\n"
        f"• Hisobot bermaganlar compliance bo‘limida ko‘rsatiladi."
    )


async def _send_summary(bot: Bot, session, weekly: bool = False, monthly: bool = False) -> None:
    recipients = list((await session.scalars(
        select(Employee).where(
            Employee.is_active.is_(True),
            Employee.telegram_user_id.is_not(None),
            Employee.can_receive_reports.is_(True),
        )
    )).all())
    text = await _summary_text(session, weekly=weekly, monthly=monthly)
    for employee in recipients:
        if "all_company" in employee.visibility_scopes:
            await bot.send_message(employee.telegram_user_id, text)


async def _handle_deliveries(bot: Bot, session, now_local: datetime) -> None:
    schedules = list((await session.scalars(select(ReportSchedule).where(ReportSchedule.is_active.is_(True)))).all())
    for schedule in schedules:
        if schedule.kind in {ScheduleKind.DAILY_SUMMARY, ScheduleKind.WEEKLY_SUMMARY, ScheduleKind.MONTHLY_SUMMARY}:
            if _matches_minute(schedule, now_local):
                monthly = schedule.kind == ScheduleKind.MONTHLY_SUMMARY
                tomorrow = now_local.date() + timedelta(days=1)
                if monthly and tomorrow.month == now_local.month:
                    continue
                period_key = now_local.strftime("%Y-%m") if monthly else now_local.date().isoformat()
                delivery_key = f"summary:{schedule.kind.value}:{period_key}"
                already_sent = await session.get(SystemSetting, delivery_key)
                if not already_sent:
                    await _send_summary(
                        bot,
                        session,
                        weekly=schedule.kind == ScheduleKind.WEEKLY_SUMMARY,
                        monthly=monthly,
                    )
                    session.add(SystemSetting(key=delivery_key, value={"sent_at": now_local.isoformat()}))
            continue
        if not _matches_minute(schedule, now_local):
            continue
        report_type = ReportType.WEEKLY if schedule.kind == ScheduleKind.WEEKLY_PROMPT else ReportType.DAILY
        for employee in await _eligible_employees(session, schedule):
            existing = await session.scalar(
                select(PromptDelivery).where(
                    PromptDelivery.employee_id == employee.id,
                    PromptDelivery.schedule_id == schedule.id,
                    PromptDelivery.delivery_date == now_local.date(),
                )
            )
            if existing and existing.sent_at:
                continue
            delivery = existing or PromptDelivery(
                employee_id=employee.id,
                schedule_id=schedule.id,
                delivery_date=now_local.date(),
            )
            if not existing:
                session.add(delivery)
                await session.commit()
            await _send_prompt(bot, employee, schedule, report_type)
            delivery.sent_at = datetime.now(UTC)
            await session.commit()
    await session.commit()


async def _handle_reminders_and_overdue(bot: Bot, session, now_utc: datetime) -> None:
    # Relationship is intentionally queried manually because schedule_id is scalar.
    cutoff = datetime.now(TZ).date() - timedelta(days=35)
    deliveries = list((await session.scalars(
        select(PromptDelivery).where(
            PromptDelivery.completed_report_id.is_(None),
            PromptDelivery.delivery_date >= cutoff,
        )
    )).all())
    for delivery in deliveries:
        schedule = await session.get(ReportSchedule, delivery.schedule_id)
        employee = await session.get(Employee, delivery.employee_id)
        if not schedule or not employee or not employee.telegram_user_id or not delivery.sent_at:
            continue
        elapsed = (now_utc - delivery.sent_at).total_seconds() / 60
        if elapsed >= schedule.first_reminder_minutes and not delivery.first_reminder_at:
            await bot.send_message(employee.telegram_user_id, "⏰ Hisobot eslatmasi / Напоминание об отчёте")
            delivery.first_reminder_at = now_utc
        if elapsed >= schedule.final_reminder_minutes and not delivery.final_reminder_at:
            await bot.send_message(employee.telegram_user_id, "⚠️ Yakuniy eslatma / Последнее напоминание")
            delivery.final_reminder_at = now_utc
        if elapsed >= schedule.grace_minutes and not delivery.overdue_at:
            report_type = ReportType.WEEKLY if schedule.kind == ScheduleKind.WEEKLY_PROMPT else ReportType.DAILY
            report = await session.scalar(
                select(Report).where(
                    Report.employee_id == employee.id,
                    Report.report_date == delivery.delivery_date,
                    Report.report_type == report_type,
                    Report.status.notin_([ReportStatus.DRAFT, ReportStatus.CANCELLED]),
                )
            )
            if report:
                delivery.completed_report_id = report.id
                continue
            delivery.overdue_at = now_utc
            since = delivery.delivery_date - timedelta(days=30)
            missed_count = await session.scalar(
                select(func.count(PromptDelivery.id)).where(
                    PromptDelivery.employee_id == employee.id,
                    PromptDelivery.delivery_date >= since,
                    PromptDelivery.overdue_at.is_not(None),
                )
            ) or 0
            new_count = missed_count + 1
            level = 1 if new_count == 1 else 2 if new_count == 2 else 3 if new_count == 3 else 4 if new_count == 4 else 5
            session.add(
                ComplianceIncident(
                    employee_id=employee.id,
                    incident_date=delivery.delivery_date,
                    missed_count_30d=new_count,
                    level=level,
                    reason_required=new_count >= 2,
                )
            )
            if employee.direct_manager_id:
                manager = await session.get(Employee, employee.direct_manager_id)
                if manager and manager.telegram_user_id:
                    await bot.send_message(
                        manager.telegram_user_id,
                        f"⚠️ {employee.full_name} reportni o‘z vaqtida topshirmadi. 30 kunlik holat: {new_count}.",
                    )
    await session.commit()


async def _dispatch() -> None:
    if not settings.telegram_bot_token:
        return
    now_local = datetime.now(TZ)
    now_utc = datetime.now(UTC)
    bot = _bot()
    try:
        async with SessionLocal() as session:
            await _handle_deliveries(bot, session, now_local)
            await _handle_reminders_and_overdue(bot, session, now_utc)
    finally:
        await bot.session.close()


@celery_app.task(name="app.tasks.schedules.dispatch_report_schedules")
def dispatch_report_schedules() -> None:
    async def runner() -> None:
        try:
            await _dispatch()
        finally:
            await dispose_engine()
    asyncio.run(runner())


async def _check_critical() -> None:
    if not settings.telegram_bot_token:
        return
    now = datetime.now(UTC)
    bot = _bot()
    try:
        async with SessionLocal() as session:
            reports = list((await session.scalars(
                select(Report).where(
                    Report.priority == Priority.CRITICAL,
                    Report.acknowledgement_due_at <= now,
                    Report.acknowledged_at.is_(None),
                    Report.status.notin_([ReportStatus.RESOLVED, ReportStatus.CANCELLED]),
                ).options(selectinload(Report.current_responsible).selectinload(Employee.direct_manager))
            )).all())
            thresholds = await load_risk_thresholds(session)
            for report in reports:
                current = report.current_responsible
                superior = current.direct_manager if current else None
                if superior and report.is_confidential and not superior.can_view_confidential:
                    superior = None
                if not superior:
                    candidates = list((await session.scalars(
                        select(Employee).where(
                            Employee.is_active.is_(True),
                            Employee.can_receive_reports.is_(True),
                            Employee.telegram_user_id.is_not(None),
                        )
                    )).all())
                    superior = next((
                        candidate for candidate in candidates
                        if candidate.id != report.current_responsible_id
                        and "all_company" in candidate.visibility_scopes
                        and (not report.is_confidential or candidate.can_view_confidential)
                    ), None)
                if superior and superior.telegram_user_id:
                    exists = await session.scalar(
                        select(ReportRecipient).where(ReportRecipient.report_id == report.id, ReportRecipient.employee_id == superior.id)
                    )
                    if not exists:
                        session.add(ReportRecipient(report_id=report.id, employee_id=superior.id, routing_reason="two_hour_escalation"))
                    report.current_responsible_id = superior.id
                    report.status = ReportStatus.ESCALATED
                    report.acknowledgement_due_at = now + timedelta(hours=thresholds.critical_acknowledgement_hours)
                    await bot.send_message(superior.telegram_user_id, f"🚨 2 soat ichida tasdiqlanmagan kritik hisobot: {report.id}")
            await session.commit()
    finally:
        await bot.session.close()


@celery_app.task(name="app.tasks.schedules.check_critical_acknowledgements")
def check_critical_acknowledgements() -> None:
    async def runner() -> None:
        try:
            await _check_critical()
        finally:
            await dispose_engine()
    asyncio.run(runner())
