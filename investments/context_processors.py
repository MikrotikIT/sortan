def unread_notification_count(request):
    user = getattr(request, "user", None)
    if not user or not user.is_authenticated or user.is_staff:
        return {"unread_notification_count": 0}
    return {
        "unread_notification_count": user.notifications.filter(is_read=False).count(),
    }
