import json
import logging
from decimal import Decimal
from urllib.parse import urlencode

import requests
from django.conf import settings
from django.shortcuts import redirect
from django.views.decorators.csrf import csrf_exempt
from django.utils.decorators import method_decorator

from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status

from payments.api.v1.phonepe_auth import get_phonepe_oauth_token
from payments.models.orderinfo import OrderInfo
from payments.models.customerinfo import CustomerInfo
from payments.models.merchantinfo import MerchantInfo

logger = logging.getLogger(__name__)


def _map_phonepe_status_to_order_status(status_str: str) -> str:
    s = (status_str or "").upper()
    if s in ("SUCCESS", "SUCCESSFUL", "COMPLETED", "PAID"):
        return "paid"
    if s in ("FAILED", "FAILURE", "DECLINED", "ERROR"):
        return "payment_failed"
    return "pending"

def _extract_verify_fields(v: dict):
    # Common PhonePe V2 shapes:
    # { "success": true, "code":"PAYMENT_SUCCESS", "data": {...} }
    # or direct { "state": "...", "amount": ... }
    data = v.get("data", {}) if isinstance(v.get("data"), dict) else {}

    payment_status = (
        data.get("state")
        or data.get("status")
        or v.get("state")
        or v.get("status")
        or v.get("paymentStatus")
        or "PENDING"
    )

    amount_paise = (
        data.get("amount")
        or data.get("paymentDetails", {}).get("amount")
        or v.get("amount")
        or 0
    )

    payment_id = (
        data.get("transactionId")
        or data.get("paymentId")
        or data.get("txnId")
        or v.get("transactionId")
        or v.get("paymentId")
        or v.get("txnId")
        or ""
    )

    # Normalize status from code if present
    code = (v.get("code") or "").upper()
    if code in ("PAYMENT_SUCCESS", "SUCCESS"):
        payment_status = "SUCCESS"
    elif code in ("PAYMENT_ERROR", "PAYMENT_DECLINED", "FAILURE", "FAILED"):
        payment_status = "FAILED"

    return str(payment_status).upper(), int(amount_paise or 0), payment_id

def _verify_phonepe_order(order_id: str) -> dict:
    token = get_phonepe_oauth_token()
    verify_url = settings.PHONEPE_STATUS_URL.format(orderId=order_id)

    headers = {
        "Content-Type": "application/json",
        "Authorization": f"O-Bearer {token}",
    }

    resp = requests.get(verify_url, headers=headers, timeout=20)

    # Always capture raw response for debugging
    raw_text = resp.text or ""
    content_type = resp.headers.get("content-type", "")

    if not resp.ok:
        raise Exception(
            f"PhonePe verify failed: HTTP {resp.status_code}, "
            f"content-type={content_type}, body={raw_text[:500]}"
        )

    # If body is not JSON, return structured fallback
    if "application/json" not in content_type.lower():
        return {
            "status": "PENDING",
            "_non_json": True,
            "_http_status": resp.status_code,
            "_content_type": content_type,
            "_raw_body": raw_text[:1000],
        }

    try:
        return resp.json()
    except Exception:
        return {
            "status": "PENDING",
            "_json_parse_error": True,
            "_http_status": resp.status_code,
            "_content_type": content_type,
            "_raw_body": raw_text[:1000],
        }


class PhonePeInitiateView(APIView):
    def post(self, request):
        data = request.data or {}

        merchant_order_id = data.get("merchantOrderId") or data.get("merchantTransactionId")
        amount_paise = int(data.get("amount") or 0)
        redirect_url = data.get("redirectUrl")
        mobile = data.get("mobileNumber")
        customer_name = (data.get("customerName") or "").strip()
        customer_email = (data.get("customerEmail") or "").strip()

        if not merchant_order_id:
            return Response({"ok": False, "error": "merchantOrderId is required"}, status=status.HTTP_400_BAD_REQUEST)
        if amount_paise < 100:
            return Response({"ok": False, "error": "amount must be at least 100 paise"}, status=status.HTTP_400_BAD_REQUEST)
        if not redirect_url:
            return Response({"ok": False, "error": "redirectUrl is required"}, status=status.HTTP_400_BAD_REQUEST)
        if len(merchant_order_id) > 63:
            return Response({"ok": False, "error": "merchantOrderId must be <= 63 characters"}, status=status.HTTP_400_BAD_REQUEST)

        # Merchant resolution (adjust if your auth flow is different)
        merchant = None
        if request.user and request.user.is_authenticated:
            merchant = MerchantInfo.objects.filter(user=request.user).first()
        if merchant is None:
            merchant = MerchantInfo.objects.first()
        if merchant is None:
            return Response({"ok": False, "error": "No merchant found"}, status=status.HTTP_400_BAD_REQUEST)

        # Customer resolution
        if mobile:
            customer, _ = CustomerInfo.objects.get_or_create(
                customer_phone=mobile,
                defaults={
                    "customer_name": customer_name or "Guest",
                    "customer_email": customer_email,
                },
            )
        else:
            # If your CustomerInfo requires phone non-null, generate temp
            customer = CustomerInfo.objects.create(
                customer_phone=f"TEMP-{merchant_order_id}"[:50],
                customer_name=customer_name or "Guest",
                customer_email=customer_email,
            )

        amount_rupees = Decimal(amount_paise) / Decimal("100")

        # Create or update local order
        order = OrderInfo.objects.filter(merchant_order_id=merchant_order_id).first()
        if order is None:
            order = OrderInfo.objects.create(
                merchant=merchant,
                merchant_order_id=merchant_order_id,
                order_amount=amount_rupees,
                order_currency="INR",
                order_status="pending",
                customer_info=customer,
                payment_provider="phonepe",
            )
        else:
            order.merchant = order.merchant or merchant
            order.customer_info = order.customer_info or customer
            order.order_amount = amount_rupees
            order.order_currency = "INR"
            order.order_status = "pending"
            order.payment_provider = "phonepe"
            order.save()

        # Get PhonePe token
        try:
            token = get_phonepe_oauth_token()
        except Exception as e:
            logger.exception("PhonePe OAuth token fetch failed")
            return Response(
                {"ok": False, "error": "PhonePe authentication failed", "details": str(e)},
                status=status.HTTP_502_BAD_GATEWAY,
            )

        # PhonePe payload
        payload = {
            "merchantOrderId": merchant_order_id,
            "amount": amount_paise,
            "paymentFlow": {
                "type": "PG_CHECKOUT",
                "merchantUrls": {"redirectUrl": redirect_url},
            },
            "expireAfter": 1200,
        }
        if mobile:
            payload["prefillUserLoginDetails"] = {"phoneNumber": mobile}

        try:
            headers = {
                "Content-Type": "application/json",
                "Authorization": f"O-Bearer {token}",
            }
            resp = requests.post(settings.PHONEPE_INIT_URL, json=payload, headers=headers, timeout=15)
            logger.info("PhonePe initiate response status=%s body=%s", resp.status_code, resp.text)
            resp.raise_for_status()
            resp_json = resp.json()
        except requests.RequestException as e:
            logger.exception("PhonePe initiate call failed")
            order.phonepe_raw_response = {"error": str(e), "response": getattr(e.response, "text", None)}
            order.payment_provider = "phonepe"
            order.order_status = "payment_failed"
            order.save(update_fields=["phonepe_raw_response", "payment_provider", "order_status"])
            return Response(
                {"ok": False, "error": "PhonePe payment initiation failed", "details": str(e)},
                status=status.HTTP_502_BAD_GATEWAY,
            )

        # Save PhonePe order details
        phonepe_order_id = resp_json.get("orderId")
        order.phonepe_order_id = phonepe_order_id or order.phonepe_order_id
        order.pa_order_id = phonepe_order_id or order.pa_order_id
        order.phonepe_raw_response = resp_json
        order.payment_provider = "phonepe"
        order.order_status = "pending"
        order.save(update_fields=[
            "phonepe_order_id", "pa_order_id", "phonepe_raw_response", "payment_provider", "order_status"
        ])

        return Response(resp_json, status=resp.status_code)


class PhonePeReturnView(APIView):
    authentication_classes = []
    permission_classes = []

    def get(self, request):
        merchant_order_id = request.GET.get("merchantOrderId") or request.GET.get("merchantTransactionId") or ""
        phonepe_order_id = request.GET.get("orderId") or ""

        order = None
        if merchant_order_id:
            order = OrderInfo.objects.filter(merchant_order_id=merchant_order_id).first()
        if not order and phonepe_order_id:
            order = OrderInfo.objects.filter(phonepe_order_id=phonepe_order_id).first()

        payment_status = "PENDING"
        amount_paise = 0
        payment_id = ""
        verify_resp = {}

        try:
            verify_id = merchant_order_id or (order.merchant_order_id if order else "")
            if verify_id:
                verify_resp = _verify_phonepe_order(verify_id)

                # handle nested shapes
                data = verify_resp.get("data", {}) if isinstance(verify_resp.get("data"), dict) else {}

                payment_status = (
                    data.get("state")
                    or data.get("status")
                    or verify_resp.get("state")
                    or verify_resp.get("status")
                    or "PENDING"
                ).upper()

                amount_paise = int(
                    data.get("amount")
                    or verify_resp.get("amount")
                    or 0
                )

                payment_id = (
                    data.get("paymentDetails", {}).get("transactionId")
                    or data.get("transactionId")
                    or data.get("paymentId")
                    or ""
                )

                # if non-json/204 fallback, do not force pending forever
                if verify_resp.get("_non_json") or verify_resp.get("_json_parse_error"):
                    # keep previous DB status if already paid via callback
                    if order and order.order_status == "paid":
                        payment_status = "SUCCESS"

        except Exception:
            logger.exception("PhonePe verify failed")

        # IMPORTANT fallback from DB
        if order:
            if (not payment_id) and order.phonepe_payment_id:
                payment_id = order.phonepe_payment_id

            if amount_paise <= 0 and order.order_amount:
                amount_paise = int(order.order_amount * 100)

            # if callback already marked paid, honor it
            if order.order_status == "paid":
                payment_status = "SUCCESS"

        mapped = _map_phonepe_status_to_order_status(payment_status)

        if order:
            order.order_status = mapped
            order.payment_provider = "phonepe"
            order.phonepe_order_id = phonepe_order_id or order.phonepe_order_id
            order.phonepe_payment_id = payment_id or order.phonepe_payment_id
            order.pa_payment_id = payment_id or order.pa_payment_id
            order.phonepe_raw_response = {
                "return_query": request.GET.dict(),
                "verify_response": verify_resp,
            }
            order.save()

        ui_url = "/merchants/store/"
        q = urlencode({
            "payment_status": (payment_status or "PENDING").upper(),
            "merchantOrderId": merchant_order_id or (order.merchant_order_id if order else ""),
            "orderId": phonepe_order_id or (order.phonepe_order_id if order else ""),
            "paymentId": payment_id,
            "amount": amount_paise,
        })
        return redirect(f"{ui_url}?{q}")

@method_decorator(csrf_exempt, name="dispatch")
class PhonePeCallbackView(APIView):
    """
    Webhook callback from PhonePe. Also updates DB.
    """
    authentication_classes = []
    permission_classes = []

    def post(self, request):
        raw = request.body or b""
        if not raw:
            return Response({"ok": False, "error": "empty body"}, status=status.HTTP_400_BAD_REQUEST)

        try:
            payload = json.loads(raw.decode("utf-8"))
        except Exception:
            logger.exception("callback: invalid json")
            return Response({"ok": False, "error": "invalid json"}, status=status.HTTP_400_BAD_REQUEST)

        merchant_order_id = payload.get("merchantOrderId") or payload.get("merchantTransactionId")
        phonepe_txn = payload.get("transactionId") or payload.get("paymentId") or payload.get("txnId")
        status_str = payload.get("status") or payload.get("state") or payload.get("paymentStatus") or ""

        order = None
        if merchant_order_id:
            order = OrderInfo.objects.filter(merchant_order_id=merchant_order_id).first()
        if not order and phonepe_txn:
            order = OrderInfo.objects.filter(pa_payment_id=phonepe_txn).first()

        if not order:
            logger.warning("PhonePe callback unknown order payload=%s", payload)
            return Response({"ok": True, "note": "unknown order logged"}, status=status.HTTP_200_OK)

        order.order_status = _map_phonepe_status_to_order_status(status_str)
        order.payment_provider = "phonepe"
        order.phonepe_order_id = merchant_order_id or order.phonepe_order_id
        order.phonepe_payment_id = phonepe_txn or order.phonepe_payment_id
        order.pa_payment_id = phonepe_txn or order.pa_payment_id
        order.phonepe_raw_response = payload
        order.save()

        return Response({"ok": True, "message": "callback processed"}, status=status.HTTP_200_OK)