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
    def post(self, request):
        username = request.data.get("username")
        password = request.data.get("password")

        if not all([username, password]):
            return Response(
                {"error": "username and password are required."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        user = authenticate(request, username=username, password=password)
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
    def post(self, request):
        token = get_auth_token_from_request(request)
        destroy_admin_session(token)
        return Response({"message": "Logged out."}, status=status.HTTP_200_OK)


class AdminMeView(AdminAPIView):
    def get(self, request):
        user = request.admin_user
        return Response(
            {
                "id": user.id,
                "username": user.username,
                "email": user.email,
            }
        )
