from django import forms
from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django.contrib.auth.forms import UserChangeForm as DjangoUserChangeForm

from .models import (
    Deposit,
    Film,
    Investment,
    InvestmentVoucher,
    PlatformSettings,
    ReferralCommission,
    User,
    WithdrawalRequest,
)


class UserChangeForm(DjangoUserChangeForm):
    class Meta(DjangoUserChangeForm.Meta):
        model = User
        fields = "__all__"


class UserCreationForm(forms.ModelForm):
    password1 = forms.CharField(label="كلمة المرور", widget=forms.PasswordInput)
    password2 = forms.CharField(label="تأكيد كلمة المرور", widget=forms.PasswordInput)

    class Meta:
        model = User
        fields = (
            "phone", "balance", "earnings_balance", "is_active", "is_staff",
            "is_superuser", "groups", "user_permissions",
        )

    def clean_password2(self):
        password1 = self.cleaned_data.get("password1")
        password2 = self.cleaned_data.get("password2")
        if password1 and password2 and password1 != password2:
            raise forms.ValidationError("كلمتا المرور غير متطابقتين.")
        return password2

    def save(self, commit=True):
        user = super().save(commit=False)
        user.set_password(self.cleaned_data["password1"])
        if commit:
            user.save()
            self.save_m2m()
        return user


@admin.register(User)
class UserAdmin(BaseUserAdmin):
    form = UserChangeForm
    add_form = UserCreationForm
    list_display = ("phone", "balance", "earnings_balance", "is_staff", "is_superuser", "is_active")
    list_filter = ("is_staff", "is_superuser", "is_active")
    search_fields = ("phone", "referral_code")
    ordering = ("phone",)
    filter_horizontal = ("groups", "user_permissions")
    readonly_fields = ("last_login", "date_joined")
    fieldsets = (
        (None, {"fields": ("phone", "password")}),
        ("الأرصدة", {"fields": ("balance", "earnings_balance", "total_earned")}),
        ("الدعوة", {"fields": ("referral_code", "referred_by")}),
        ("الصلاحيات", {"fields": ("is_active", "is_staff", "is_superuser", "groups", "user_permissions")}),
        ("التواريخ", {"fields": ("last_login", "date_joined")}),
    )
    add_fieldsets = (
        (None, {
            "classes": ("wide",),
            "fields": (
                "phone", "password1", "password2", "balance", "earnings_balance",
                "is_active", "is_staff", "is_superuser", "groups", "user_permissions",
            ),
        }),
    )


@admin.register(Film)
class FilmAdmin(admin.ModelAdmin):
    list_display = ("title", "investment_code", "waiting_duration", "waiting_unit", "link_expiry_duration", "link_expiry_unit", "link_expires_at", "profit_percent", "minimum_investment_amount", "active")
    list_filter = ("active", "waiting_unit", "link_expiry_unit")
    search_fields = ("title", "investment_code")

    def get_changeform_initial_data(self, request):
        initial = super().get_changeform_initial_data(request)
        initial.setdefault("link_expiry_duration", 1)
        initial.setdefault("link_expiry_unit", Film.ExpiryUnit.DAYS)
        return initial


@admin.register(InvestmentVoucher)
class InvestmentVoucherAdmin(admin.ModelAdmin):
    list_display = ("user", "amount", "status", "created_at", "used_at")
    list_filter = ("status",)
    search_fields = ("user__phone",)


@admin.register(Investment)
class InvestmentAdmin(admin.ModelAdmin):
    list_display = ("film_title", "user", "amount", "funding_source", "status", "matures_at", "realized_profit")
    list_filter = ("status", "funding_source")
    search_fields = ("film_title", "user__phone")
    readonly_fields = ("invested_at", "matures_at", "settled_at")


@admin.register(PlatformSettings)
class PlatformSettingsAdmin(admin.ModelAdmin):
    list_display = ("id", "default_voucher_count", "default_voucher_amount", "withdrawal_interval_days", "withdrawal_tax_percent")


@admin.register(Deposit)
class DepositAdmin(admin.ModelAdmin):
    list_display = ("user", "amount", "source", "status", "reference", "transaction_id", "created_at", "processed_at")
    list_filter = ("source", "status")
    search_fields = ("user__phone", "reference", "transaction_id")
    readonly_fields = ("transaction_id", "occurred_at", "created_at", "processed_at")


@admin.register(ReferralCommission)
class ReferralCommissionAdmin(admin.ModelAdmin):
    list_display = ("referrer", "referred_user", "source", "percent", "amount", "created_at")
    list_filter = ("source", "wallet")
    search_fields = ("referrer__phone", "referred_user__phone")
    readonly_fields = tuple(field.name for field in ReferralCommission._meta.fields)


@admin.register(WithdrawalRequest)
class WithdrawalRequestAdmin(admin.ModelAdmin):
    list_display = ("user", "amount", "tax_amount", "net_amount", "status", "requested_at", "processed_at")
    list_filter = ("status",)
    search_fields = ("user__phone", "wallet_address")
