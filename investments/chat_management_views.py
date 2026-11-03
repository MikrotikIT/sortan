import logging
from datetime import timedelta
from decimal import Decimal, ROUND_HALF_UP
from random import choice, randint

from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer
from django.conf import settings
from django.contrib import messages
from django.db import transaction
from django.db.models import Count, Q
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_GET, require_POST

from .chat_forms import (
    ChatDemoAccountBatchForm,
    ChatDemoAccountEditForm,
    AIBotPoolForm,
    AIBotTemplateForm,
    AIChatSettingsForm,
    DemoWithdrawalReceiptForm,
    ChatUploadForm,
    ChatGroupForm,
    GroupBanForm,
    GroupMemberForm,
    GroupMemberPermissionForm,
)
from .chat_services import (
    ChatRuleError,
    create_demo_uploaded_message,
    mark_chat_group_read,
    serialize_chat_message,
    set_demo_message_reaction,
)
from .management_views import staff_required
from .models import (
    AIBotPool,
    AIBotTemplate,
    AIChatSettings,
    ChatDemoAccount,
    ChatGroup,
    ChatGroupBan,
    ChatMembership,
    ChatMessage,
    DemoWithdrawalReceipt,
    PlatformSettings,
)


logger = logging.getLogger(__name__)


def _broadcast_group_event(group_id, payload):
    layer = get_channel_layer()
    if layer:
        async_to_sync(layer.group_send)(
            f"chat_group_{group_id}",
            {"type": "chat.broadcast", "payload": payload},
        )


def _delete_chat_message_files(file_refs):
    for storage, name in file_refs:
        try:
            storage.delete(name)
        except Exception:
            logger.exception("Could not delete chat message file %s", name)


@staff_required
def chat_groups(request):
    form = ChatGroupForm(request.POST or None, request.FILES or None)
    if request.method == "POST" and form.is_valid():
        group = form.save(commit=False)
        group.created_by = request.user
        group.save()
        form.save_m2m()
        messages.success(request, "تم إنشاء مجموعة المحادثة.")
        return redirect("management_chat_group_edit", pk=group.pk)
    groups = ChatGroup.objects.order_by("display_order", "title", "pk")
    return render(request, "management/chat_groups.html", {"form": form, "groups": groups})


@staff_required
def chat_group_edit(request, pk):
    group = get_object_or_404(ChatGroup, pk=pk)
    was_active = group.is_active
    old_reactions_enabled = group.reactions_enabled
    old_allowed_reactions = tuple(group.allowed_reactions or ())
    form = ChatGroupForm(request.POST or None, request.FILES or None, instance=group)
    if request.method == "POST" and form.is_valid():
        group = form.save()
        if was_active and not group.is_active:
            _broadcast_group_event(group.pk, {"type": "group_closed"})
        if (
            old_reactions_enabled != group.reactions_enabled
            or old_allowed_reactions != tuple(group.allowed_reactions or ())
        ):
            _broadcast_group_event(group.pk, {"type": "reaction_settings_updated"})
        messages.success(request, "تم حفظ إعدادات المجموعة.")
        return redirect("management_chat_group_edit", pk=group.pk)
    members = group.memberships.select_related("user").order_by("user__phone")
    bans = group.bans.select_related("user", "banned_by").order_by("-created_at")
    return render(
        request,
        "management/chat_group_edit.html",
        {
            "group": group,
            "form": form,
            "member_form": GroupMemberForm(),
            "ban_form": GroupBanForm(),
            "members": members,
            "bans": bans,
            "actual_member_count": group.member_count,
            "display_member_count": group.member_count + group.demo_member_offset,
            "message_count": group.messages.count(),
        },
    )


@staff_required
@require_POST
def chat_group_delete(request, pk):
    group = get_object_or_404(ChatGroup, pk=pk)
    _broadcast_group_event(group.pk, {"type": "group_closed"})
    group.delete()
    messages.success(request, "تم حذف المجموعة ورسائلها ومرفقاتها.")
    return redirect("management_chat_groups")


@staff_required
@require_POST
def chat_group_messages_delete_all(request, pk):
    with transaction.atomic():
        group = get_object_or_404(ChatGroup.objects.select_for_update(), pk=pk)
        message_queryset = ChatMessage.objects.filter(group=group)
        message_count = message_queryset.count()
        file_refs = []
        attachment_fields = ("image", "attachment", "voice_message", "video")
        file_storages = {
            field_name: ChatMessage._meta.get_field(field_name).storage
            for field_name in attachment_fields
        }
        for names in message_queryset.values_list(*attachment_fields).iterator():
            for field_name, file_name in zip(attachment_fields, names):
                if file_name:
                    file_refs.append((file_storages[field_name], file_name))
        message_queryset.delete()
        transaction.on_commit(lambda refs=file_refs: _delete_chat_message_files(refs))

    _broadcast_group_event(group.pk, {"type": "group_messages_cleared"})
    messages.success(request, f"تم حذف {message_count} رسالة من مجموعة {group.title} مع المرفقات والتفاعلات.")
    return redirect("management_chat_group_edit", pk=group.pk)


@staff_required
@require_POST
def chat_group_member_add(request, pk):
    group = get_object_or_404(ChatGroup, pk=pk)
    form = GroupMemberForm(request.POST)
    if not form.is_valid():
        messages.error(request, "تعذر إضافة العضو. تحقق من رقم العميل وحالته.")
        return redirect("management_chat_group_edit", pk=group.pk)
    user = form.cleaned_data["target_user"]
    if ChatGroupBan.objects.filter(group=group, user=user).exists():
        messages.error(request, "ألغِ حظر العميل من قائمة المحظورين قبل إضافته.")
    elif not ChatMembership.objects.filter(group=group, user=user).exists() and group.max_members and group.member_count >= group.max_members:
        messages.error(request, "وصلت المجموعة إلى الحد الأقصى للأعضاء.")
    else:
        membership, created = ChatMembership.objects.get_or_create(
            group=group,
            user=user,
            defaults={
                "role": form.cleaned_data["role"],
                "can_post": form.cleaned_data["can_post"],
                "notifications_muted": group.notifications_muted_by_default,
            },
        )
        if not created:
            membership.role = form.cleaned_data["role"]
            membership.can_post = form.cleaned_data["can_post"]
            membership.save(update_fields=("role", "can_post"))
        messages.success(request, f"تمت إضافة {user.phone} إلى المجموعة.")
    return redirect("management_chat_group_edit", pk=group.pk)


@staff_required
@require_POST
def chat_group_member_update(request, pk, user_id):
    group = get_object_or_404(ChatGroup, pk=pk)
    membership = get_object_or_404(ChatMembership, group=group, user_id=user_id)
    form = GroupMemberPermissionForm(request.POST)
    if form.is_valid():
        membership.role = form.cleaned_data["role"]
        membership.can_post = form.cleaned_data["can_post"]
        membership.save(update_fields=("role", "can_post"))
        messages.success(request, f"تم تحديث صلاحيات {membership.user.phone}.")
    else:
        messages.error(request, "بيانات الصلاحية غير صالحة.")
    return redirect("management_chat_group_edit", pk=group.pk)


@staff_required
@require_POST
def chat_group_member_remove(request, pk, user_id):
    group = get_object_or_404(ChatGroup, pk=pk)
    membership = get_object_or_404(ChatMembership, group=group, user_id=user_id)
    phone = membership.user.phone
    target_user_id = membership.user_id
    membership.delete()
    _broadcast_group_event(group.pk, {"type": "member_removed", "target_user_id": target_user_id})
    messages.success(request, f"تمت إزالة {phone} من أعضاء المجموعة.")
    return redirect("management_chat_group_edit", pk=group.pk)


@staff_required
@require_POST
def chat_group_ban(request, pk):
    group = get_object_or_404(ChatGroup, pk=pk)
    form = GroupBanForm(request.POST)
    if not form.is_valid():
        messages.error(request, "تعذر حظر العميل. تحقق من رقم الهاتف.")
        return redirect("management_chat_group_edit", pk=group.pk)
    user = form.cleaned_data["target_user"]
    with transaction.atomic():
        ChatMembership.objects.filter(group=group, user=user).delete()
        ChatGroupBan.objects.update_or_create(
            group=group,
            user=user,
            defaults={"banned_by": request.user, "reason": form.cleaned_data["reason"]},
        )
    _broadcast_group_event(group.pk, {"type": "member_banned", "target_user_id": user.pk})
    messages.success(request, f"تم حظر {user.phone} من المجموعة.")
    return redirect("management_chat_group_edit", pk=group.pk)


@staff_required
@require_POST
def chat_group_unban(request, pk, ban_id):
    group = get_object_or_404(ChatGroup, pk=pk)
    ban = get_object_or_404(ChatGroupBan, pk=ban_id, group=group)
    phone = ban.user.phone
    ban.delete()
    messages.success(request, f"تم رفع الحظر عن {phone}. يمكنه الانضمام مجدداً إذا كانت المجموعة متاحة.")
    return redirect("management_chat_group_edit", pk=group.pk)


DEMO_CHAT_FIRST_NAMES = (
    "آدم", "أحمد", "أنس", "إياد", "باسل", "بهاء", "تامر", "تيم", "جواد", "حازم",
    "حسام", "حمزة", "خالد", "رامي", "رائد", "ريان", "زيد", "سامر", "سليم", "سيف",
    "شادي", "طارق", "عادل", "عاصم", "عباس", "عمر", "عمار", "فارس", "فراس", "قيس",
    "كريم", "ليث", "مازن", "محمد", "مروان", "مهند", "نادر", "نديم", "هادي", "هيثم",
    "وسام", "يزن", "ياسر", "يوسف", "سارة", "آية", "بتول", "جنى", "جود", "حلا",
    "دانا", "ديمة", "رنا", "ريم", "زينة", "سلمى", "شهد", "صفا", "عبير", "غنى",
    "فرح", "لارا", "لمى", "لين", "ليان", "مريم", "ميس", "نادين", "ندى", "نور",
    "هبة", "هند", "ياسمين",
)

DEMO_CHAT_NISBAS = (
    "الحموي", "الدمشقي", "الحلبي", "الحمصي", "الشامي", "العلي", "الحسن", "الناصر", "الخطيب", "بركات",
    "الرفاعي", "الزيني", "النجار", "الحاج", "الحداد", "الملحم", "الأسعد", "العباس", "الدياب", "السالم",
    "المرعي", "البدوي", "العمر", "اليوسف", "القاسم", "الموسى", "الدرويش", "الشقير", "العبيد", "الغانم",
    "الطويل", "القصير", "الزعبي", "الحريري", "الشقيف", "العثمان", "المراد", "الشرع", "الصالح", "الطاهر",
    "الخوري", "الكردي", "النعيم", "الحسين", "السيد", "القادري", "النجدي", "المالكي", "الأنصاري", "التميمي",
    "القرشي", "الجبوري", "الربيعي", "الشمري", "العنزي", "السلطان", "العابد", "المنصور", "النجار", "الصفدي",
)


def _new_demo_chat_name(reserved_names):
    for _ in range(5000):
        candidate = f"{choice(DEMO_CHAT_FIRST_NAMES)} {choice(DEMO_CHAT_NISBAS)}"
        if candidate.casefold() not in reserved_names:
            reserved_names.add(candidate.casefold())
            return candidate
    raise ValueError("نفدت الأسماء التجريبية الفريدة. عدّل اسماً موجوداً ثم أعد التوليد.")


def _reserved_demo_chat_names():
    names = {
        name.casefold() for name in ChatDemoAccount.objects.values_list("display_name", flat=True)
    }
    names.update(
        name.casefold()
        for name in ChatMessage.objects.exclude(demo_sender_name="")
        .values_list("demo_sender_name", flat=True)
        .distinct()
    )
    return names


def _demo_accounts_page_url(group_id):
    return f"{reverse('management_demo_chat_accounts')}?group={group_id}"


@staff_required
def demo_chat_accounts(request):
    groups = ChatGroup.objects.filter(is_active=True).order_by("title", "pk")
    requested_group_id = request.GET.get("group")
    try:
        selected_group = groups.filter(pk=int(requested_group_id)).first() if requested_group_id else None
    except (TypeError, ValueError):
        selected_group = None
    if selected_group is None:
        selected_group = groups.first()
    form = ChatDemoAccountBatchForm(
        initial={"group": selected_group.pk, "count": 5} if selected_group else {"count": 5}
    )
    accounts = (
        ChatDemoAccount.objects.filter(group=selected_group, is_ai=False)
        .select_related("group")
        .annotate(message_count=Count("messages", distinct=True))
        .order_by("display_name", "pk")
        if selected_group else ChatDemoAccount.objects.none()
    )
    ai_accounts = (
        ChatDemoAccount.objects.filter(group=selected_group, is_ai=True)
        .select_related("bot_pool__template", "ai_partner")
        .annotate(message_count=Count("messages", distinct=True))
        .order_by("bot_pool__template__name", "display_name", "pk")
        if selected_group else ChatDemoAccount.objects.none()
    )
    bot_pools = (
        AIBotPool.objects.filter(group=selected_group)
        .select_related("template")
        .annotate(
            active_count=Count(
                "accounts",
                filter=Q(accounts__is_ai=True, accounts__ai_state__in=("ACTIVE", "PAUSED")),
                distinct=True,
            )
        )
        .order_by("template__name", "pk")
        if selected_group else AIBotPool.objects.none()
    )
    ai_settings, _ = AIChatSettings.objects.get_or_create(pk=1)
    ai_settings_form = AIChatSettingsForm(instance=ai_settings)
    template_form = AIBotTemplateForm()
    pool_form = AIBotPoolForm(initial={"group": selected_group.pk} if selected_group else None)
    templates = AIBotTemplate.objects.order_by("name", "pk")
    template_rows = [
        (template, AIBotTemplateForm(instance=template, prefix=f"template-{template.pk}"))
        for template in templates
    ]
    try:
        popup_blocked = max(0, int(request.GET.get("popup_blocked", "0")))
    except (TypeError, ValueError):
        popup_blocked = 0
    return render(
        request,
        "management/demo_chat_accounts.html",
        {
            "groups": groups,
            "selected_group": selected_group,
            "form": form,
            "accounts": accounts,
            "ai_accounts": ai_accounts,
            "bot_pools": bot_pools,
            "ai_settings": ai_settings,
            "ai_settings_form": ai_settings_form,
            "templates": templates,
            "template_rows": template_rows,
            "template_form": template_form,
            "pool_form": pool_form,
            "openrouter_key_present": bool(ai_settings.encrypted_openrouter_api_key or getattr(settings, "OPENROUTER_API_KEY", "")),
            "popup_blocked": popup_blocked,
        },
    )


def _new_ai_bot_account(group, template, pool, reserved_names, *, display_name=None):
    if display_name is None:
        try:
            display_name = _new_demo_chat_name(reserved_names)
        except ValueError:
            letters = "ابتثجحخدذرزسشصضطظعغفقكلمنهوي"
            for _ in range(50):
                candidate = f"{template.name} {''.join(choice(letters) for _ in range(6))}"
                if candidate.casefold() not in reserved_names:
                    display_name = candidate
                    reserved_names.add(candidate.casefold())
                    break
            if display_name is None:
                raise ValueError("تعذر توليد اسم فريد لبوت الذكاء الاصطناعي.")
    return ChatDemoAccount.objects.create(
        group=group,
        display_name=display_name,
        is_ai=True,
        bot_pool=pool,
        ai_role=template.role,
        ai_model_id=template.model_id,
        ai_system_prompt=template.system_prompt,
        ai_wait_min_seconds=template.wait_min_seconds,
        ai_wait_max_seconds=template.wait_max_seconds,
        ai_lifetime_seconds=template.lifetime_minutes * 60,
        ai_next_action_at=timezone.now() + timedelta(
            seconds=randint(template.wait_min_seconds, template.wait_max_seconds)
        ),
    )


@staff_required
@require_POST
def ai_chat_settings_update(request):
    settings_row, _ = AIChatSettings.objects.get_or_create(pk=1)
    form = AIChatSettingsForm(request.POST, instance=settings_row)
    if form.is_valid():
        form.save()
        messages.success(request, "تم حفظ إعدادات تشغيل البوتات وربط OpenRouter.")
    else:
        error = next(iter(form.errors.values()), ["راجع الحقول المحددة."])[0]
        messages.error(request, f"تعذر حفظ الإعدادات: {error}")
    return redirect(_demo_accounts_page_url(request.POST.get("group", "")) if request.POST.get("group") else "management_demo_chat_accounts")


@staff_required
@require_POST
def ai_bot_template_create(request):
    form = AIBotTemplateForm(request.POST)
    if form.is_valid():
        form.save()
        messages.success(request, "تم حفظ قالب شخصية الذكاء الاصطناعي.")
    else:
        error = next(iter(form.errors.values()), ["راجع الحقول المحددة."])[0]
        messages.error(request, f"تعذر حفظ القالب: {error}")
    group_id = request.POST.get("group", "")
    return redirect(_demo_accounts_page_url(group_id) if group_id else "management_demo_chat_accounts")


@staff_required
@require_POST
def ai_bot_template_edit(request, pk):
    template = get_object_or_404(AIBotTemplate, pk=pk)
    form = AIBotTemplateForm(request.POST, instance=template)
    if form.is_valid():
        form.save()
        messages.success(request, f"تم تحديث قالب {template.name}. البوتات الموجودة تحتفظ بنسختها؛ التحديث يطبق على البدائل الجديدة.")
    else:
        error = next(iter(form.errors.values()), ["راجع الحقول المحددة."])[0]
        messages.error(request, f"تعذر تحديث القالب: {error}")
    group_id = request.POST.get("group", "")
    return redirect(_demo_accounts_page_url(group_id) if group_id else "management_demo_chat_accounts")


@staff_required
@require_POST
def ai_bot_pool_save(request):
    form = AIBotPoolForm(request.POST)
    if not form.is_valid():
        error = next(iter(form.errors.values()), ["راجع الحقول المحددة."])[0]
        messages.error(request, f"تعذر ضبط عدد البوتات: {error}")
        return redirect(_demo_accounts_page_url(request.POST.get("group", "")) if request.POST.get("group") else "management_demo_chat_accounts")
    template = form.cleaned_data["template"]
    requested_group = form.cleaned_data["group"]
    try:
        with transaction.atomic():
            group = ChatGroup.objects.select_for_update().get(pk=requested_group.pk, is_active=True)
            pool, _ = AIBotPool.objects.get_or_create(
                group=group,
                template=template,
                defaults={"created_by": request.user},
            )
            pool = AIBotPool.objects.select_for_update().get(pk=pool.pk)
            pool.desired_count = form.cleaned_data["desired_count"]
            pool.replacement_min_seconds = form.cleaned_data["replacement_min_seconds"]
            pool.replacement_max_seconds = form.cleaned_data["replacement_max_seconds"]
            pool.created_by = request.user
            pool.save()
            current_accounts = list(pool.accounts.filter(is_ai=True, ai_state__in=("ACTIVE", "PAUSED")).order_by("pk"))
            desired_count = pool.desired_count
            if len(current_accounts) > desired_count:
                for account in current_accounts[desired_count:]:
                    if account.ai_partner_id:
                        ChatDemoAccount.objects.filter(
                            pk=account.ai_partner_id, ai_partner_id=account.pk
                        ).update(ai_partner=None)
                    account.ai_state = "DEAD"
                    account.ai_dead_at = timezone.now()
                    account.ai_next_action_at = None
                    account.ai_last_active_at = None
                    account.ai_partner = None
                    account.save(update_fields=("ai_state", "ai_dead_at", "ai_next_action_at", "ai_last_active_at", "ai_partner"))
            elif len(current_accounts) < desired_count:
                reserved_names = _reserved_demo_chat_names()
                for _ in range(desired_count - len(current_accounts)):
                    _new_ai_bot_account(group, template, pool, reserved_names)
            pool.next_replacement_at = None
            pool.save(update_fields=("next_replacement_at", "updated_at"))
    except ChatGroup.DoesNotExist:
        messages.error(request, "مجموعة المحادثة لم تعد متاحة.")
        return redirect("management_demo_chat_accounts")
    messages.success(request, f"تم ضبط {desired_count} بوت من قالب {template.name} في {group.title}.")
    return redirect(_demo_accounts_page_url(group.pk))


@staff_required
@require_GET
def openrouter_model_list(request):
    import json
    from urllib.request import Request, urlopen

    endpoint = "https://openrouter.ai/api/v1/models?output_modalities=text"
    try:
        ai_settings = AIChatSettings.objects.filter(pk=1).first()
        api_key = (ai_settings.openrouter_api_key if ai_settings else "") or getattr(settings, "OPENROUTER_API_KEY", "")
        headers = {"Accept": "application/json", "User-Agent": "Kodi-TV/1.0"}
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"
        req = Request(endpoint, headers=headers)
        with urlopen(req, timeout=12) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except Exception:
        logger.exception("Could not fetch OpenRouter models")
        return JsonResponse({"ok": False, "models": [], "error": "تعذر تحميل قائمة موديلات OpenRouter."}, status=502)
    rows = payload.get("data", []) if isinstance(payload, dict) else []
    if not isinstance(rows, list):
        rows = []
    models = [
        {"id": row.get("id", ""), "name": row.get("name") or row.get("id", "")}
        for row in rows
        if isinstance(row, dict) and row.get("id")
    ]
    return JsonResponse({"ok": True, "models": models})


@staff_required
@require_POST
def demo_chat_accounts_create(request):
    form = ChatDemoAccountBatchForm(request.POST)
    if not form.is_valid():
        error = next(iter(form.errors.values()), ["راجع بيانات المجموعة وعدد الحسابات."])[0]
        return JsonResponse({"ok": False, "error": str(error)}, status=400)

    group = form.cleaned_data["group"]
    count = form.cleaned_data["count"]
    created_accounts = []
    try:
        with transaction.atomic():
            group = ChatGroup.objects.select_for_update().get(pk=group.pk, is_active=True)
            reserved_names = _reserved_demo_chat_names()
            for _ in range(count):
                created_accounts.append(
                    ChatDemoAccount.objects.create(
                        group=group,
                        display_name=_new_demo_chat_name(reserved_names),
                    )
                )
    except (ChatGroup.DoesNotExist, ValueError) as exc:
        error = str(exc) if isinstance(exc, ValueError) else "المجموعة غير متاحة الآن."
        return JsonResponse({"ok": False, "error": error}, status=400)

    messages.success(request, f"تم إنشاء {len(created_accounts)} حساب محادثة تجريبي للمجموعة {group.title}.")
    return JsonResponse(
        {
            "ok": True,
            "accounts": [
                {
                    "id": account.pk,
                    "name": account.display_name,
                    "url": reverse("management_demo_chat_account_room", args=(account.pk,)),
                }
                for account in created_accounts
            ],
            "page_url": _demo_accounts_page_url(group.pk),
        }
    )


@staff_required
@require_POST
def demo_chat_account_edit(request, pk):
    account = get_object_or_404(ChatDemoAccount.objects.select_related("group"), pk=pk)
    form = ChatDemoAccountEditForm(request.POST, instance=account)
    if form.is_valid():
        form.save()
        messages.success(request, "تم حفظ اسم الحساب التجريبي. الرسائل السابقة تحتفظ بالاسم الذي أُرسلت به.")
    else:
        errors = [str(error) for field_errors in form.errors.values() for error in field_errors]
        messages.error(request, errors[0] if errors else "تعذر حفظ اسم الحساب.")
    return redirect(_demo_accounts_page_url(account.group_id))


@staff_required
def demo_withdrawal_receipt_create(request, account_pk):
    account = get_object_or_404(ChatDemoAccount.objects.select_related("group"), pk=account_pk)
    form = DemoWithdrawalReceiptForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        platform_settings, _ = PlatformSettings.objects.get_or_create(pk=1)
        amount = form.cleaned_data["amount"]
        tax_percent = platform_settings.withdrawal_tax_percent if platform_settings.withdrawal_tax_enabled else Decimal("0.00")
        tax_amount = (amount * tax_percent / Decimal("100")).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        receipt = DemoWithdrawalReceipt.objects.create(
            account=account,
            amount=amount,
            tax_percent=tax_percent,
            tax_amount=tax_amount,
            net_amount=amount - tax_amount,
        )
        return redirect("management_demo_withdrawal_receipt", pk=receipt.pk)
    return render(
        request,
        "management/demo_withdrawal_receipt_form.html",
        {"account": account, "form": form},
    )


@staff_required
def demo_withdrawal_receipt(request, pk):
    receipt = get_object_or_404(
        DemoWithdrawalReceipt.objects.select_related("account", "account__group"),
        pk=pk,
    )
    return render(
        request,
        "investments/withdrawal_receipt.html",
        {"withdrawal": receipt, "is_demo_receipt": True},
    )


@staff_required
@require_POST
def demo_chat_account_regenerate_name(request, pk):
    try:
        with transaction.atomic():
            account = get_object_or_404(ChatDemoAccount.objects.select_related("group"), pk=pk)
            ChatGroup.objects.select_for_update().get(pk=account.group_id)
            account.display_name = _new_demo_chat_name(_reserved_demo_chat_names())
            account.save(update_fields=("display_name", "updated_at"))
        messages.success(request, f"تم توليد اسم جديد: {account.display_name}. الرسائل السابقة لم تتغير.")
    except ValueError as exc:
        messages.error(request, str(exc))
    return redirect(_demo_accounts_page_url(account.group_id))


@staff_required
@require_POST
def demo_chat_account_delete(request, pk):
    account = get_object_or_404(ChatDemoAccount.objects.select_related("group"), pk=pk)
    group_id = account.group_id
    display_name = account.display_name
    account.delete()
    messages.success(request, f"تم حذف هوية {display_name}. بقيت رسائلها السابقة محفوظة في المجموعة.")
    return redirect(_demo_accounts_page_url(group_id))


@staff_required
@require_POST
def demo_chat_accounts_delete_group(request, group_id):
    group = get_object_or_404(ChatGroup, pk=group_id)
    with transaction.atomic():
        AIBotPool.objects.filter(group=group).delete()
        deleted_count, _ = ChatDemoAccount.objects.filter(group=group).delete()
    messages.success(request, f"تم حذف {deleted_count} هوية من مجموعة {group.title}. بقيت الرسائل محفوظة ولن تُولّد بدائل.")
    return redirect(_demo_accounts_page_url(group.pk))


@staff_required
def demo_chat_account_room(request, pk):
    account = get_object_or_404(
        ChatDemoAccount.objects.select_related("group"),
        pk=pk,
        group__is_active=True,
    )
    recent_messages = list(
        ChatMessage.objects.filter(group=account.group)
        .select_related("group", "sender", "reply_to", "reply_to__sender")
        .prefetch_related("reactions", "demo_reaction_counts", "demo_account_reactions")
        .order_by("-created_at", "-pk")[:101]
    )
    has_older_messages = len(recent_messages) > 100
    recent_messages = list(reversed(recent_messages[:100]))
    messages_data = [
        serialize_chat_message(message, viewer_id=request.user.pk, demo_account_id=account.pk)
        for message in recent_messages
    ]
    if recent_messages:
        mark_chat_group_read(request.user, account.group, recent_messages[-1].pk)
    return render(
        request,
        "management/demo_chat_account_room.html",
        {
            "account": account,
            "group": account.group,
            "messages_data": messages_data,
            "has_older_messages": has_older_messages,
            "actual_member_count": account.group.member_count,
            "display_member_count": account.group.member_count + account.group.demo_member_offset,
            "ws_path": f"/ws/chat/groups/{account.group.pk}/",
            "history_url": reverse("management_demo_chat_account_history", args=(account.pk,)),
            "read_url": reverse("chat_group_mark_read", args=(account.group.pk,)),
            "send_url": reverse("management_demo_chat_account_send", args=(account.pk,)),
            "chat_live_stats_url": reverse("chat_live_stats"),
            "demo_growth_url_template": reverse("chat_message_demo_growth", args=(0,)),
            "demo_reaction_url_template": reverse("management_demo_chat_account_react", args=(account.pk, 0)),
        },
    )


@staff_required
@require_GET
def demo_chat_account_history(request, pk):
    account = get_object_or_404(
        ChatDemoAccount.objects.select_related("group"),
        pk=pk,
        group__is_active=True,
    )
    before_value = request.GET.get("before")
    if before_value:
        try:
            before_id = int(before_value)
        except (TypeError, ValueError):
            return JsonResponse({"ok": False, "error": "مؤشر الرسائل غير صالح."}, status=400)
        cursor = get_object_or_404(ChatMessage, pk=before_id, group=account.group)
        page_messages = list(
            ChatMessage.objects.filter(group=account.group)
            .filter(Q(created_at__lt=cursor.created_at) | Q(created_at=cursor.created_at, pk__lt=cursor.pk))
            .select_related("group", "sender", "reply_to", "reply_to__sender")
            .prefetch_related("reactions", "demo_reaction_counts", "demo_account_reactions")
            .order_by("-created_at", "-pk")[:51]
        )
        has_more = len(page_messages) > 50
        page_messages = list(reversed(page_messages[:50]))
        payload = {
            "ok": True,
            "messages": [
                serialize_chat_message(message, viewer_id=request.user.pk, demo_account_id=account.pk)
                for message in page_messages
            ],
            "has_more": has_more,
        }
    else:
        try:
            after_id = max(0, int(request.GET.get("after", "0")))
        except (TypeError, ValueError):
            return JsonResponse({"ok": False, "error": "مؤشر الرسائل غير صالح."}, status=400)
        page_messages = list(
            ChatMessage.objects.filter(group=account.group, pk__gt=after_id)
            .select_related("group", "sender", "reply_to", "reply_to__sender")
            .prefetch_related("reactions", "demo_reaction_counts", "demo_account_reactions")
            .order_by("pk")[:100]
        )
        payload = {
            "ok": True,
            "messages": [
                serialize_chat_message(message, viewer_id=request.user.pk, demo_account_id=account.pk)
                for message in page_messages
            ],
            "last_message_id": page_messages[-1].pk if page_messages else after_id,
        }
    response = JsonResponse(payload)
    response["Cache-Control"] = "private, no-store"
    return response


@staff_required
@require_POST
def demo_chat_account_react(request, account_pk, message_pk):
    account = get_object_or_404(
        ChatDemoAccount.objects.select_related("group"),
        pk=account_pk,
        group__is_active=True,
    )
    get_object_or_404(ChatMessage, pk=message_pk, group=account.group)
    try:
        message_data = set_demo_message_reaction(
            message_pk,
            account.pk,
            request.user.pk,
            request.POST.get("kind", ""),
        )
    except ChatRuleError as exc:
        return JsonResponse({"ok": False, "error": str(exc)}, status=400)
    reaction_event = {
        "type": "reaction_updated",
        "message_id": message_data["id"],
        "demo_account_id": account.pk,
        "actor_reaction": message_data["user_reaction"],
        "allowed_reactions": message_data["allowed_reactions"],
        "reactions_enabled": message_data["reactions_enabled"],
        "reactions": message_data["reactions"],
    }
    try:
        _broadcast_group_event(account.group_id, reaction_event)
    except Exception:
        logger.exception("Could not broadcast demo reaction for message %s", message_pk)
    return JsonResponse({"ok": True, "message": message_data})


@staff_required
@require_POST
def demo_chat_account_send(request, pk):
    account = get_object_or_404(
        ChatDemoAccount.objects.select_related("group"),
        pk=pk,
        group__is_active=True,
    )
    form = ChatUploadForm(request.POST, request.FILES, group=account.group)
    if not form.is_valid():
        errors = [str(error) for field_errors in form.errors.values() for error in field_errors]
        return JsonResponse({"ok": False, "error": errors[0] if errors else "راجع بيانات الرسالة."}, status=400)
    try:
        message_data = create_demo_uploaded_message(account.group_id, account.pk, request.user.pk, form)
    except ChatRuleError as exc:
        return JsonResponse({"ok": False, "error": str(exc)}, status=400)
    try:
        _broadcast_group_event(account.group_id, {"type": "message_created", "message": message_data})
    except Exception:
        logger.exception("Could not broadcast demo chat message %s", message_data["id"])
    return JsonResponse({"ok": True, "message": message_data})
