import warnings
from datetime import timedelta
from io import BytesIO
from pathlib import PurePath
from random import randint

from django import forms
from django.core.exceptions import ValidationError
from django.core.files.base import ContentFile
from django.utils import timezone
from PIL import Image, ImageOps, UnidentifiedImageError

from .models import ChatGroup, ChatMembership, User


def _normalize_image(upload, *, canvas_size=None, max_size=(1600, 1600), output_limit=2 * 1024 * 1024):
    if not upload or getattr(upload, "_committed", False):
        return upload
    if upload.size > 5 * 1024 * 1024:
        raise ValidationError("يجب ألا يتجاوز حجم الصورة 5 ميغابايت.")

    try:
        upload.seek(0)
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(upload) as source:
                if source.format not in {"JPEG", "PNG", "WEBP"}:
                    raise ValidationError("اختر صورة بصيغة JPG أو PNG أو WebP.")
                width, height = source.size
                if width <= 0 or height <= 0 or width * height > 20_000_000:
                    raise ValidationError("أبعاد الصورة كبيرة جداً. اختر صورة أصغر.")
                source = ImageOps.exif_transpose(source)
                source.load()
                has_alpha = "A" in source.getbands() or "transparency" in source.info
                image = source.convert("RGBA" if has_alpha else "RGB")
                bound = canvas_size or max_size
                image.thumbnail(bound, Image.Resampling.LANCZOS)

                if canvas_size:
                    mode = "RGBA" if has_alpha else "RGB"
                    fill = (255, 255, 255, 0) if has_alpha else (255, 255, 255)
                    canvas = Image.new(mode, canvas_size, fill)
                    offset = ((canvas.width - image.width) // 2, (canvas.height - image.height) // 2)
                    if has_alpha:
                        canvas.alpha_composite(image, dest=offset)
                    else:
                        canvas.paste(image, offset)
                    image = canvas

                payload = None
                for quality in (84, 76, 68, 60):
                    output = BytesIO()
                    image.save(output, format="WEBP", quality=quality, method=6)
                    if output.tell() <= output_limit:
                        payload = output.getvalue()
                        break
                if payload is None:
                    raise ValidationError("تعذر ضغط الصورة للحجم المطلوب. اختر صورة أخرى.")
    except ValidationError:
        raise
    except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError, Image.DecompressionBombWarning) as exc:
        raise ValidationError("تعذرت قراءة الصورة. اختر ملف صورة صالحاً بصيغة JPG أو PNG أو WebP.") from exc

    return ContentFile(payload, name="group-image.webp" if canvas_size else "chat-image.webp")


class ChatGroupForm(forms.ModelForm):
    class Meta:
        model = ChatGroup
        fields = (
            "title", "description", "image", "is_active", "is_public", "max_members",
            "demo_member_offset", "demo_member_growth_enabled", "demo_member_interval_min_seconds",
            "demo_member_interval_max_seconds", "demo_member_increment_min", "demo_member_increment_max",
            "message_mode", "allow_images", "allow_files", "allow_links", "reactions_enabled",
            "slow_mode_seconds", "blocked_terms",
        )
        widgets = {
            "description": forms.Textarea(attrs={"rows": 3, "maxlength": 1200}),
            "image": forms.ClearableFileInput(attrs={"accept": "image/jpeg,image/png,image/webp"}),
            "max_members": forms.NumberInput(attrs={"min": "0", "max": "10000", "step": "1"}),
            "demo_member_offset": forms.NumberInput(attrs={"min": "0", "max": "1000000", "step": "1"}),
            "demo_member_interval_min_seconds": forms.NumberInput(attrs={"min": "1", "max": "15", "step": "1"}),
            "demo_member_interval_max_seconds": forms.NumberInput(attrs={"min": "1", "max": "15", "step": "1"}),
            "demo_member_increment_min": forms.NumberInput(attrs={"min": "1", "max": "5", "step": "1"}),
            "demo_member_increment_max": forms.NumberInput(attrs={"min": "1", "max": "5", "step": "1"}),
            "slow_mode_seconds": forms.NumberInput(attrs={"min": "0", "max": "300", "step": "1"}),
            "blocked_terms": forms.Textarea(attrs={"rows": 4, "placeholder": "عبارة واحدة في كل سطر"}),
        }
        help_texts = {
            "image": "صورة JPG أو PNG أو WebP بحد أقصى 5MB. تُحوّل إلى WebP مربع 512×512 تلقائياً.",
            "max_members": "0 يعني بلا حد. الزيادة التجريبية إعداد منفصل وتظهر بوسم تجريبي.",
            "demo_member_offset": "يضاف إلى عدد الأعضاء الحقيقي. اتركه 0 لإخفاء العدد الإضافي التجريبي.",
            "demo_member_growth_enabled": "محاكاة للاختبار فقط؛ الزيادة ليست أعضاء حقيقيين.",
            "demo_member_interval_min_seconds": "اختيار عشوائي للفاصل بين الزيادات، من 1 إلى 15 ثانية.",
            "demo_member_increment_min": "اختيار عشوائي للزيادة في كل مرة، من 1 إلى 5.",
            "message_mode": "يمكن ضبط الأعضاء المسموح لهم من قائمة أعضاء المجموعة.",
            "slow_mode_seconds": "الفاصل الأدنى بين رسائل العضو. الحد الأقصى 300 ثانية.",
            "blocked_terms": "كل عبارة في سطر مستقل؛ الرسائل التي تحتويها تُرفض.",
        }

    def __init__(self, *args, **kwargs):
        self._previous_image = None
        self._previous_growth_enabled = False
        self._previous_next_growth_at = None
        if kwargs.get("instance") and kwargs["instance"].pk:
            self._previous_image = kwargs["instance"].image
            self._previous_growth_enabled = kwargs["instance"].demo_member_growth_enabled
            self._previous_next_growth_at = kwargs["instance"].demo_member_next_growth_at
        super().__init__(*args, **kwargs)

    def clean_image(self):
        image = self.cleaned_data.get("image")
        return _normalize_image(image, canvas_size=(512, 512), output_limit=500 * 1024)

    def clean_blocked_terms(self):
        value = self.cleaned_data.get("blocked_terms", "")
        terms = [line.strip() for line in value.splitlines() if line.strip()]
        if len(terms) > 100:
            raise ValidationError("أقصى عدد للعبارات المحظورة 100.")
        return "\n".join(terms)

    def clean(self):
        cleaned = super().clean()
        if cleaned.get("demo_member_interval_min_seconds") and cleaned.get("demo_member_interval_max_seconds"):
            if cleaned["demo_member_interval_min_seconds"] > cleaned["demo_member_interval_max_seconds"]:
                self.add_error("demo_member_interval_max_seconds", "يجب أن يكون الحد الأعلى مساوياً أو أكبر من الحد الأدنى.")
        if cleaned.get("demo_member_increment_min") and cleaned.get("demo_member_increment_max"):
            if cleaned["demo_member_increment_min"] > cleaned["demo_member_increment_max"]:
                self.add_error("demo_member_increment_max", "يجب أن تكون الزيادة القصوى مساوياً أو أكبر من الدنيا.")
        return cleaned

    def save(self, commit=True):
        group = super().save(commit=False)
        if group.demo_member_growth_enabled:
            if not self._previous_growth_enabled or not self._previous_next_growth_at:
                group.demo_member_next_growth_at = timezone.now() + timedelta(
                    seconds=randint(group.demo_member_interval_min_seconds, group.demo_member_interval_max_seconds)
                )
        else:
            group.demo_member_next_growth_at = None
        if commit:
            group.save()
            self.save_m2m()
        if commit and self._previous_image and "image" in self.changed_data:
            if self._previous_image.name and self._previous_image.name != group.image.name:
                self._previous_image.delete(save=False)
        return group


class ChatDemoGrowthForm(forms.Form):
    demo_growth_enabled = forms.BooleanField(label="تفعيل الزيادة التلقائية لهذه الرسالة", required=False)
    demo_growth_duration_hours = forms.ChoiceField(label="مدة الزيادة", choices=(("1", "ساعة"), ("6", "6 ساعات"), ("12", "12 ساعة"), ("24", "يوم"), ("48", "يومان"), ("72", "3 أيام")), initial="24")
    demo_growth_interval_min_seconds = forms.IntegerField(label="أقل فاصل (ثانية)", min_value=1, max_value=15, initial=5)
    demo_growth_interval_max_seconds = forms.IntegerField(label="أعلى فاصل (ثانية)", min_value=1, max_value=15, initial=15)
    demo_growth_step_min = forms.IntegerField(label="أقل زيادة في المرة", min_value=1, max_value=5, initial=1)
    demo_growth_step_max = forms.IntegerField(label="أعلى زيادة في المرة", min_value=1, max_value=5, initial=5)
    demo_like_percent = forms.IntegerField(label="👍 الإعجاب %", min_value=0, max_value=100, initial=30)
    demo_heart_percent = forms.IntegerField(label="❤️ القلب %", min_value=0, max_value=100, initial=40)
    demo_fire_percent = forms.IntegerField(label="🔥 النار %", min_value=0, max_value=100, initial=15)
    demo_clap_percent = forms.IntegerField(label="👏 التصفيق %", min_value=0, max_value=100, initial=10)
    demo_dislike_percent = forms.IntegerField(label="👎 عدم الإعجاب %", min_value=0, max_value=100, initial=5)

    def __init__(self, *args, group=None, **kwargs):
        self.group = group
        super().__init__(*args, **kwargs)

    def clean(self):
        cleaned = super().clean()
        if cleaned.get("demo_growth_interval_min_seconds") and cleaned.get("demo_growth_interval_max_seconds"):
            if cleaned["demo_growth_interval_min_seconds"] > cleaned["demo_growth_interval_max_seconds"]:
                self.add_error("demo_growth_interval_max_seconds", "يجب أن يكون الحد الأعلى مساوياً أو أكبر من الحد الأدنى.")
        if cleaned.get("demo_growth_step_min") and cleaned.get("demo_growth_step_max"):
            if cleaned["demo_growth_step_min"] > cleaned["demo_growth_step_max"]:
                self.add_error("demo_growth_step_max", "يجب أن تكون الزيادة القصوى مساوياً أو أكبر من الدنيا.")
        if cleaned.get("demo_growth_enabled"):
            if self.group and not self.group.reactions_enabled:
                self.add_error("demo_growth_enabled", "فعّل التفاعلات في إعدادات المجموعة أولاً.")
            percentage_fields = ("demo_like_percent", "demo_heart_percent", "demo_fire_percent", "demo_clap_percent", "demo_dislike_percent")
            percentages = [cleaned.get(field) for field in percentage_fields]
            if all(value is not None for value in percentages) and sum(percentages) != 100:
                raise ValidationError("يجب أن يساوي مجموع نسب التفاعلات 100%.")
        return cleaned


class ChatUploadForm(forms.Form):
    text = forms.CharField(max_length=2000, required=False, widget=forms.Textarea(attrs={"rows": 2, "maxlength": 2000}))
    image = forms.ImageField(required=False, widget=forms.ClearableFileInput(attrs={"accept": "image/jpeg,image/png,image/webp"}))
    attachment = forms.FileField(required=False)
    reply_to = forms.IntegerField(required=False, min_value=1, widget=forms.HiddenInput())

    ALLOWED_ATTACHMENTS = {"pdf", "txt", "csv", "doc", "docx", "xls", "xlsx", "ppt", "pptx", "zip"}

    def __init__(self, *args, group=None, **kwargs):
        self.group = group
        super().__init__(*args, **kwargs)

    def clean_text(self):
        return self.cleaned_data.get("text", "").strip()

    def clean_image(self):
        image = self.cleaned_data.get("image")
        return _normalize_image(image, max_size=(1600, 1600), output_limit=2 * 1024 * 1024)

    def clean_attachment(self):
        attachment = self.cleaned_data.get("attachment")
        if not attachment:
            return attachment
        if attachment.size > 20 * 1024 * 1024:
            raise ValidationError("يجب ألا يتجاوز حجم الملف 20 ميغابايت.")
        extension = PurePath(attachment.name).suffix.lstrip(".").lower()
        if extension not in self.ALLOWED_ATTACHMENTS:
            raise ValidationError("الأنواع المسموحة: PDF وملفات النص والجداول والعروض وZIP.")
        return attachment

    def clean(self):
        cleaned = super().clean()
        image = cleaned.get("image")
        attachment = cleaned.get("attachment")
        text = cleaned.get("text", "")
        if image and attachment:
            raise ValidationError("أرسل صورة أو ملفاً واحداً في الرسالة.")
        if not text and not image and not attachment:
            raise ValidationError("اكتب رسالة أو أرفق صورة أو ملفاً.")
        if self.group:
            if image and not self.group.allow_images:
                raise ValidationError("إرسال الصور متوقف في هذه المجموعة.")
            if attachment and not self.group.allow_files:
                raise ValidationError("إرفاق الملفات متوقف في هذه المجموعة.")
        return cleaned

class GroupMemberForm(forms.Form):
    phone = forms.CharField(label="رقم العميل", max_length=20, widget=forms.TextInput(attrs={"dir": "ltr"}))
    role = forms.ChoiceField(label="الدور", choices=ChatMembership.Role.choices)
    can_post = forms.BooleanField(label="السماح له بالنشر عند اختيار أعضاء محددين", required=False)

    def clean_phone(self):
        phone = self.cleaned_data["phone"].strip()
        user = User.objects.filter(phone=phone, is_staff=False, is_active=True, approval_status="approved").first()
        if user is None:
            raise ValidationError("لم يُعثر على عميل نشط ومقبول بهذا الرقم.")
        self.cleaned_data["target_user"] = user
        return phone


class GroupMemberPermissionForm(forms.Form):
    role = forms.ChoiceField(choices=ChatMembership.Role.choices)
    can_post = forms.BooleanField(required=False)


class GroupBanForm(forms.Form):
    phone = forms.CharField(label="رقم العميل", max_length=20, widget=forms.TextInput(attrs={"dir": "ltr"}))
    reason = forms.CharField(label="سبب الحظر", max_length=500, required=False, widget=forms.Textarea(attrs={"rows": 2}))

    def clean_phone(self):
        phone = self.cleaned_data["phone"].strip()
        user = User.objects.filter(phone=phone, is_staff=False).first()
        if user is None:
            raise ValidationError("لم يُعثر على عميل بهذا الرقم.")
        self.cleaned_data["target_user"] = user
        return phone
