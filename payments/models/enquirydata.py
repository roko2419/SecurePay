from django.conf import settings
from django.db import models


class EnquiryData(models.Model):
    RECEIPT_STATUS_CHOICES = [
        ("received", "Received"),
        ("not_received", "Not Received"),
        ("wrong_order", "Wrong Order"),
    ]

    RESOLUTION_STATUS_CHOICES = [
        ("unresolved", "Unresolved"),
        ("money_refunded", "Money Refunded"),
        ("money_to_merchant", "Money To Merchant"),
    ]

    id = models.AutoField(primary_key=True)
    enquiry_id = models.CharField(max_length=100, null=False, blank=False, unique=True)
    order_id = models.CharField(max_length=100, null=False, blank=False)
    enquiry_text = models.TextField(null=False, blank=False)
    receipt_status = models.CharField(max_length=20, choices=RECEIPT_STATUS_CHOICES, null=False)
    someone_else_received = models.BooleanField(null=True, blank=True)
    agent_contacted = models.BooleanField(null=True, blank=True)
    otp_shared = models.BooleanField(null=True, blank=True)
    unboxing_evidence = models.BooleanField(null=True, blank=True)
    evidence_file = models.FileField(upload_to="enquiry_evidence/", null=True, blank=True)
    status = models.CharField(max_length=20, default="pending")  # pending / reviewed / resolved
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    # Admin resolution tracking: who decided where the money goes, and why.
    resolution_status = models.CharField(
        max_length=20, choices=RESOLUTION_STATUS_CHOICES, default="unresolved"
    )
    resolution_reason = models.TextField(null=True, blank=True)
    resolved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    resolved_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "enquiry_data"


class EnquiryNote(models.Model):
    """A running log of admin notes left on an enquiry."""

    id = models.AutoField(primary_key=True)
    enquiry = models.ForeignKey(EnquiryData, on_delete=models.CASCADE, related_name="notes")
    note = models.TextField(null=False, blank=False)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "enquiry_note"
        ordering = ["-created_at"]
