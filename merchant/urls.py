# merchant/urls.py
from django.urls import path
from django.views.generic import TemplateView
from payments.api.v1.generate_order import GenerateOrder, VerifyPayment, CreatePayment
from .v1.create_merchant import CreateMerchant, LoginMerchant

urlpatterns = [
    path("store/", TemplateView.as_view(template_name="merchant/static/index.html"), name="store"),
    path("track/", TemplateView.as_view(template_name="merchant/static/tracking.html"), name="track"),
    path("dashboard/", TemplateView.as_view(template_name="merchant/static/dashboard.html"), name="dashboard"),
    path("login_test/", TemplateView.as_view(template_name="merchant/static/auth.html"), name="login"),
    path('create_merchant/', CreateMerchant.as_view(), name='create_merchant'),
    path('login/', LoginMerchant.as_view(), name='login_merchant'),
]