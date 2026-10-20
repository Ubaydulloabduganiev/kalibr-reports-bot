import asyncio
import os
from contextlib import asynccontextmanager, suppress
from pathlib import Path

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import Update
from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app.api.router import api_router
from app.bot.handlers import router as telegram_router
from app.core.config import settings
from app.core.database import init_db
from app.tasks.amocrm_sync import _process_outbox
from app.tasks.schedules import _check_critical, _dispatch

BASE_DIR = Path(__file__).resolve().parent
templates = Jinja2Templates(directory=BASE_DIR / "templates")

bot: Bot | None = None
dispatcher: Dispatcher | None = None
scheduler_task: asyncio.Task | None = None
tick_lock = asyncio.Lock()


async def _run_tick() -> None:
    """Run scheduled work without Redis/Celery for the free pilot."""
    async with tick_lock:
        await _dispatch()
        await _check_critical()
        await _process_outbox()


async def _scheduler_loop() -> None:
    """Run minute-level schedules while the free web service is awake."""
    while True:
        try:
            await _run_tick()
        except asyncio.CancelledError:
            raise
        except Exception:
            # A failed tick must not stop future reminders/sync attempts.
            pass
        await asyncio.sleep(60)


@asynccontextmanager
async def lifespan(_: FastAPI):
    global bot, dispatcher, scheduler_task

    if settings.auto_create_schema:
        await init_db()

    if settings.telegram_bot_token:
        bot = Bot(settings.telegram_bot_token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
        dispatcher = Dispatcher(storage=MemoryStorage())
        dispatcher.include_router(telegram_router)

        external_url = os.getenv("RENDER_EXTERNAL_URL") or settings.app_base_url
        if settings.is_production and external_url and settings.telegram_webhook_secret:
            await bot.set_webhook(
                f"{external_url.rstrip('/')}/telegram/webhook",
                secret_token=settings.telegram_webhook_secret,
                allowed_updates=dispatcher.resolve_used_update_types(),
                drop_pending_updates=False,
            )

    scheduler_task = asyncio.create_task(_scheduler_loop(), name="kalibr-report-scheduler")

    yield

    if scheduler_task:
        scheduler_task.cancel()
        with suppress(asyncio.CancelledError):
            await scheduler_task
        scheduler_task = None

    if bot:
        with suppress(Exception):
            await bot.session.close()


app = FastAPI(title=settings.app_name, version="0.2.1", lifespan=lifespan)
app.include_router(api_router)
app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")


@app.get("/health")
async def health():
    return {"status": "ok", "service": settings.app_name, "environment": settings.app_env}


@app.post("/telegram/webhook")
async def telegram_webhook(
    request: Request,
    x_telegram_bot_api_secret_token: str | None = Header(default=None),
):
    if not bot or not dispatcher:
        raise HTTPException(status_code=503, detail="Telegram bot is not configured")
    if settings.telegram_webhook_secret and x_telegram_bot_api_secret_token != settings.telegram_webhook_secret:
        raise HTTPException(status_code=403, detail="Invalid webhook secret")
    update = Update.model_validate(await request.json(), context={"bot": bot})
    await dispatcher.feed_update(bot, update)
    return {"ok": True}


@app.post("/internal/tick")
async def internal_tick(x_cron_secret: str | None = Header(default=None)):
    cron_secret = os.getenv("CRON_SECRET", "")
    if not cron_secret or x_cron_secret != cron_secret:
        raise HTTPException(status_code=403, detail="Invalid cron secret")
    await _run_tick()
    return {"ok": True}


@app.get("/", response_class=HTMLResponse)
async def root(request: Request):
    return templates.TemplateResponse(request=request, name="admin.html", context={"app_name": settings.app_name})


@app.get("/admin", response_class=HTMLResponse)
async def admin(request: Request):
    return templates.TemplateResponse(request=request, name="admin.html", context={"app_name": settings.app_name})
