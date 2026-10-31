import hashlib
from threading import Lock

import firebase_admin
from firebase_admin import credentials, messaging
from django.conf import settings

from .firebase_credentials import service_account_path
from .models import PushDevice


_FIREBASE_APP_LOCK = Lock()


def _firebase_app():
    credential_path = service_account_path()
    if credential_path.is_file():
        signature = hashlib.sha256(credential_path.read_bytes()).hexdigest()[:16]
        credential = credentials.Certificate(str(credential_path))
    else:
        signature = "application-default"
        credential = None
    app_name = f"push-{settings.FIREBASE_PROJECT_ID}-{signature}"

    with _FIREBASE_APP_LOCK:
        try:
            return firebase_admin.get_app(app_name)
        except ValueError:
            try:
                return firebase_admin.initialize_app(
                    credential,
                    options={"projectId": settings.FIREBASE_PROJECT_ID},
                    name=app_name,
                )
            except ValueError:
                return firebase_admin.get_app(app_name)


def _send_to_devices(devices, *, title, body, data=None):
    device_rows = list(devices.values_list("pk", "token"))
    if not device_rows:
        return {"success_count": 0, "failure_count": 0}

    notification_data = {str(key): str(value) for key, value in (data or {}).items()}
    app = _firebase_app()
    success_count = 0
    failure_count = 0
    expired_device_ids = []

    for start in range(0, len(device_rows), 500):
        batch = device_rows[start : start + 500]
        message = messaging.MulticastMessage(
            tokens=[token for _, token in batch],
            notification=messaging.Notification(title=title, body=body),
            data=notification_data or None,
            android=messaging.AndroidConfig(
                priority="high",
                notification=messaging.AndroidNotification(channel_id="default"),
            ),
        )
        response = messaging.send_each_for_multicast(message, app=app)
        success_count += response.success_count
        failure_count += response.failure_count

        for (device_id, _), item_response in zip(batch, response.responses):
            if isinstance(item_response.exception, messaging.UnregisteredError):
                expired_device_ids.append(device_id)

    if expired_device_ids:
        PushDevice.objects.filter(pk__in=expired_device_ids).delete()

    return {"success_count": success_count, "failure_count": failure_count}


def send_push_to_user(user, *, title, body, data=None):
    return _send_to_devices(
        PushDevice.objects.filter(user=user),
        title=title,
        body=body,
        data=data,
    )


def send_push_to_all(*, title, body, data=None):
    return _send_to_devices(
        PushDevice.objects.all(),
        title=title,
        body=body,
        data=data,
    )
