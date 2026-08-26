"""
URL configuration for securepay project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/6.1/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""
from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path
from django.views.generic import TemplateView
from rest_framework.permissions import AllowAny
from rest_framework.schemas import get_schema_view


schema_view = get_schema_view(
    title="SecurePay API",
    description="Public OpenAPI schema for SecurePay endpoints.",
    version="1.0.0",
    public=True,
    permission_classes=[AllowAny],
)

urlpatterns = [
    path('admin/', admin.site.urls),
    path("", TemplateView.as_view(template_name="payments/static/index.html"), name="home"),
    path("openapi.json", schema_view, name="openapi-schema"),
    # path('tracking/', include('tracking.urls')),
    path('payments/', include('payments.urls')),
    path('merchants/', include('merchant.urls')),
    path('tracking/', include('tracking.urls')),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
