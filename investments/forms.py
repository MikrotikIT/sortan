import re
from decimal import Decimal

from django import forms
from django.contrib.auth import password_validation
from django.core.exceptions import ValidationError

from .models import Film, Investment, User


class RegistrationForm(forms.Form):
    phone = forms.CharField(label="رقم الهاتف", max_length=20, widget=forms.TextInput(attrs={"placeholder": "+90 5xx xxx xx xx", "autocomplete": "tel", "dir": "ltr"}))
    invitation_code = forms.CharField(label="كود الدعوة", max_length=12, widget=forms.TextInput(attrs={"placeholder": "أدخل كود الدعوة", "dir": "ltr"}))
    password1 = forms.CharField(label="كلمة المرور", widget=forms.PasswordInput(attrs={"placeholder": "8 أحرف على الأقل", "autocomplete": "new-password"}))
    password2 = forms.CharField(label="تأكيد كلمة المرور", widget=forms.PasswordInput(attrs={"placeholder": "أعد كتابة كلمة المرور", "autocomplete": "new-password"}))

    def clean_phone(self):
        phone = self.cleaned_data["phone"].strip()
        if not re.fullmatch(r"\+?[0-9][0-9\s()-]{6,18}", phone):
            raise ValidationError("أدخل رقم هاتف صحيحاً.")
        normalized = re.sub(r"[\s()-]", "", phone)
        if User.objects.filter(phone=normalized).exists():
            raise ValidationError("رقم الهاتف مسجل بالفعل.")
        return normalized

    def clean_invitation_code(self):
        code = self.cleaned_data["invitation_code"].strip().upper()
        if not User.objects.filter(referral_code__iexact=code, is_active=True).exists():
            raise ValidationError("كود الدعوة غير صحيح.")
        return code

    def clean(self):
        cleaned = super().clean()
        password1 = cleaned.get("password1")
        password2 = cleaned.get("password2")
        if password1 and password2 and password1 != password2:
            self.add_error("password2", "كلمتا المرور غير متطابقتين.")
        if password1:
            try:
                password_validation.validate_password(password1)
            except ValidationError as exc:
                self.add_error("password1", exc)
        return cleaned

    def create_user(self):
        from django.db import transaction

        from .models import InvestmentVoucher, PlatformSettings

        with transaction.atomic():
            settings = PlatformSettings.objects.filter(pk=1).first()
            voucher_count = settings.default_voucher_count if settings else 3
            voucher_amount = settings.default_voucher_amount if settings else Decimal("100.00")
            referrer = User.objects.get(referral_code__iexact=self.cleaned_data["invitation_code"])
            user = User.objects.create_user(
                phone=self.cleaned_data["phone"],
                password=self.cleaned_data["password1"],
                referred_by=referrer,
            )
            InvestmentVoucher.objects.bulk_create(
                [InvestmentVoucher(user=user, amount=voucher_amount) for _ in range(voucher_count)]
            )
        return user


class LoginForm(forms.Form):
    phone = forms.CharField(label="رقم الهاتف", max_length=20, widget=forms.TextInput(attrs={"placeholder": "+90 5xx xxx xx xx", "autocomplete": "tel", "dir": "ltr"}))
    password = forms.CharField(label="كلمة المرور", widget=forms.PasswordInput(attrs={"placeholder": "أدخل كلمة المرور", "autocomplete": "current-password"}))

    def clean_phone(self):
        return re.sub(r"[\s()-]", "", self.cleaned_data["phone"].strip())


class InvestmentForm(forms.Form):
    film_url = forms.URLField(label="رابط الفيلم", max_length=500, widget=forms.URLInput(attrs={"placeholder": "https://...", "dir": "ltr"}))
    investment_code = forms.CharField(label="كود الاستثمار", max_length=48, widget=forms.TextInput(attrs={"placeholder": "أدخل كود الاستثمار", "dir": "ltr"}))
    funding_method = forms.ChoiceField(
        label="طريقة الاستثمار",
        choices=(("voucher", "قسيمة استثمار"), ("balance", "الرصيد")),
        widget=forms.RadioSelect,
    )
    amount = forms.DecimalField(
        label="مبلغ الاستثمار (USDT)",
        required=False,
        min_value=Decimal("0.01"),
        max_digits=20,
        decimal_places=6,
        widget=forms.NumberInput(attrs={"placeholder": "0.00", "step": "0.000001", "min": "0.01", "dir": "ltr"}),
    )

    def __init__(self, *args, user=None, has_vouchers=True, **kwargs):
        super().__init__(*args, **kwargs)
        self.user = user
        self.initial.setdefault("funding_method", "voucher" if has_vouchers else "balance")
        if not has_vouchers:
            self.fields["funding_method"].choices = (("balance", "الرصيد"),)

    def clean(self):
        cleaned = super().clean()
        url = (cleaned.get("film_url") or "").rstrip("/")
        code = (cleaned.get("investment_code") or "").strip()
        film = Film.objects.filter(investment_code=code).first()
        if film and film.external_url.rstrip("/") == url and film.active:
            if film.is_expired:
                self.add_error("film_url", "انتهت صلاحية رابط هذا الفيلم، ولا يمكن الاستثمار فيه.")
            else:
                cleaned["film"] = film
                if self.user and Investment.objects.filter(
                    user_id=self.user.pk,
                    film_url=film.external_url,
                ).exists():
                    self.add_error("film_url", "سبق لك الاستثمار في هذا الرابط، ويمكن الاستثمار فيه مرة واحدة فقط.")
                amount = cleaned.get("amount")
                if cleaned.get("funding_method") == "balance" and amount is not None and amount < film.minimum_investment_amount:
                    self.add_error(
                        "amount",
                        f"الحد الأدنى للاستثمار من الرصيد في هذا الفيلم هو {film.minimum_investment_amount:.2f} USDT.",
                    )
        else:
            raise ValidationError("الرابط أو كود الاستثمار غير صحيح، أو أن الفيلم لم يعد متاحاً.")
        if cleaned.get("funding_method") == "balance" and not cleaned.get("amount"):
            self.add_error("amount", "أدخل مبلغ الاستثمار من رصيدك.")
        return cleaned


class WithdrawalForm(forms.Form):
    amount = forms.DecimalField(
        label="مبلغ السحب (USDT)",
        min_value=Decimal("0.01"),
        max_digits=14,
        decimal_places=2,
        widget=forms.NumberInput(attrs={"placeholder": "0.00", "step": "0.01", "min": "0.01", "dir": "ltr"}),
    )
    wallet_address = forms.CharField(
        label="عنوان محفظة USDT TRC20",
        max_length=64,
        widget=forms.TextInput(attrs={"placeholder": "T...", "autocomplete": "off", "dir": "ltr"}),
    )

    def clean_wallet_address(self):
        address = self.cleaned_data["wallet_address"].strip()
        if not re.fullmatch(r"T[1-9A-HJ-NP-Za-km-z]{33}", address):
            raise ValidationError("أدخل عنوان TRON TRC20 صحيحاً.")
        return address
