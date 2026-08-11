# payments/urls.py
from django.urls import path
from payments.api.v1.generate_order import GenerateOrder, VerifyPayment, CreatePayment, ShipmentListView

urlpatterns = [
    path('create_payment/', CreatePayment.as_view(), name='create_payment'),
    path('verify_payment/', VerifyPayment.as_view(), name='verify_payment'),
    path('v1/shipments/', ShipmentListView.as_view(), name='shipment-list'),
]