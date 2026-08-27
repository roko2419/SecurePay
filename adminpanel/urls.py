from django.urls import path

from adminpanel.api.v1.auth_views import AdminLoginView, AdminLogoutView, AdminMeView
from adminpanel.api.v1.orders_views import AdminOrderListView, AdminEnquiryListView
from adminpanel.api.v1.stats_views import AdminStatsView
from adminpanel.api.v1.enquiry_actions_views import (
    AdminEnquiryNoteListView,
    AdminEnquiryNoteDetailView,
    AdminEnquiryResolutionView,
)

urlpatterns = [
    path("login/", AdminLoginView.as_view(), name="admin-login"),
    path("logout/", AdminLogoutView.as_view(), name="admin-logout"),
    path("me/", AdminMeView.as_view(), name="admin-me"),
    path("orders/", AdminOrderListView.as_view(), name="admin-orders"),
    path("enquiries/", AdminEnquiryListView.as_view(), name="admin-enquiries"),
    path("enquiries/<int:enquiry_id>/notes/", AdminEnquiryNoteListView.as_view(), name="admin-enquiry-notes"),
    path(
        "enquiries/<int:enquiry_id>/notes/<int:note_id>/",
        AdminEnquiryNoteDetailView.as_view(),
        name="admin-enquiry-note-detail",
    ),
    path(
        "enquiries/<int:enquiry_id>/resolution/",
        AdminEnquiryResolutionView.as_view(),
        name="admin-enquiry-resolution",
    ),
    path("stats/", AdminStatsView.as_view(), name="admin-stats"),
]
