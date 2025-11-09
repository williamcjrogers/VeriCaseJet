from celery import Celery
from .config import settings
celery_app = Celery("vericase-docs", broker=settings.REDIS_URL, backend=settings.REDIS_URL)
