from django.contrib.auth import get_user_model
from rest_framework.exceptions import AuthenticationFailed
from rest_framework.views import APIView

from adminpanel.auth import get_admin_user_id_from_token, get_auth_token_from_request

User = get_user_model()


class AdminAPIView(APIView):
    """Base view requiring a valid admin (staff/superuser) session token.

    Subclasses just implement get/post/patch/etc. as normal; `initial()` runs
    before the handler on every request and stashes the resolved user on
    `request.admin_user` for handlers to use (e.g. to stamp "resolved_by").
    Raising AuthenticationFailed here lets DRF turn it into a clean 401/403
    response automatically, without each view needing its own auth checks.
    """

    def initial(self, request, *args, **kwargs):
        super().initial(request, *args, **kwargs)
        token = get_auth_token_from_request(request)
        user_id = get_admin_user_id_from_token(token)
        if not user_id:
            raise AuthenticationFailed("Invalid or expired admin session")

        try:
            user = User.objects.get(id=user_id, is_active=True)
        except User.DoesNotExist:
            raise AuthenticationFailed("Invalid or expired admin session")

        # Belt-and-suspenders: even if a stale session token somehow points at
        # a user who lost staff/superuser status, don't let them in.
        if not (user.is_staff or user.is_superuser):
            raise AuthenticationFailed("Invalid or expired admin session")

        request.admin_user = user
