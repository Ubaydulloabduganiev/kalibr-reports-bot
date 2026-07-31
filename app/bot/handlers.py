from __future__ import annotations

import tempfile
import uuid
from datetime import date
from pathlib import Path

from aiogram import Bot, F, Router
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.bot.keyboards import collection_keyboard, confirmation_keyboard, deal_match_keyboard, language_keyboard, menu_keyboard
from app.bot.texts import t
from app.bot.utils import split_telegram_text
from app.core.database import SessionLocal
from app.core.models import Department, Employee, Language, ManagerActionType, MessageKind, Report, ReportRecipient, ReportStatus, ReportType
from app.services.activation import activate_employee
from app.services.amocrm import amocrm_client
from app.services.gemini import gemini_service
from app.services.reporting import (
    append_message,
    confirm_report,
    create_report_draft,
    get_employee_by_telegram,
    process_report,
    record_manager_action,
    render_structured_report,
)
from app.services.storage import object_storage

router = Router()


class ActivationStates(StatesGroup):
    choosing_language = State()
    entering_code = State()


class ReportStates(StatesGroup):
    collecting = State()
    clarifying = State()
    awaiting_confirmation = State()
    awaiting_deal = State()
    correcting = State()


class ManagerStates(StatesGroup):
    return_reason = State()
    comment = State()
    reassign = State()


async def _employee(message_or_callback) -> Employee | None:
    user_id = message_or_callback.from_user.id
    async with SessionLocal() as session:
        return await get_employee_by_telegram(session, user_id)


async def _show_menu(message: Message, employee: Employee) -> None:
    await message.answer(t(employee.language.value, "menu"), reply_markup=menu_keyboard(employee.language.value))


@router.message(CommandStart())
async def start(message: Message, state: FSMContext) -> None:
    async with SessionLocal() as session:
        employee = await get_employee_by_telegram(session, message.from_user.id)
    if employee:
        await state.clear()
        await _show_menu(message, employee)
        return
    await state.set_state(ActivationStates.choosing_language)
    await message.answer(t("uz", "choose_language"), reply_markup=language_keyboard())


@router.callback_query(ActivationStates.choosing_language, F.data.startswith("lang:"))
async def choose_language(callback: CallbackQuery, state: FSMContext) -> None:
    language = callback.data.split(":", 1)[1]
    await state.update_data(language=language)
    await state.set_state(ActivationStates.entering_code)
    await callback.message.edit_text(t(language, "enter_code"))
    await callback.answer()


@router.message(ActivationStates.entering_code)
async def enter_activation_code(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    language = data.get("language", "uz")
    async with SessionLocal() as session:
        try:
            employee = await activate_employee(
                session,
                code=message.text or "",
                telegram_user_id=message.from_user.id,
                telegram_username=message.from_user.username,
            )
            employee.language = Language(language)
            await session.commit()
        except ValueError:
            await message.answer(t(language, "invalid_code"))
            return
    await state.clear()
    await message.answer(t(language, "activated", name=employee.full_name), reply_markup=menu_keyboard(language))


async def _start_report(message: Message, state: FSMContext, report_type: ReportType) -> None:
    async with SessionLocal() as session:
        employee = await get_employee_by_telegram(session, message.from_user.id)
        if not employee:
            await message.answer(t("uz", "not_linked"))
            return
        report = await create_report_draft(session, employee=employee, report_type=report_type)
    await state.set_state(ReportStates.collecting)
    await state.update_data(report_id=str(report.id), language=employee.language.value)
    await message.answer(t(employee.language.value, "report_started"), reply_markup=collection_keyboard(employee.language.value))


@router.callback_query(F.data.startswith("scheduled:"))
async def scheduled_report_start(callback: CallbackQuery, state: FSMContext) -> None:
    report_type = ReportType(callback.data.split(":", 1)[1])
    async with SessionLocal() as session:
        employee = await get_employee_by_telegram(session, callback.from_user.id)
        if not employee:
            await callback.answer(t("uz", "not_linked"), show_alert=True)
            return
        report = await create_report_draft(session, employee=employee, report_type=report_type)
    await state.set_state(ReportStates.collecting)
    await state.update_data(report_id=str(report.id), language=employee.language.value)
    await callback.message.answer(t(employee.language.value, "report_started"), reply_markup=collection_keyboard(employee.language.value))
    await callback.answer()


@router.message(Command("report"))
async def command_report(message: Message, state: FSMContext) -> None:
    await _start_report(message, state, ReportType.DAILY)


@router.message(Command("weekly"))
async def command_weekly(message: Message, state: FSMContext) -> None:
    await _start_report(message, state, ReportType.WEEKLY)


@router.message(F.text.in_({"🗓 Kunlik hisobot", "🗓 Ежедневный отчёт"}))
async def menu_daily(message: Message, state: FSMContext) -> None:
    await _start_report(message, state, ReportType.DAILY)


@router.message(F.text.in_({"📊 Haftalik hisobot", "📊 Еженедельный отчёт"}))
async def menu_weekly(message: Message, state: FSMContext) -> None:
    await _start_report(message, state, ReportType.WEEKLY)


@router.message(F.text.in_({"🕘 Tarix", "🕘 История"}))
async def menu_history(message: Message) -> None:
    async with SessionLocal() as session:
        employee = await get_employee_by_telegram(session, message.from_user.id)
        if not employee:
            await message.answer(t("uz", "not_linked"))
            return
        reports = list((await session.scalars(
            select(Report).where(Report.employee_id == employee.id, Report.status != ReportStatus.DRAFT).order_by(Report.created_at.desc()).limit(10)
        )).all())
    if not reports:
        await message.answer(t(employee.language.value, "history_empty"))
        return
    text = "\n".join(f"• {r.report_date.isoformat()} — {r.report_type.value} — {r.status.value}" for r in reports)
    await message.answer(text)


@router.message(ReportStates.collecting, F.text)
async def collect_text(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    async with SessionLocal() as session:
        await append_message(
            session,
            report_id=uuid.UUID(data["report_id"]),
            kind=MessageKind.TEXT,
            text=message.text,
            telegram_message_id=message.message_id,
        )
    await message.answer(t(data["language"], "message_added"), reply_markup=collection_keyboard(data["language"]))


async def _download_telegram_file(bot: Bot, file_id: str, suffix: str) -> Path:
    telegram_file = await bot.get_file(file_id)
    temp = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
    temp.close()
    await bot.download_file(telegram_file.file_path, destination=temp.name)
    return Path(temp.name)


@router.message(ReportStates.collecting, F.voice)
async def collect_voice(message: Message, state: FSMContext, bot: Bot) -> None:
    data = await state.get_data()
    path = await _download_telegram_file(bot, message.voice.file_id, ".ogg")
    try:
        transcript = await gemini_service.transcribe_audio(path, data["language"])
        key = await object_storage.save(path, prefix=f"reports/{data['report_id']}/voice", filename=f"{message.message_id}.ogg")
        async with SessionLocal() as session:
            await append_message(
                session,
                report_id=uuid.UUID(data["report_id"]),
                kind=MessageKind.VOICE,
                text=transcript,
                telegram_message_id=message.message_id,
                file_key=key,
                mime_type="audio/ogg",
                file_size=message.voice.file_size,
            )
    finally:
        path.unlink(missing_ok=True)
    await message.answer(t(data["language"], "message_added"), reply_markup=collection_keyboard(data["language"]))


@router.message(ReportStates.collecting, F.photo)
async def collect_photo(message: Message, state: FSMContext, bot: Bot) -> None:
    data = await state.get_data()
    photo = message.photo[-1]
    path = await _download_telegram_file(bot, photo.file_id, ".jpg")
    try:
        extracted = await gemini_service.extract_file_text(path, "image/jpeg")
        key = await object_storage.save(path, prefix=f"reports/{data['report_id']}/photos", filename=f"{message.message_id}.jpg")
        async with SessionLocal() as session:
            await append_message(
                session,
                report_id=uuid.UUID(data["report_id"]),
                kind=MessageKind.PHOTO,
                text=extracted,
                telegram_message_id=message.message_id,
                file_key=key,
                mime_type="image/jpeg",
                file_size=photo.file_size,
            )
    finally:
        path.unlink(missing_ok=True)
    await message.answer(t(data["language"], "message_added"), reply_markup=collection_keyboard(data["language"]))


@router.message(ReportStates.collecting, F.document)
async def collect_document(message: Message, state: FSMContext, bot: Bot) -> None:
    data = await state.get_data()
    suffix = Path(message.document.file_name or "file.bin").suffix or ".bin"
    path = await _download_telegram_file(bot, message.document.file_id, suffix)
    try:
        extracted = await gemini_service.extract_file_text(path, message.document.mime_type)
        key = await object_storage.save(
            path,
            prefix=f"reports/{data['report_id']}/documents",
            filename=message.document.file_name or f"{message.message_id}{suffix}",
        )
        async with SessionLocal() as session:
            await append_message(
                session,
                report_id=uuid.UUID(data["report_id"]),
                kind=MessageKind.DOCUMENT,
                text=extracted,
                telegram_message_id=message.message_id,
                file_key=key,
                mime_type=message.document.mime_type,
                file_size=message.document.file_size,
            )
    finally:
        path.unlink(missing_ok=True)
    await message.answer(t(data["language"], "message_added"), reply_markup=collection_keyboard(data["language"]))


async def _send_preview(message: Message, state: FSMContext, report: Report, language: str) -> None:
    await state.set_state(ReportStates.awaiting_confirmation)
    chunks = split_telegram_text(t(language, "confirm_prompt") + "\n\n" + render_structured_report(report, language))
    for index, chunk in enumerate(chunks):
        await message.answer(
            chunk,
            reply_markup=confirmation_keyboard(language) if index == len(chunks) - 1 else None,
        )


@router.callback_query(ReportStates.collecting, F.data == "report:finish")
async def finish_report(callback: CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data()
    await callback.message.answer(t(data["language"], "processing"))
    async with SessionLocal() as session:
        try:
            report = await process_report(session, report_id=uuid.UUID(data["report_id"]))
        except Exception as exc:
            await callback.message.answer(f"❌ {exc}")
            await callback.answer()
            return
    if report.ai_questions:
        await state.set_state(ReportStates.clarifying)
        questions = "\n".join(f"• {q}" for q in report.ai_questions)
        await callback.message.answer(t(data["language"], "need_details", questions=questions))
    else:
        await _send_preview(callback.message, state, report, data["language"])
    await callback.answer()


@router.message(ReportStates.clarifying, F.text)
async def clarify_report(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    async with SessionLocal() as session:
        await append_message(
            session,
            report_id=uuid.UUID(data["report_id"]),
            kind=MessageKind.CORRECTION,
            text=message.text,
            telegram_message_id=message.message_id,
        )
        report = await process_report(session, report_id=uuid.UUID(data["report_id"]), correction=message.text)
    await _send_preview(message, state, report, data["language"])


async def _finalize_submission(callback: CallbackQuery, state: FSMContext, data: dict) -> None:
    async with SessionLocal() as session:
        report = await confirm_report(session, report_id=uuid.UUID(data["report_id"]))
    from app.tasks.amocrm_sync import process_outbox
    from app.tasks.notifications import notify_report
    notify_report.delay(str(report.id))
    process_outbox.delay()
    await state.clear()
    await callback.message.edit_reply_markup(reply_markup=None)
    await callback.message.answer(t(data["language"], "submitted"), reply_markup=menu_keyboard(data["language"]))
    await callback.answer()


@router.callback_query(ReportStates.awaiting_confirmation, F.data == "report:confirm")
async def confirm(callback: CallbackQuery, state: FSMContext, bot: Bot) -> None:
    data = await state.get_data()
    matches = []
    async with SessionLocal() as session:
        report = await session.get(Report, uuid.UUID(data["report_id"]))
        if not report:
            await callback.answer("Report not found", show_alert=True)
            return
        structured = report.structured_data or {}
        search_terms = list(structured.get("mentioned_phone_numbers") or []) + list(structured.get("mentioned_customer_names") or [])
    if amocrm_client.configured and search_terms:
        for term in search_terms[:3]:
            try:
                matches = await amocrm_client.find_leads(str(term), limit=5)
            except Exception:
                matches = []
            if matches:
                break
    if matches:
        await state.set_state(ReportStates.awaiting_deal)
        prompt = (
            "amoCRM bitimini tanlang yoki mos bitim yo‘qligini belgilang."
            if data["language"] == "uz"
            else "Выберите сделку amoCRM или укажите, что подходящей сделки нет."
        )
        await callback.message.edit_reply_markup(reply_markup=None)
        await callback.message.answer(prompt, reply_markup=deal_match_keyboard(matches, data["language"]))
        await callback.answer()
        return
    await _finalize_submission(callback, state, data)


@router.callback_query(ReportStates.awaiting_deal, F.data.startswith("deal:"))
async def choose_deal(callback: CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data()
    if callback.data.startswith("deal:link:"):
        deal_id = int(callback.data.rsplit(":", 1)[1])
        async with SessionLocal() as session:
            report = await session.get(Report, uuid.UUID(data["report_id"]))
            if not report:
                await callback.answer("Report not found", show_alert=True)
                return
            report.amocrm_deal_id = deal_id
            await session.commit()
    await _finalize_submission(callback, state, data)


@router.callback_query(ReportStates.awaiting_confirmation, F.data == "report:correct")
async def correct(callback: CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data()
    await state.set_state(ReportStates.correcting)
    await callback.message.answer(t(data["language"], "send_correction"))
    await callback.answer()


@router.message(ReportStates.correcting, F.text)
async def apply_correction(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    async with SessionLocal() as session:
        await append_message(
            session,
            report_id=uuid.UUID(data["report_id"]),
            kind=MessageKind.CORRECTION,
            text=message.text,
            telegram_message_id=message.message_id,
        )
        report = await process_report(session, report_id=uuid.UUID(data["report_id"]), correction=message.text)
    await _send_preview(message, state, report, data["language"])


@router.callback_query(ReportStates.awaiting_confirmation, F.data == "report:cancel")
async def cancel_report(callback: CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data()
    async with SessionLocal() as session:
        report = await session.get(Report, uuid.UUID(data["report_id"]))
        if report:
            report.status = ReportStatus.CANCELLED
            await session.commit()
    await state.clear()
    await callback.message.answer(t(data["language"], "cancelled"), reply_markup=menu_keyboard(data["language"]))
    await callback.answer()


async def _manager_can_access(session, actor: Employee, report_id: uuid.UUID) -> bool:
    report = await session.get(Report, report_id)
    if not report:
        return False
    if report.is_confidential and not actor.can_view_confidential:
        return False
    if "all_company" in actor.visibility_scopes:
        return True
    recipient = await session.scalar(
        select(ReportRecipient).where(
            ReportRecipient.report_id == report_id,
            ReportRecipient.employee_id == actor.id,
        )
    )
    return recipient is not None


@router.callback_query(F.data.startswith("mgr:"))
async def manager_action(callback: CallbackQuery, state: FSMContext, bot: Bot) -> None:
    _, action, report_id_raw = callback.data.split(":", 2)
    report_id = uuid.UUID(report_id_raw)
    async with SessionLocal() as session:
        actor = await get_employee_by_telegram(session, callback.from_user.id)
        if not actor:
            await callback.answer("Not linked", show_alert=True)
            return
        if not await _manager_can_access(session, actor, report_id):
            await callback.answer("Access denied", show_alert=True)
            return
        if action in {"return", "comment", "reassign"}:
            await state.update_data(manager_report_id=str(report_id), manager_action=action)
            state_map = {
                "return": ManagerStates.return_reason,
                "comment": ManagerStates.comment,
                "reassign": ManagerStates.reassign,
            }
            await state.set_state(state_map[action])
            prompts = {
                "return": "Enter the required return reason:",
                "comment": "Enter your comment:",
                "reassign": "Enter the new manager’s full name:",
            }
            await callback.message.answer(prompts[action])
            await callback.answer()
            return
        action_map = {
            "approve": ManagerActionType.APPROVE,
            "task": ManagerActionType.CREATE_TASK,
            "escalate": ManagerActionType.ESCALATE,
            "resolve": ManagerActionType.RESOLVE,
        }
        if action in action_map:
            try:
                report = await record_manager_action(session, report_id=report_id, actor=actor, action_type=action_map[action])
            except (ValueError, PermissionError) as exc:
                await callback.answer(str(exc), show_alert=True)
                return
            if action == "task":
                from app.tasks.amocrm_sync import process_outbox
                process_outbox.delay()
            await callback.answer(f"Done: {action}", show_alert=True)
            return
        if action == "history":
            report = await session.get(Report, report_id)
            reports = list((await session.scalars(
                select(Report).where(Report.employee_id == report.employee_id).order_by(Report.created_at.desc()).limit(10)
            )).all())
            await callback.message.answer("\n".join(f"• {r.report_date}: {r.status.value}" for r in reports))
            await callback.answer()
            return
        if action == "summary":
            report = await session.get(Report, report_id, options=[selectinload(Report.employee).selectinload(Employee.departments)])
            department_ids = [d.id for d in report.employee.departments]
            employee_ids = list((await session.scalars(
                select(Employee.id).where(Employee.departments.any(Department.id == department_ids[0]))
            )).all()) if department_ids else []
            recent = list((await session.scalars(
                select(Report).where(Report.employee_id.in_(employee_ids), Report.report_date == date.today()).order_by(Report.priority.desc())
            )).all()) if employee_ids else []
            await callback.message.answer(f"Today: {len(recent)} reports; critical/high: {sum(r.priority.value in {'critical','high'} for r in recent)}")
            await callback.answer()


@router.message(ManagerStates.return_reason, F.text)
async def manager_return_reason(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    report_id = uuid.UUID(data["manager_report_id"])
    async with SessionLocal() as session:
        actor = await get_employee_by_telegram(session, message.from_user.id)
        if not actor or not await _manager_can_access(session, actor, report_id):
            await state.clear()
            await message.answer("Access denied")
            return
        report = await record_manager_action(
            session,
            report_id=report_id,
            actor=actor,
            action_type=ManagerActionType.RETURN,
            reason=message.text,
        )
        employee = await session.get(Employee, report.employee_id)
    if employee and employee.telegram_user_id:
        await message.bot.send_message(employee.telegram_user_id, t(employee.language.value, "returned", reason=message.text))
    await state.clear()
    await message.answer("Done")


@router.message(ManagerStates.comment, F.text)
async def manager_comment(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    report_id = uuid.UUID(data["manager_report_id"])
    async with SessionLocal() as session:
        actor = await get_employee_by_telegram(session, message.from_user.id)
        if not actor or not await _manager_can_access(session, actor, report_id):
            await state.clear()
            await message.answer("Access denied")
            return
        report = await record_manager_action(
            session,
            report_id=report_id,
            actor=actor,
            action_type=ManagerActionType.COMMENT,
            reason=message.text,
        )
        employee = await session.get(Employee, report.employee_id)
    if employee and employee.telegram_user_id:
        await message.bot.send_message(employee.telegram_user_id, f"💬 {actor.full_name}: {message.text}")
    await state.clear()
    await message.answer("Done")


@router.message(ManagerStates.reassign, F.text)
async def manager_reassign(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    report_id = uuid.UUID(data["manager_report_id"])
    async with SessionLocal() as session:
        actor = await get_employee_by_telegram(session, message.from_user.id)
        if not actor or not await _manager_can_access(session, actor, report_id):
            await state.clear()
            await message.answer("Access denied")
            return
        report = await session.get(Report, report_id)
        matches = list((await session.scalars(
            select(Employee).where(Employee.full_name.ilike(f"%{message.text}%"), Employee.can_receive_reports.is_(True), Employee.is_active.is_(True)).limit(5)
        )).all())
        if report and report.is_confidential:
            matches = [candidate for candidate in matches if candidate.can_view_confidential]
        if len(matches) != 1:
            await message.answer("Manager not uniquely found or lacks access. Enter a more exact full name.")
            return
        report.current_responsible_id = matches[0].id
        existing_recipient = await session.scalar(
            select(ReportRecipient).where(ReportRecipient.report_id == report.id, ReportRecipient.employee_id == matches[0].id)
        )
        if not existing_recipient:
            session.add(ReportRecipient(report_id=report.id, employee_id=matches[0].id, routing_reason="manager_reassignment"))
        await record_manager_action(
            session,
            report_id=report.id,
            actor=actor,
            action_type=ManagerActionType.REASSIGN,
            reason=f"Reassigned to {matches[0].full_name}",
            metadata={"assignee_id": str(matches[0].id)},
        )
    if matches[0].telegram_user_id:
        await message.bot.send_message(matches[0].telegram_user_id, f"A report was reassigned to you: {report.id}")
    await state.clear()
    await message.answer("Done")
