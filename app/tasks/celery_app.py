from celery import Celery
from celery.schedules import crontab

from app.core.config import settings

celery_app = Celery(
    "kalibr_reports",
    broker=settings.redis_url,
    backend=settings.redis_url,
    include=["app.tasks.amocrm_sync", "app.tasks.schedules", "app.tasks.notifications"],
)
celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone=settings.app_timezone,
    enable_utc=True,
    task_acks_late=True,
    worker_prefetch_multiplier=1,
    task_reject_on_worker_lost=True,
    beat_schedule={
        "dispatch-report-schedules-every-minute": {
            "task": "app.tasks.schedules.dispatch_report_schedules",
            "schedule": crontab(minute="*"),
        },
        "process-amocrm-outbox": {
            "task": "app.tasks.amocrm_sync.process_outbox",
            "schedule": 20.0,
        },
        "check-critical-acknowledgements": {
            "task": "app.tasks.schedules.check_critical_acknowledgements",
            "schedule": 300.0,
        },
    },
)
