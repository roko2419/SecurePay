# Admin panel login/logout/session-check endpoints.
#
# --- How to create the FIRST admin user (there's no signup form) ----------
# Unlike merchant accounts (merchant.v1.create_merchant.CreateMerchant),
# there is NO API endpoint to create an admin user — that's deliberate,
# since anyone who could self-register as an admin would defeat the point of
# having an admin panel. Instead, admin accounts are plain Django
# auth.User rows, created with Django's own tooling:
#
#     python manage.py createsuperuser
#
# (superuser implies staff, so this is enough on its own). Or, to promote an
# EXISTING regular Django user to be able to log into this admin panel
# without making them a full superuser:
#
#     python manage.py shell -c "
#     from django.contrib.auth import get_user_model
#     u = get_user_model().objects.get(username='someone')
#     u.is_staff = True
#     u.save()
#     "
#
# Either way, that same username/password is what gets POSTed to
# AdminLoginView below — this reuses Django's built-in User model and
# password hashing (authenticate()) rather than inventing a separate admin
# credential store.
from django.contrib.auth import authenticate
from rest_framework.views import APIView, Response, status

from adminpanel.auth import (
    TOKEN_TTL_SECONDS,
    create_admin_session,
    destroy_admin_session,
    get_auth_token_from_request,
)
from adminpanel.permissions import AdminAPIView


class AdminLoginView(APIView):
    """Authenticate against Django's normal auth.User (staff/superuser only).

    No AdminAPIView base here since there's no session yet to check — this is
    the endpoint that creates one.
    """

    def post(self, request):
        username = request.data.get("username")
        password = request.data.get("password")

        if not all([username, password]):
            return Response(
                {"error": "username and password are required."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        user = authenticate(request, username=username, password=password)
        # Reject non-staff users even if the password is correct — this login
        # is for the admin panel only, not general site auth.
        if user is None or not (user.is_staff or user.is_superuser):
            return Response({"error": "Invalid credentials."}, status=status.HTTP_401_UNAUTHORIZED)

        token = create_admin_session(user)

        return Response(
            {
                "message": "Login successful.",
                "token": token,
                "expires_in": TOKEN_TTL_SECONDS,
                "admin": {
                    "id": user.id,
                    "username": user.username,
                    "email": user.email,
                },
            },
            status=status.HTTP_200_OK,
        )


class AdminLogoutView(AdminAPIView):
    """Drop the current session token so it can no longer be used."""

    def post(self, request):
        token = get_auth_token_from_request(request)
        destroy_admin_session(token)
        return Response({"message": "Logged out."}, status=status.HTTP_200_OK)


class AdminMeView(AdminAPIView):
    """Used by the frontend on load to check whether a stored token is still valid
    and to populate the logged-in admin's name in the UI."""

    def get(self, request):
        user = request.admin_user
        return Response(
            {
                "id": user.id,
                "username": user.username,
                "email": user.email,
            }
        )
