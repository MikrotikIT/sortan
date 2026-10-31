import json

from django.http import JsonResponse
from django.views.decorators.http import require_POST

from .models import PushDevice


def _json_body(request):
    try:
        payload = json.loads(request.body or b"{}")
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


@require_POST
def register_push_device(request):
    if not request.user.is_authenticated or not request.user.is_active:
        return JsonResponse({"ok": False, "error": "authentication_required"}, status=401)

    payload = _json_body(request)
    if payload is None:
        return JsonResponse({"ok": False, "error": "invalid_json"}, status=400)

    token = payload.get("token")
    platform = payload.get("platform", PushDevice.Platform.ANDROID)
    if not isinstance(token, str) or not token.strip() or len(token) > 4096:
        return JsonResponse({"ok": False, "error": "invalid_token"}, status=400)
    if platform not in PushDevice.Platform.values:
        return JsonResponse({"ok": False, "error": "invalid_platform"}, status=400)

    token = token.strip()
    PushDevice.objects.update_or_create(
        token=token,
        defaults={"user": request.user, "platform": platform},
    )
    request.session["push_device_token"] = token
    return JsonResponse({"ok": True})


@require_POST
def unregister_push_device(request):
    if not request.user.is_authenticated or not request.user.is_active:
        return JsonResponse({"ok": False, "error": "authentication_required"}, status=401)

    payload = _json_body(request)
    if payload is None:
        return JsonResponse({"ok": False, "error": "invalid_json"}, status=400)

    token = payload.get("token")
    if not isinstance(token, str) or not token.strip():
        return JsonResponse({"ok": False, "error": "invalid_token"}, status=400)

    token = token.strip()
    PushDevice.objects.filter(user=request.user, token=token).delete()
    if request.session.get("push_device_token") == token:
        request.session.pop("push_device_token", None)
    return JsonResponse({"ok": True})
