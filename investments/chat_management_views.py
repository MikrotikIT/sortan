from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer
from django.contrib import messages
from django.db import transaction
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from .chat_forms import ChatGroupForm, GroupBanForm, GroupMemberForm, GroupMemberPermissionForm
from .management_views import staff_required
from .models import ChatGroup, ChatGroupBan, ChatMembership


def _broadcast_group_event(group_id, payload):
    layer = get_channel_layer()
    if layer:
        async_to_sync(layer.group_send)(
            f"chat_group_{group_id}",
            {"type": "chat.broadcast", "payload": payload},
        )


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
    groups = ChatGroup.objects.order_by("title", "pk")
    return render(request, "management/chat_groups.html", {"form": form, "groups": groups})


@staff_required
def chat_group_edit(request, pk):
    group = get_object_or_404(ChatGroup, pk=pk)
    was_active = group.is_active
    form = ChatGroupForm(request.POST or None, request.FILES or None, instance=group)
    if request.method == "POST" and form.is_valid():
        group = form.save()
        if was_active and not group.is_active:
            _broadcast_group_event(group.pk, {"type": "group_closed"})
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
