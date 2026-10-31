import firebase_admin
from firebase_admin import messaging
from django.conf import settings

from .models import PushDevice


def _firebase_app():
    try:
        return firebase_admin.get_app()
    except ValueError:
        return firebase_admin.initialize_app(options={"projectId": settings.FIREBASE_PROJECT_ID})


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
