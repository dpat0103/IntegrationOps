from celery import Celery
from app.core.config import get_settings

settings = get_settings()
celery_app = Celery("integrationops", broker=settings.redis_url, backend=settings.redis_url)
celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="UTC",
    beat_schedule={
        "dispatch-due-checks": {
            "task": "app.tasks.dispatch_due_checks",
            "schedule": 5.0,
        }
    },
)
celery_app.autodiscover_tasks(["app"])
