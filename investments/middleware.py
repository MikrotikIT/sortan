from django.contrib.auth import logout
from django.shortcuts import redirect
from django.urls import Resolver404, resolve


class ApprovalRequiredMiddleware:
    """Keep unapproved customers inside application review and notifications."""

    allowed_url_names = {
        "login",
        "register",
        "logout",
        "join_application",
        "account_review",
        "join_application_photo",
        "notifications",
        "notification_open",
        "notification_mark_read",
        "notifications_mark_all_read",
        "notification_unread_count",
    }

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        user = getattr(request, "user", None)
        if (
            user is not None
            and user.is_authenticated
            and not user.is_staff
            and user.approval_status == "blocked"
        ):
            logout(request)
            return redirect("login")

        if (
            user is not None
            and user.is_authenticated
            and not user.is_staff
            and user.approval_status != "approved"
            and not request.path_info.startswith(("/static/", "/media/"))
        ):
            try:
                url_name = resolve(request.path_info).url_name
            except Resolver404:
                url_name = None

            if url_name not in self.allowed_url_names:
                if user.approval_status == "rejected":
                    return redirect("join_application")
                if not hasattr(user, "join_application"):
                    return redirect("join_application")
                return redirect("account_review")

        return self.get_response(request)
