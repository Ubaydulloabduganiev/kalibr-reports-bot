from __future__ import annotations

import asyncio
import uuid

from aiogram import Bot
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

from app.core.config import settings
from app.core.database import dispose_engine
from app.services.notifications import notify_report_recipients
from app.tasks.celery_app import celery_app


async def _notify(report_id: uuid.UUID) -> None:
    if not settings.telegram_bot_token:
        raise RuntimeError("TELEGRAM_BOT_TOKEN is not configured")
    bot = Bot(settings.telegram_bot_token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    try:
        await notify_report_recipients(report_id, bot)
    finally:
        await bot.session.close()


@celery_app.task(
    name="app.tasks.notifications.notify_report",
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_jitter=True,
    max_retries=8,
)
def notify_report(report_id: str) -> None:
    async def runner() -> None:
        try:
            await _notify(uuid.UUID(report_id))
        finally:
            await dispose_engine()
    asyncio.run(runner())
