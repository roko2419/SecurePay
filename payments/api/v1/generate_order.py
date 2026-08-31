# Razorpay checkout flow: create an order, then verify the payment signature.
#
# NOTE: this file defines CreatePayment and VerifyPayment twice — a DRF
# APIView pair up top (GenerateOrder/VerifyPayment), and a plain Django View
# pair further down (also named CreatePayment/VerifyPayment). Because both
# live at module scope, the later definitions silently replace the earlier
# ones; payments/urls.py imports CreatePayment/VerifyPayment from here and
# gets the *second* (View-based) versions. GenerateOrder itself is unused/
# unrouted. Left as-is since untangling it is a behavior change, not a
# comment — flagging it here so it's not mistaken for dead code.
from django.utils import timezone
import os

import requests
import razorpay
from rest_framework.views import APIView, Response, status

from payments.auth import get_merchant_id_from_token
from payments.models.orderinfo import OrderInfo
from payments.models.customerinfo import CustomerInfo
from payments.api.v1.phonepe import PhonePeInitiateView
from payments.config import RAZORPAY_CREATE_ORDER_URL, RAZORPAY_KEY_ID, RAZORPAY_KEY_SECRET


client = razorpay.Client(auth=(RAZORPAY_KEY_ID, RAZORPAY_KEY_SECRET))


def _get_auth_token_from_request(request, payload=None):
    """Pull the merchant session token from the Authorization header, the
    parsed JSON payload, request.data, or a query param — whichever the
    caller used. Lets both DRF (request.data) and plain-Django (raw payload)
    views in this file share one lookup."""
    auth_header = request.headers.get("Authorization", "")
    if auth_header.lower().startswith("bearer "):
        return auth_header.split(" ", 1)[1].strip()

    if payload and payload.get("auth_token"):
        return payload.get("auth_token")

    data = getattr(request, "data", None)
    if data and data.get("auth_token"):
        return data.get("auth_token")

    return request.GET.get("auth_token")

class GenerateOrder(APIView):
    """Not wired up in urls.py — superseded by the CreatePayment View below."""

    def post(self, request):
        self.auth_token = _get_auth_token_from_request(request)
        token_merchant_id = get_merchant_id_from_token(self.auth_token)
        if token_merchant_id is None:
            return Response({"error": "Invalid or expired merchant token"}, status=status.HTTP_401_UNAUTHORIZED)

        self.merchant_id = token_merchant_id
        self.merchant_order_id = request.data.get('merchant_order_id')
        self.customer_name = request.data.get('customer_name')
        self.customer_email = request.data.get('customer_email')
        self.customer_phone = request.data.get('customer_phone')
        self.amount = int(request.data.get('amount'))

        self.generate_order()
        return self.create_pa_order()

    def generate_order(self):
        try:
            customer_info = CustomerInfo.objects.get(customer_phone=self.customer_phone)
        except CustomerInfo.DoesNotExist:
            customer_info = CustomerInfo(
                customer_name=self.customer_name,
                customer_email=self.customer_email,
                customer_phone=self.customer_phone
            )
            customer_info.save()

        self.order_info = OrderInfo(
            merchant_id=self.merchant_id,
            merchant_order_id=self.merchant_order_id,
            order_amount=self.amount,
            order_currency="INR",
            customer_info_id=customer_info.id
        )

    def create_pa_order(self):
        PhonePeInitiateView
        try:
            payload = {
                "amount": self.amount * 100,  # Amount in paise
                "currency": "INR",
                "payment_capture": "1"
            }
            response = client.order.create(payload)
            self.order_info.order_status = response['status']
            self.order_info.pa_order_id = response['id']
            self.order_info.save()
            return Response(response)
        except Exception as e:
            return Response({"error": str(e)}, status=status.HTTP_400_BAD_REQUEST)


class VerifyPayment(APIView):
    """Placeholder — shadowed by the View-based VerifyPayment defined later
    in this file (see the module-level note above); not actually reachable."""

    def post(self, request):
        print("Request data:", request.data)
        return Response(request.data)

# payments/api/v1/payment_views.py
import os
import json
import hmac
import hashlib
from decimal import Decimal

from django.views.decorators.csrf import csrf_exempt
from django.http import JsonResponse, HttpResponseBadRequest, HttpResponse
from django.utils.decorators import method_decorator
from django.views import View

# Optional: import real razorpay client if installed
try:
    import razorpay
    RZP_AVAILABLE = True
except Exception:
    RZP_AVAILABLE = False

# This is the CreatePayment actually routed by payments/urls.py (see note
# at the top of the file about the duplicate class names above).
@method_decorator(csrf_exempt, name='dispatch')  # for demo: allow POST from browser without CSRF token
class CreatePayment(View):
    def post(self, request, *args, **kwargs):
        """
        Expected JSON payload:
        {
          "amount": "100.50",            # decimal string in INR rupees
          "currency": "INR",
          "receipt": "receipt_12345",
          "customer": {"name":"Alice","email":"a@x.com","contact":"9999999999"},
          "metadata": { ... }            # optional
        }
        Response:
        {
          "key": "<RAZORPAY_KEY_ID>",
          "order_id": "<razorpay_order_id>",
          "amount": 10050,   # amount in paise (integer)
          "currency": "INR",
          "callback_url": "/payments/verify_payment/"  # optional
        }
        """
        try:
            payload = json.loads(request.body.decode('utf-8'))
        except Exception:
            return HttpResponseBadRequest("invalid json")

        self.auth_token = _get_auth_token_from_request(request, payload)
        token_merchant_id = get_merchant_id_from_token(self.auth_token)
        if token_merchant_id is None:
            return JsonResponse({"error": "Invalid or expired merchant token"}, status=401)
        self.merchant_id = token_merchant_id

        # Validate & compute amount in paise
        self.amount_str = str(payload.get("amount", "0")).strip()
        try:
            # Convert rupees string to paise integer
            amount_paise = int((Decimal(self.amount_str) * 100).quantize(Decimal('1')))
        except Exception:
            return HttpResponseBadRequest("invalid amount")

        currency = payload.get("currency", "INR")
        receipt = payload.get("receipt", f"rcpt_{os.urandom(4).hex()}")
        notes = payload.get("metadata", {})
        customer = payload.get("customer", {})

        self.customer_name = customer.get("name", "")
        self.customer_email = customer.get("email", "")
        self.customer_phone = customer.get("contact", "")
        self.mock_order_id = f"mock_rzp_{os.urandom(4).hex()}"

        # Use real Razorpay if available & keys present
        if RZP_AVAILABLE and RAZORPAY_KEY_ID and RAZORPAY_KEY_SECRET:
            client = razorpay.Client(auth=(RAZORPAY_KEY_ID, RAZORPAY_KEY_SECRET))
            order_data = {
                "amount": amount_paise,
                "currency": currency,
                "receipt": receipt,
                "notes": notes
            }
            try:
                rzp_order = client.order.create(data=order_data)
                # rzp_order looks like {"id":"order_XXX", "status":"created", ...}
                self.order_id = rzp_order["id"]
                self.generate_order()  # store in our DB
                return JsonResponse({
                    "key": RAZORPAY_KEY_ID,
                    "order_id": rzp_order["id"],
                    "amount": amount_paise,
                    "currency": currency,
                    "callback_url": "/payments/verify_payment/",
                    "customer": customer
                })
            except Exception as e:
                return JsonResponse({"error": "failed to create razorpay order", "detail": str(e)}, status=500)

        # Fallback mock order (useful for local dev without SDK)
        # store mapping somewhere (DB) in real app; here we return for demo
        return JsonResponse({
            "key": RAZORPAY_KEY_ID,
            "order_id": self.mock_order_id,
            "amount": amount_paise,
            "currency": currency,
            "callback_url": "/payments/verify_payment/",
            "customer": customer,
            "note": "mock_razorpay_order"
        })

    def generate_order(self):
        try:
            customer_info = CustomerInfo.objects.get(customer_phone=self.customer_phone)
        except CustomerInfo.DoesNotExist:
            customer_info = CustomerInfo(
                customer_name=self.customer_name,
                customer_email=self.customer_email,
                customer_phone=self.customer_phone
            )
            customer_info.save()

        self.order_info = OrderInfo(
            merchant_id=self.merchant_id,
            merchant_order_id=self.mock_order_id,
            order_amount=self.amount_str,
            order_currency="INR",
            customer_info_id=customer_info.id,
            pa_order_id=self.order_id,
        )
        self.order_info.save()



# This is the VerifyPayment actually routed by payments/urls.py.
@method_decorator(csrf_exempt, name='dispatch')
class VerifyPayment(View):
    def post(self, request, *args, **kwargs):
        """
        Expects JSON:
        {
          "razorpay_order_id": "...",
          "razorpay_payment_id": "...",
          "razorpay_signature": "..."
        }
        Verifies signature using RAZORPAY_KEY_SECRET (HMAC SHA256 of order_id|payment_id)
        On success: mark internal order/payment as paid, return success JSON.

        *** SECURITY BUG — READ BEFORE RELYING ON THIS ENDPOINT ***
        The docstring above describes the INTENDED behavior, but the code
        below does not actually match it: `order_info.order_status = "paid"`
        and `.save()` happen BEFORE the signature is checked (see the
        `hmac.compare_digest` call much further down). That means:
          - Any POST with a valid-looking existing razorpay_order_id gets the
            matching order marked "paid" in the database immediately —
            regardless of whether payment_id/signature are present, correct,
            or even supplied at all.
          - The signature check that follows only affects the HTTP RESPONSE
            ("signature mismatch" vs. success) — it does NOT undo the
            order_status="paid" write that already happened.
          - This means a caller who knows (or brute-forces/guesses) a
            razorpay_order_id can mark that order as paid without ever
            proving they made a real payment, simply by POSTing here with a
            wrong/missing signature. That's the exact scenario payment
            signature verification exists to prevent.
        This is a payments-integrity bug, not just a style issue. The fix
        (not applied here, since it's a behavior change beyond "add
        comments") would be moving the `order_info.order_status = "paid"` /
        `.save()` lines to AFTER the `hmac.compare_digest(...)` check
        succeeds, so a failed/forged verification leaves the order
        untouched. Flagging prominently because unlike the other issues
        noted in this codebase, this one directly affects whether money
        changes hands correctly.
        """
        try:
            payload = json.loads(request.body.decode('utf-8'))
        except Exception:
            return HttpResponseBadRequest("invalid json")
        print(payload)
        order_id = payload.get("razorpay_order_id")
        payment_id = payload.get("razorpay_payment_id")
        signature = payload.get("razorpay_signature")

        order_info = OrderInfo.objects.filter(pa_order_id=order_id).first()
        if not order_info:
            return HttpResponseBadRequest("invalid razorpay_order_id")
        # BUG (see docstring above): this write happens unconditionally,
        # before the signature below is ever checked.
        order_info.pa_payment_id = payment_id
        order_info.order_status = "paid"
        order_info.save()
        if not (order_id and payment_id and signature):
            return HttpResponseBadRequest("missing parameters")

        # This IS the correct, secure way to check a Razorpay signature
        # (HMAC-SHA256 of "order_id|payment_id" keyed on the secret, compared
        # with the constant-time hmac.compare_digest) — the problem is only
        # that it runs too late to gate the DB write above.
        msg = f"{order_id}|{payment_id}".encode()
        expected_sig = hmac.new(RAZORPAY_KEY_SECRET.encode(), msg, hashlib.sha256).hexdigest()
        if not hmac.compare_digest(expected_sig, signature):
            return JsonResponse({"ok": False, "reason": "signature mismatch"}, status=400)
        return JsonResponse({"ok": True, "message": "payment verified and processed", "razorpay_order_id": order_id, "razorpay_payment_id": payment_id})
    
class ShipmentListView(View):
    """Merchant-scoped order/shipment list — the merchant-facing counterpart
    to adminpanel.AdminOrderListView, but filtered to the logged-in merchant
    only rather than showing every merchant's orders."""

    def get(self, request, *args, **kwargs):
        """
        Example endpoint to list shipments.
        Accepts optional query params: limit (int), page (int), q (search string).
        Returns: { results: [...], page: 1, total_pages: 1 }
        """
        auth_token = _get_auth_token_from_request(request)
        token_merchant_id = get_merchant_id_from_token(auth_token)
        if token_merchant_id is None:
            return JsonResponse({"error": "Invalid or expired merchant token"}, status=401)

        # read query params
        try:
            limit = int(request.GET.get('limit', 25))
        except ValueError:
            limit = 25
        try:
            page = int(request.GET.get('page', 1))
        except ValueError:
            page = 1
        q = (request.GET.get('q') or '').strip().lower()

        all_shipments = OrderInfo.objects.filter(merchant_id=token_merchant_id).values('pa_order_id', 'order_status', 'order_amount', 'order_currency', 'customer_info__customer_name', 'customer_info__customer_email', 'customer_info__customer_phone', 'shipment_id__awb', 'shipment_id__courier', 'shipment_id__status', 'pa_payment_id').order_by('-order_date')
        # simple filtering by q (match awb, courier, or order id)
        if q:
            filtered = [s for s in all_shipments if q in (s.get('shipment_id__awb','') + s.get('shipment_id__courier','') + s.get('pa_order_id','')).lower()]
        else:
            filtered = all_shipments

        # pagination (simple)
        total = len(filtered)
        total_pages = max(1, (total + limit - 1) // limit)
        start = (page - 1) * limit
        end = start + limit
        results = filtered[start:end]

        return JsonResponse({
            "results": results,
            "page": page,
            "total_pages": total_pages,
            "total": total
        })