from __future__ import annotations

import uuid
from html import escape
from datetime import UTC, datetime

from aiogram import Bot
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.bot.keyboards import manager_keyboard
from app.bot.utils import split_telegram_text
from app.core.database import SessionLocal
from app.core.models import Employee, Report, ReportRecipient
from app.services.reporting import render_structured_report


async def notify_report_recipients(report_id: uuid.UUID, bot: Bot) -> int:
    async with SessionLocal() as session:
        stmt = (
            select(Report)
            .where(Report.id == report_id)
            .options(
                selectinload(Report.employee).selectinload(Employee.departments),
                selectinload(Report.recipients).selectinload(ReportRecipient.employee),
            )
        )
        report = (await session.execute(stmt)).scalar_one()
        sent = 0
        for recipient in report.recipients:
            manager = recipient.employee
            if recipient.notified_at or not manager.telegram_user_id:
                continue
            if report.is_confidential and not manager.can_view_confidential:
                continue
            language = manager.language.value
            department = ", ".join(d.name_uz if language == "uz" else d.name_ru for d in report.employee.departments)
            header = (
                f"<b>{'Yangi xodim hisoboti' if language == 'uz' else 'Новый отчёт сотрудника'}</b>\n"
                f"👤 {escape(report.employee.full_name)}\n"
                f"🏢 {escape(department or '—')}\n"
                f"🔒 {'Ha' if report.is_confidential and language == 'uz' else 'Да' if report.is_confidential else 'No'}\n\n"
            )
            chunks = split_telegram_text(header + render_structured_report(report, language))
            for index, chunk in enumerate(chunks):
                await bot.send_message(
                    manager.telegram_user_id,
                    chunk,
                    reply_markup=manager_keyboard(str(report.id)) if index == len(chunks) - 1 else None,
                )
            recipient.notified_at = datetime.now(UTC)
            sent += 1
        await session.commit()
        return sent
