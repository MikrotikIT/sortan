from decimal import Decimal, InvalidOperation
from io import BytesIO
import warnings

from django import forms
from django.core.files.base import ContentFile
from django.core.exceptions import ValidationError
from django.utils import timezone
from django.utils.html import strip_tags
from PIL import Image, ImageOps, UnidentifiedImageError

from .models import Film, InvestmentVoucher, JoinApplication, PlatformSettings, SupportOption, User
from .demo_film_titles import DEMO_FILM_TITLES
from .notification_services import sanitize_notification_html
from .services import parse_withdrawal_referral_rules


class FilmForm(forms.ModelForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if not self.instance.pk:
            self.fields["link_expiry_duration"].initial = 1
            self.fields["link_expiry_unit"].initial = Film.ExpiryUnit.DAYS

    class Meta:
        model = Film
        fields = (
            "title", "description", "image_url", "external_url", "investment_code",
            "waiting_duration", "waiting_unit", "profit_percent", "minimum_investment_amount",
            "link_expiry_duration", "link_expiry_unit", "active",
        )
        widgets = {
            "description": forms.Textarea(attrs={"rows": 3}),
            "waiting_duration": forms.NumberInput(attrs={"min": "1", "step": "1"}),
            "profit_percent": forms.NumberInput(attrs={"min": "0", "max": "100", "step": "0.01"}),
            "minimum_investment_amount": forms.NumberInput(attrs={"min": "0.01", "step": "0.01"}),
            "link_expiry_duration": forms.NumberInput(attrs={"min": "1", "step": "1"}),
        }


class PlatformSettingsForm(forms.ModelForm):
    deposit_activity_amount_bands = forms.JSONField(widget=forms.HiddenInput())

    class Meta:
        model = PlatformSettings
        fields = (
            "minimum_deposit_amount",
            "default_voucher_count", "default_voucher_amount",
            "withdrawal_cooldown_enabled", "withdrawal_interval_days",
            "withdrawal_referral_gate_enabled", "withdrawal_referral_rules",
            "withdrawal_tax_enabled", "withdrawal_tax_percent",
            "withdrawal_minimum_enabled", "withdrawal_minimum_amount",
            "referral_deposit_percent", "referral_profit_percent",
            "online_counter_enabled", "online_counter_min", "online_counter_max",
            "online_counter_step_min", "online_counter_step_max",
            "deposit_activity_enabled", "deposit_activity_amount_bands",
            "deposit_activity_min_interval_seconds", "deposit_activity_max_interval_seconds",
        )

        widgets = {
            "minimum_deposit_amount": forms.NumberInput(attrs={"min": "0.000001", "step": "0.000001"}),
            "withdrawal_minimum_amount": forms.NumberInput(attrs={"min": "0.01", "step": "0.01"}),
            "withdrawal_referral_rules": forms.Textarea(attrs={"rows": 3, "dir": "ltr", "placeholder": "3:2, 5:4, 9:6"}),
            "online_counter_min": forms.NumberInput(attrs={"min": "0", "step": "1"}),
            "online_counter_max": forms.NumberInput(attrs={"min": "0", "step": "1"}),
            "online_counter_step_min": forms.NumberInput(attrs={"min": "1", "step": "1"}),
            "online_counter_step_max": forms.NumberInput(attrs={"min": "1", "step": "1"}),
            "deposit_activity_amount_bands": forms.HiddenInput(),
            "deposit_activity_min_interval_seconds": forms.NumberInput(attrs={"min": "1", "max": "300", "step": "1"}),
            "deposit_activity_max_interval_seconds": forms.NumberInput(attrs={"min": "1", "max": "300", "step": "1"}),
        }
        help_texts = {
            "minimum_deposit_amount": "أي تحويل أقل من هذا الحد يبقى في محفظة الاستقبال ويظهر في سجل الإيداعات كرصيد غير متوقع، من دون إضافته إلى رصيد العميل.",
            "withdrawal_referral_rules": "أضف مرحلة لكل عدد من السحوبات، وحدد إجمالي عدد المدعوين المطلوب عندها. مثال: بعد 3 سحوبات يلزم مدعوان، وبعد 5 يلزم 4 مدعوين إجمالاً.",
            "online_counter_enabled": "عداد تجريبي يتغير عشوائياً ضمن النطاق المحدد؛ لا يمثل عدد الزوار الحقيقي.",
            "online_counter_min": "يبدأ العداد من قيمة عشوائية بين هذا الحد والحد الأعلى.",
            "online_counter_step_min": "الحد الأدنى للزيادة أو النقصان العشوائي الذي يحدث كل 5 ثوانٍ.",
            "online_counter_step_max": "الحد الأعلى للزيادة أو النقصان العشوائي الذي يحدث كل 5 ثوانٍ.",
            "deposit_activity_enabled": "يعرض بلداناً ومبالغ عشوائية وأرقاماً مقنّعة، ولا يستخدم إيداعات أو بيانات عملاء حقيقية.",
            "deposit_activity_min_interval_seconds": "أقصر وقت انتظار عشوائي بين الإشعارات.",
            "deposit_activity_max_interval_seconds": "أطول وقت انتظار عشوائي بين الإشعارات.",
        }

    def clean(self):
        cleaned = super().clean()
        minimum = cleaned.get("online_counter_min")
        maximum = cleaned.get("online_counter_max")
        step_minimum = cleaned.get("online_counter_step_min")
        step_maximum = cleaned.get("online_counter_step_max")
        if minimum is not None and maximum is not None and minimum > maximum:
            self.add_error("online_counter_max", "يجب أن يكون الحد الأعلى أكبر من الحد الأدنى أو مساوياً له.")
        if step_minimum is not None and step_maximum is not None and step_minimum > step_maximum:
            self.add_error("online_counter_step_max", "يجب أن يكون أكبر مقدار للتغير أكبر من الأقل أو مساوياً له.")
        activity_min_interval = cleaned.get("deposit_activity_min_interval_seconds")
        activity_max_interval = cleaned.get("deposit_activity_max_interval_seconds")
        if activity_min_interval is not None and activity_max_interval is not None and activity_min_interval > activity_max_interval:
            self.add_error("deposit_activity_max_interval_seconds", "يجب أن تكون الفترة العليا أكبر من أو مساوية للفترة الدنيا.")
        return cleaned

    def clean_deposit_activity_amount_bands(self):
        bands = self.cleaned_data["deposit_activity_amount_bands"]
        if not isinstance(bands, list) or not 1 <= len(bands) <= 20:
            raise ValidationError("أضف شريحة واحدة على الأقل، وبحد أقصى 20 شريحة.")

        normalized_bands = []
        probability_total = Decimal("0")
        for index, band in enumerate(bands, start=1):
            if not isinstance(band, dict):
                raise ValidationError(f"بيانات الشريحة {index} غير صالحة.")
            try:
                minimum = Decimal(str(band["min_amount"]))
                maximum = Decimal(str(band["max_amount"]))
                probability = Decimal(str(band["probability"]))
            except (KeyError, InvalidOperation, TypeError, ValueError) as exc:
                raise ValidationError(f"أكمل حقول الشريحة {index} بأرقام صحيحة.") from exc
            if not all(value.is_finite() for value in (minimum, maximum, probability)):
                raise ValidationError(f"أرقام الشريحة {index} غير صالحة.")
            if minimum < 50 or maximum > 1000000 or minimum > maximum:
                raise ValidationError(f"نطاق الشريحة {index} يجب أن يكون بين 50 و1,000,000 USDT وبحد أدنى أقل من الأعلى.")
            if minimum % 50 or maximum % 50:
                raise ValidationError(f"مبالغ الشريحة {index} يجب أن تكون من مضاعفات 50 USDT.")
            if probability < 0 or probability > 100 or probability.as_tuple().exponent < -2:
                raise ValidationError(f"احتمالية الشريحة {index} يجب أن تكون بين 0 و100 وبحد أقصى منزلتين عشريتين.")
            probability_total += probability
            normalized_bands.append({
                "min_amount": format(minimum, "f"),
                "max_amount": format(maximum, "f"),
                "probability": format(probability, "f"),
            })

        if probability_total != Decimal("100"):
            raise ValidationError(f"مجموع احتمالات الشرائح يجب أن يساوي 100% (المجموع الحالي {probability_total}%).")
        return normalized_bands

    def clean_withdrawal_referral_rules(self):
        raw_rules = self.cleaned_data["withdrawal_referral_rules"]
        enabled = self.cleaned_data.get("withdrawal_referral_gate_enabled", False)
        if not raw_rules.strip():
            if enabled:
                raise ValidationError("أدخل مرحلة واحدة على الأقل أو عطّل شرط الدعوات.")
            return ""
        try:
            rules = parse_withdrawal_referral_rules(raw_rules)
        except (ValueError, TypeError):
            raise ValidationError("استخدم الصيغة عدد السحوبات:عدد المدعوين، مثال: 3:2, 5:4, 9:6.")
        if not rules:
            raise ValidationError("أدخل مرحلة واحدة على الأقل أو عطّل شرط الدعوات.")
        if len({withdrawal_count for withdrawal_count, _ in rules}) != len(rules):
            raise ValidationError("لا تكرر عدد السحوبات في أكثر من مرحلة.")
        required_counts = [referral_count for _, referral_count in rules]
        if required_counts != sorted(required_counts):
            raise ValidationError("يجب ألا يقل عدد المدعوين المطلوب في مرحلة لاحقة عن المرحلة السابقة.")
        return ", ".join(f"{withdrawal_count}:{referral_count}" for withdrawal_count, referral_count in rules)

class SupportOptionForm(forms.ModelForm):
    class Meta:
        model = SupportOption
        fields = ("title", "url", "image", "sort_order", "is_active", "show_on_auth_pages")
        widgets = {
            "url": forms.URLInput(attrs={"dir": "ltr", "placeholder": "https://wa.me/..."}),
            "image": forms.ClearableFileInput(attrs={"accept": "image/png,image/jpeg,image/webp,image/gif"}),
            "sort_order": forms.NumberInput(attrs={"min": "0", "step": "1"}),
        }
        help_texts = {
            "image": "PNG أو JPG أو WebP أو GIF، بحد أقصى 5 ميغابايت. ستُوحّد الصورة تلقائياً إلى مربع 256×256 لتظهر بالحجم نفسه.",
            "sort_order": "الأرقام الأصغر تظهر أولاً.",
            "show_on_auth_pages": "يظهر رابط الدعم أسفل نموذج تسجيل الدخول وإنشاء الحساب إذا كان الخيار مفعّلاً.",
        }

    def clean_image(self):
        image = self.cleaned_data.get("image")
        if not image or getattr(image, "_committed", False):
            return image
        if image.size > 5 * 1024 * 1024:
            raise ValidationError("حجم الصورة يجب ألا يتجاوز 5 ميغابايت.")

        try:
            image.seek(0)
            with warnings.catch_warnings():
                warnings.simplefilter("error", Image.DecompressionBombWarning)
                with Image.open(image) as source:
                    if source.format not in {"JPEG", "PNG", "WEBP", "GIF"}:
                        raise ValidationError("اختر صورة بصيغة PNG أو JPG أو WebP أو GIF.")
                    width, height = source.size
                    if width <= 0 or height <= 0 or width * height > 20_000_000:
                        raise ValidationError("أبعاد الصورة كبيرة جداً. اختر صورة أصغر.")

                    source = ImageOps.exif_transpose(source)
                    source.seek(0)
                    source.load()
                    has_alpha = "A" in source.getbands() or "transparency" in source.info
                    converted = source.convert("RGBA" if has_alpha else "RGB")
                    converted.thumbnail((224, 224), Image.Resampling.LANCZOS)

                    canvas_mode = "RGBA" if has_alpha else "RGB"
                    background = (255, 255, 255, 0) if has_alpha else (255, 255, 255)
                    canvas = Image.new(canvas_mode, (256, 256), background)
                    offset = ((256 - converted.width) // 2, (256 - converted.height) // 2)
                    if has_alpha:
                        canvas.alpha_composite(converted, dest=offset)
                    else:
                        canvas.paste(converted, offset)

                    output = BytesIO()
                    canvas.save(output, format="WEBP", quality=82, method=6)
        except ValidationError:
            raise
        except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError, Image.DecompressionBombWarning) as exc:
            raise ValidationError("تعذرت قراءة الصورة. اختر ملف صورة صالحاً بصيغة PNG أو JPG أو WebP أو GIF.") from exc

        return ContentFile(output.getvalue(), name="support-option.webp")

    def save(self, commit=True):
        previous_image = self.instance.image if self.instance.pk else None
        option = super().save(commit=False)
        if "image" in self.changed_data:
            option.image_url = ""
        if commit:
            option.save()
            self.save_m2m()
            if previous_image and "image" in self.changed_data and previous_image.name != option.image.name:
                previous_image.delete(save=False)
        return option


class VoucherIssueForm(forms.Form):
    phone = forms.CharField(label="رقم هاتف المستخدم", max_length=20, widget=forms.TextInput(attrs={"dir": "ltr", "placeholder": "رقم الهاتف"}))
    count = forms.IntegerField(label="عدد القسائم", min_value=1, max_value=500, initial=3)
    amount = forms.DecimalField(label="قيمة كل قسيمة (USDT)", min_value=Decimal("0.01"), max_digits=12, decimal_places=2, initial=Decimal("100.00"))

    def clean_phone(self):
        phone = self.cleaned_data["phone"].strip()
        user = User.objects.filter(phone=phone).first()
        if user is None:
            raise ValidationError("لم يتم العثور على مستخدم بهذا الرقم.")
        self.cleaned_data["target_user"] = user
        return phone


class VoucherAmountForm(forms.ModelForm):
    class Meta:
        model = InvestmentVoucher
        fields = ("amount",)
        widgets = {"amount": forms.NumberInput(attrs={"min": "0.01", "step": "0.01"})}


class NotificationForm(forms.Form):
    title = forms.CharField(
        label="عنوان الإشعار",
        max_length=180,
        widget=forms.TextInput(attrs={"placeholder": "مثال: تحديث مهم على حسابك"}),
    )
    body_html = forms.CharField(
        label="محتوى الإشعار",
        max_length=20000,
        help_text="يمكنك كتابة HTML أو استخدام أزرار التنسيق. تدعم الرسالة العناوين والفقرات والقوائم والروابط والجداول.",
        widget=forms.Textarea(
            attrs={
                "rows": 12,
                "dir": "ltr",
                "spellcheck": "false",
                "data-notification-html-source": "",
            }
        ),
    )

    def clean_body_html(self):
        body = sanitize_notification_html(self.cleaned_data["body_html"])
        if not strip_tags(body).strip():
            raise ValidationError("اكتب محتوى نصياً للإشعار.")
        return body


class JoinApplicationDecisionForm(forms.Form):
    decision = forms.ChoiceField(
        label="قرار المراجعة",
        choices=(
            ("", "اختر القرار"),
            ("approved", "الموافقة على الانضمام"),
            ("rejected", "رفض الطلب"),
            ("blocked", "حظر الحساب وتعطيل تسجيل الدخول"),
        ),
    )
    rejection_reason = forms.CharField(
        label="سبب الرفض أو الحظر",
        required=False,
        max_length=1200,
        widget=forms.Textarea(attrs={"rows": 4, "placeholder": "اكتب سبباً واضحاً للرجوع إليه في سجل المراجعة"}),
    )

    def clean(self):
        cleaned = super().clean()
        if cleaned.get("decision") in {"rejected", "blocked"} and not cleaned.get("rejection_reason", "").strip():
            self.add_error("rejection_reason", "اكتب سبب الرفض أو الحظر ليبقى موثقاً في سجل المراجعة.")
        return cleaned


class CustomerBlockForm(forms.Form):
    reason = forms.CharField(
        label="سبب الحظر",
        max_length=1200,
        widget=forms.Textarea(attrs={"rows": 4, "placeholder": "اكتب سبب حظر الحساب"}),
    )

    def clean_reason(self):
        reason = self.cleaned_data["reason"].strip()
        if not reason:
            raise ValidationError("اكتب سبباً لحظر الحساب.")
        return reason


class CustomerInfoForm(forms.Form):
    full_name = forms.CharField(label="الاسم والنسبة", max_length=160)
    father_name = forms.CharField(label="اسم الأب", max_length=120, required=False)
    mother_name = forms.CharField(label="اسم الأم", max_length=120, required=False)
    gender = forms.ChoiceField(
        label="الجنس",
        required=False,
        choices=(("", "غير محدد"), *JoinApplication.GENDER_CHOICES),
    )
    marital_status = forms.ChoiceField(
        label="الوضع العائلي",
        required=False,
        choices=(("", "غير محدد"), *JoinApplication.MARITAL_STATUS_CHOICES),
    )
    financial_status = forms.ChoiceField(
        label="الوضع المادي",
        required=False,
        choices=(("", "غير محدد"), *JoinApplication.FINANCIAL_STATUS_CHOICES),
    )


class CustomerPasswordForm(forms.Form):
    password1 = forms.CharField(
        label="كلمة المرور الجديدة",
        max_length=128,
        strip=False,
        widget=forms.PasswordInput(attrs={"autocomplete": "new-password"}),
        help_text="لا توجد شروط للأحرف الكبيرة أو الأرقام.",
    )
    password2 = forms.CharField(
        label="تأكيد كلمة المرور",
        max_length=128,
        strip=False,
        widget=forms.PasswordInput(attrs={"autocomplete": "new-password"}),
    )

    def clean(self):
        cleaned = super().clean()
        password = cleaned.get("password1")
        confirmation = cleaned.get("password2")
        if password and confirmation and password != confirmation:
            self.add_error("password2", "كلمتا المرور غير متطابقتين.")
        return cleaned


class ManualDepositForm(forms.Form):
    phone = forms.CharField(label="رقم هاتف المستخدم", max_length=20, widget=forms.TextInput(attrs={"dir": "ltr", "placeholder": "رقم الهاتف"}))
    amount = forms.DecimalField(label="المبلغ (USDT)", min_value=Decimal("0.01"), max_digits=20, decimal_places=6)
    reference = forms.CharField(label="مرجع التحويل", max_length=180, required=False)

    def clean_phone(self):
        phone = self.cleaned_data["phone"].strip()
        user = User.objects.filter(phone=phone).first()
        if user is None:
            raise ValidationError("لم يتم العثور على مستخدم بهذا الرقم.")
        self.cleaned_data["target_user"] = user
        return phone


class InternalBalanceCreditForm(forms.Form):
    phone = forms.CharField(
        label="رقم هاتف العميل",
        max_length=20,
        widget=forms.TextInput(attrs={"dir": "ltr", "placeholder": "رقم الهاتف"}),
    )
    amount = forms.DecimalField(
        label="المبلغ المضاف إلى الرصيد (USDT)",
        min_value=Decimal("0.000001"),
        max_digits=20,
        decimal_places=6,
    )
    internal_note = forms.CharField(
        label="ملاحظة للإدارة فقط (اختيارية)",
        max_length=240,
        required=False,
        widget=forms.TextInput(attrs={"placeholder": "سبب أو مرجع داخلي"}),
    )

    def clean_phone(self):
        phone = self.cleaned_data["phone"].strip()
        user = User.objects.filter(phone=phone, is_staff=False).first()
        if user is None:
            raise ValidationError("لم يتم العثور على عميل بهذا الرقم.")
        self.cleaned_data["target_user"] = user
        return phone


class DemoInvestmentBatchForm(forms.Form):
    user = forms.ModelChoiceField(
        label="حساب الاختبار",
        queryset=User.objects.none(),
        empty_label="اختر حساباً مصنفاً للاختبار",
    )
    count_per_day = forms.IntegerField(
        label="عدد الاستثمارات في اليوم",
        min_value=1,
        max_value=20,
        initial=3,
        widget=forms.NumberInput(attrs={"min": "1", "max": "20", "step": "1"}),
    )
    start_date = forms.DateField(
        label="من تاريخ",
        widget=forms.DateInput(attrs={"type": "date"}),
    )
    end_date = forms.DateField(
        label="إلى تاريخ",
        widget=forms.DateInput(attrs={"type": "date"}),
    )
    amount = forms.DecimalField(
        label="مبلغ كل استثمار (USDT)",
        min_value=Decimal("0.01"),
        max_digits=20,
        decimal_places=2,
        widget=forms.NumberInput(attrs={"min": "0.01", "step": "0.01"}),
    )
    profit_percent = forms.DecimalField(
        label="نسبة الربح (%)",
        min_value=Decimal("0"),
        max_value=Decimal("100"),
        max_digits=6,
        decimal_places=2,
        widget=forms.NumberInput(attrs={"min": "0", "max": "100", "step": "0.01"}),
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["user"].queryset = User.objects.filter(
            is_staff=False,
            is_active=True,
            is_fake_account=True,
            approval_status="approved",
        ).order_by("phone")
        self.fields["user"].help_text = "اختر حساباً نشطاً ومقبولاً ومعلماً كحساب اختبار."
        self.max_demo_title_count = len({title.casefold() for title in DEMO_FILM_TITLES})
        self.fields["count_per_day"].help_text = f"يُنشأ هذا العدد لكل يوم في الفترة المحددة، بحد أقصى {self.max_demo_title_count} سجل لكل دفعة."
        self.fields["profit_percent"].help_text = "تُحسب الأرباح التجريبية بهذا المعدل ولا تضاف إلى رصيد الحساب."
        today = timezone.localdate()
        self.fields["start_date"].initial = today
        self.fields["end_date"].initial = today
        self.fields["end_date"].widget.attrs["max"] = today.isoformat()
        self.fields["end_date"].help_text = "اختر اليوم أو تاريخاً سابقاً؛ لا يمكن أن يكون الاستثمار مكتملاً في المستقبل."

    def clean(self):
        cleaned = super().clean()
        start_date = cleaned.get("start_date")
        end_date = cleaned.get("end_date")
        count_per_day = cleaned.get("count_per_day")
        if start_date and end_date:
            if end_date < start_date:
                self.add_error("end_date", "يجب أن يكون تاريخ النهاية في اليوم نفسه أو بعد تاريخ البداية.")
            elif end_date > timezone.localdate():
                self.add_error("end_date", "لا يمكن أن يكون تاريخ الاستثمار المكتمل في المستقبل. اختر تاريخ اليوم أو تاريخاً سابقاً.")
            elif count_per_day and (end_date - start_date).days + 1 > self.max_demo_title_count // count_per_day:
                self.add_error(None, f"الدفعة الواحدة محدودة بـ {self.max_demo_title_count} استثمار تجريبي كحد أقصى.")
        return cleaned
