import os

from .settings import *

DEBUG = False
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
STATIC_URL = "/static/"

# The scheduled TRON sync needs a configured API key. Keep Beat idle until it exists.
if not os.environ.get("TRONGRID_API_KEY"):
    CELERY_BEAT_SCHEDULE = {}
