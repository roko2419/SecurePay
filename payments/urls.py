# payments/urls.py
# Mounted at /payments/ in securepay/urls.py. Merchant-facing endpoints below
# (create_payment/verify_payment/shipments) are authenticated with a merchant
# session token (see payments.auth), not Django's session/user auth.
from django.urls import path
from payments.api.v1.generate_order import GenerateOrder, VerifyPayment, CreatePayment, ShipmentListView
from payments.api.v1.phonepe import PhonePeCallbackView, PhonePeInitiateView, PhonePeReturnView

urlpatterns = [
    path('create_payment/', CreatePayment.as_view(), name='create_payment'),
    path('verify_payment/', VerifyPayment.as_view(), name='verify_payment'),
    path('v1/shipments/', ShipmentListView.as_view(), name='shipment-list'),
    path("phonepe/initiate/", PhonePeInitiateView.as_view(), name="phonepe-initiate"),
    path("phonepe/return/", PhonePeReturnView.as_view(), name="phonepe-return"),
    path("phonepe/callback/", PhonePeCallbackView.as_view(), name="phonepe-callback"),
]