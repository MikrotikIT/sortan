from decimal import Decimal

from django import forms
from django.core.exceptions import ValidationError
from django.utils.html import strip_tags

from .models import Film, InvestmentVoucher, PlatformSettings, SupportOption, User
from .notification_services import sanitize_notification_html
from .services import parse_deposit_activity_examples, parse_withdrawal_referral_rules


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
    class Meta:
        model = PlatformSettings
        fields = (
            "minimum_deposit_amount",
            "default_voucher_count", "default_voucher_amount",
            "withdrawal_cooldown_enabled", "withdrawal_interval_days",
            "withdrawal_referral_gate_enabled", "withdrawal_referral_rules",
            "withdrawal_tax_enabled", "withdrawal_tax_percent",
            "referral_deposit_percent", "referral_profit_percent",
            "online_counter_enabled", "online_counter_min", "online_counter_max",
            "online_counter_step_min", "online_counter_step_max",
            "deposit_activity_enabled", "deposit_activity_examples", "deposit_activity_interval_seconds",
        )

        widgets = {
            "minimum_deposit_amount": forms.NumberInput(attrs={"min": "0.000001", "step": "0.000001"}),
            "withdrawal_referral_rules": forms.Textarea(attrs={"rows": 3, "dir": "ltr", "placeholder": "3:2, 5:4, 9:6"}),
            "online_counter_min": forms.NumberInput(attrs={"min": "0", "step": "1"}),
            "online_counter_max": forms.NumberInput(attrs={"min": "0", "step": "1"}),
            "online_counter_step_min": forms.NumberInput(attrs={"min": "1", "step": "1"}),
            "online_counter_step_max": forms.NumberInput(attrs={"min": "1", "step": "1"}),
            "deposit_activity_examples": forms.Textarea(attrs={"rows": 5, "dir": "ltr"}),
            "deposit_activity_interval_seconds": forms.NumberInput(attrs={"min": "5", "max": "120", "step": "1"}),
        }
        help_texts = {
            "minimum_deposit_amount": "أي تحويل أقل من هذا الحد يبقى في محفظة الاستقبال ويظهر في سجل الإيداعات كرصيد غير متوقع، من دون إضافته إلى رصيد العميل.",
            "withdrawal_referral_rules": "أضف مرحلة لكل عدد من السحوبات، وحدد إجمالي عدد المدعوين المطلوب عندها. مثال: بعد 3 سحوبات يلزم مدعوان، وبعد 5 يلزم 4 مدعوين إجمالاً.",
            "online_counter_enabled": "عداد تجريبي يتغير عشوائياً ضمن النطاق المحدد؛ لا يمثل عدد الزوار الحقيقي.",
            "online_counter_min": "يبدأ العداد من قيمة عشوائية بين هذا الحد والحد الأعلى.",
            "online_counter_step_min": "الحد الأدنى للزيادة أو النقصان العشوائي الذي يحدث كل 5 ثوانٍ.",
            "online_counter_step_max": "الحد الأعلى للزيادة أو النقصان العشوائي الذي يحدث كل 5 ثوانٍ.",
            "deposit_activity_enabled": "يعرض أمثلة تجريبية واضحة، ولا يعرض إيداعات أو بيانات عملاء حقيقية.",
            "deposit_activity_examples": "سطر لكل مثال بالصيغة الدولة|رقم الهاتف|المبلغ. تُخفى آخر ثلاثة أرقام تلقائياً إذا لم يكن الرقم مقنّعاً.",
            "deposit_activity_interval_seconds": "الفاصل بين بداية ظهور إشعارين تجريبيين، من 5 إلى 120 ثانية.",
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
        return cleaned

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

    def clean_deposit_activity_examples(self):
        raw_examples = self.cleaned_data["deposit_activity_examples"]
        try:
            examples = parse_deposit_activity_examples(raw_examples)
        except ValueError as exc:
            raise ValidationError(str(exc)) from exc
        if self.cleaned_data.get("deposit_activity_enabled") and not examples:
            raise ValidationError("أضف مثالاً واحداً على الأقل أو أوقف إشعارات النشاط التجريبي.")
        return raw_examples.strip()


class SupportOptionForm(forms.ModelForm):
    class Meta:
        model = SupportOption
        fields = ("title", "url", "image", "sort_order", "is_active")
        widgets = {
            "url": forms.URLInput(attrs={"dir": "ltr", "placeholder": "https://wa.me/..."}),
            "image": forms.ClearableFileInput(attrs={"accept": "image/png,image/jpeg,image/webp,image/gif"}),
            "sort_order": forms.NumberInput(attrs={"min": "0", "step": "1"}),
        }
        help_texts = {
            "image": "اختر صورة من جهازك (PNG أو JPG أو WebP أو GIF)، بحد أقصى 5 ميغابايت. اتركها فارغة لاستخدام الأيقونة الافتراضية.",
            "sort_order": "الأرقام الأصغر تظهر أولاً.",
        }

    def clean_image(self):
        image = self.cleaned_data.get("image")
        if image and image.size > 5 * 1024 * 1024:
            raise ValidationError("حجم الصورة يجب ألا يتجاوز 5 ميغابايت.")
        return image

    def save(self, commit=True):
        option = super().save(commit=False)
        if "image" in self.changed_data:
            option.image_url = ""
        if commit:
            option.save()
            self.save_m2m()
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
