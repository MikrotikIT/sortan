import json
import os
import tempfile
from pathlib import Path

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured, ValidationError


MAX_SERVICE_ACCOUNT_BYTES = 64 * 1024


def service_account_path():
    path = Path(settings.FIREBASE_SERVICE_ACCOUNT_FILE)
    resolved_path = path.resolve()
    for public_root in (settings.MEDIA_ROOT, settings.STATIC_ROOT):
        resolved_root = Path(public_root).resolve()
        try:
            resolved_path.relative_to(resolved_root)
        except ValueError:
            continue
        raise ImproperlyConfigured("Firebase service-account credentials must be stored outside public media and static roots.")
    return path


def service_account_status():
    path = service_account_path()
    if not path.is_file():
        return {"configured": False, "project_id": ""}

    try:
        with path.open("r", encoding="utf-8") as service_account_file:
            payload = json.load(service_account_file)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return {"configured": False, "project_id": "", "invalid": True}

    configured = (
        isinstance(payload, dict)
        and payload.get("type") == "service_account"
        and payload.get("project_id") == settings.FIREBASE_PROJECT_ID
        and isinstance(payload.get("client_email"), str)
        and isinstance(payload.get("private_key"), str)
    )
    return {
        "configured": configured,
        "project_id": payload.get("project_id", "") if isinstance(payload, dict) else "",
        "invalid": not configured,
    }


def save_service_account_upload(uploaded_file):
    if not uploaded_file or uploaded_file.size > MAX_SERVICE_ACCOUNT_BYTES:
        raise ValidationError("حجم ملف Firebase غير صالح؛ الحد الأعلى 64 كيلوبايت.")
    if not uploaded_file.name.lower().endswith(".json"):
        raise ValidationError("ارفع ملف JSON الخاص بحساب الخدمة.")

    try:
        raw_content = uploaded_file.read(MAX_SERVICE_ACCOUNT_BYTES + 1)
        if len(raw_content) > MAX_SERVICE_ACCOUNT_BYTES:
            raise ValidationError("حجم ملف Firebase يتجاوز الحد المسموح.")
        payload = json.loads(raw_content.decode("utf-8-sig"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise ValidationError("الملف ليس JSON صالحًا.") from None

    if not isinstance(payload, dict) or payload.get("type") != "service_account":
        raise ValidationError("الملف ليس مفتاح Service Account صالحًا.")
    if payload.get("project_id") != settings.FIREBASE_PROJECT_ID:
        raise ValidationError("معرّف المشروع في الملف لا يطابق إعداد Firebase للموقع.")
    if not payload.get("client_email") or not payload.get("private_key"):
        raise ValidationError("ملف Service Account ينقصه البريد أو المفتاح الخاص.")

    try:
        from firebase_admin import credentials

        credentials.Certificate(payload)
    except ImportError:
        raise ValidationError("مكتبة Firebase Admin غير مثبتة على الخادم.") from None
    except Exception:
        raise ValidationError("تعذر التحقق من المفتاح الخاص داخل الملف.") from None

    destination = service_account_path()
    destination.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    os.chmod(destination.parent, 0o700)
    temporary_path = None
    try:
        file_descriptor, temporary_path = tempfile.mkstemp(
            prefix=".firebase-service-account-",
            suffix=".tmp",
            dir=destination.parent,
        )
        if hasattr(os, "fchmod"):
            os.fchmod(file_descriptor, 0o600)
        with os.fdopen(file_descriptor, "w", encoding="utf-8") as temporary_file:
            json.dump(payload, temporary_file, separators=(",", ":"))
            temporary_file.flush()
            os.fsync(temporary_file.fileno())
        os.replace(temporary_path, destination)
        temporary_path = None
        os.chmod(destination, 0o600)
    except OSError:
        raise ValidationError("تعذر حفظ الملف في مساحة التخزين الخاصة بالموقع.") from None
    finally:
        if temporary_path and os.path.exists(temporary_path):
            os.unlink(temporary_path)

    return {"project_id": payload["project_id"]}
