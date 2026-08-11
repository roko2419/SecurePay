# payments/urls.py
from django.urls import path
from django.views.generic import TemplateView
from payments.api.v1.generate_order import GenerateOrder, VerifyPayment, CreatePayment

urlpatterns = [
    path("store/", TemplateView.as_view(template_name="merchant/static/index.html"), name="store"),
    path("track/", TemplateView.as_view(template_name="merchant/static/tracking.html"), name="track"),
    path("dashboard/", TemplateView.as_view(template_name="merchant/static/dashboard.html"), name="dashboard"),
]