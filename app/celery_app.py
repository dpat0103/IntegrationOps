from celery import Celery
from app.core.config import get_settings

settings = get_settings()
celery_app = Celery(
    "integrationops", broker=settings.redis_url, backend=settings.redis_url
)
celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="UTC",
    worker_prefetch_multiplier=1,
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    broker_connection_retry_on_startup=True,
    result_expires=3600,
    task_publish_retry=False,
    beat_schedule={
        "dispatch-due-checks": {
            "task": "app.tasks.dispatch_due_checks",
            "schedule": settings.scheduler_tick_seconds,
        },
        "deliver-alerts-and-heartbeat": {
            "task": "app.tasks.operations_tick",
            "schedule": 5.0,
        },
        "retention": {"task": "app.tasks.maintenance", "schedule": 3600.0},
    },
)
celery_app.autodiscover_tasks(["app"])
