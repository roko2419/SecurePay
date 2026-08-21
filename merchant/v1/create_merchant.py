import secrets
from hashlib import sha512
from django.db import IntegrityError, transaction
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from payments.models.merchantinfo import MerchantInfo
from django_redis import get_redis_connection
from payments.auth import TOKEN_TTL_SECONDS


class CreateMerchant(APIView):
    def post(self, request):
        merchant_name = request.data.get("merchant_name")
        merchant_email = request.data.get("merchant_email")
        merchant_phone = request.data.get("merchant_phone")
        merchant_address = request.data.get("merchant_address")
        merchant_username = request.data.get("merchant_username")
        merchant_password = request.data.get("merchant_password")

        if not all([merchant_name, merchant_email, merchant_phone, merchant_address, merchant_username, merchant_password]):
            return Response({"error": "All fields are required."}, status=status.HTTP_400_BAD_REQUEST)

        for _ in range(10):
            try:
                with transaction.atomic():
                    merchant = MerchantInfo.objects.create(
                        merchant_name=merchant_name,
                        merchant_email=merchant_email,
                        merchant_phone=merchant_phone,
                        merchant_address=merchant_address,
                        username=merchant_username,
                        password=sha512(merchant_password.encode()).hexdigest(),
                        merchant_key=self.generate_key(),
                        merchant_salt=self.generate_salt(),
                    )
                return Response(
                    {
                        "message": "Merchant created successfully.",
                        "merchant_id": merchant.id,
                        "merchant_key": merchant.merchant_key,
                        "merchant_salt": merchant.merchant_salt,
                    },
                    status=status.HTTP_201_CREATED,
                )
            except IntegrityError:
                continue

        return Response({"error": "Could not generate unique merchant credentials. Please retry."}, status=500)

    def generate_key(self) -> str:
        return secrets.token_hex(4)

    def generate_salt(self) -> str:
        return secrets.token_hex(4)




class LoginMerchant(APIView):
    def post(self, request):
        merchant_email = request.data.get("merchant_email")
        password = request.data.get("password")

        if not all([merchant_email, password]):
            return Response(
                {"error": "merchant_email and password are required."},
                status=status.HTTP_400_BAD_REQUEST
            )

        try:
            merchant = MerchantInfo.objects.get(merchant_email=merchant_email)
        except MerchantInfo.DoesNotExist:
            return Response({"error": "Invalid credentials."}, status=status.HTTP_401_UNAUTHORIZED)

        hashed_password = sha512(password.encode()).hexdigest()
        if merchant.password != hashed_password:
            return Response({"error": "Invalid credentials."}, status=status.HTTP_401_UNAUTHORIZED)

        session_token = secrets.token_urlsafe(32)
        combined_token = f"{merchant.id}-{session_token}"

        redis_conn = get_redis_connection("default")
        redis_key = f"merchant_{merchant.id}:{session_token}"
        redis_value = str(merchant.id)
        redis_conn.setex(redis_key, TOKEN_TTL_SECONDS, redis_value)

        response = Response(
            {
                "message": "Login successful.",
                "merchant_id": merchant.id,
                "token": combined_token,
                "expires_in": TOKEN_TTL_SECONDS
            },
            status=status.HTTP_200_OK
        )
        response.set_cookie(
            key="token",
            value=combined_token,
            max_age=TOKEN_TTL_SECONDS,
            samesite="Lax",
            path="/",
        )
        return response