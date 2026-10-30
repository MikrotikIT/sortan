import os

from .settings import *

DEBUG = False
CHANNEL_LAYERS = {
    "default": {
        "BACKEND": "channels_redis.core.RedisChannelLayer",
        "CONFIG": {"hosts": [os.environ.get("CHANNEL_REDIS_URL", "redis://127.0.0.1:6379/1")]},
    }
}
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
STATIC_URL = "/static/"

# The scheduled TRON sync needs a configured API key. Keep the health heartbeat active.
if not os.environ.get("TRONGRID_API_KEY"):
    CELERY_BEAT_SCHEDULE = {
        name: schedule
        for name, schedule in CELERY_BEAT_SCHEDULE.items()
        if name != "sync-tron-deposits"
    }
