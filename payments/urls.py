# payments/urls.py
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