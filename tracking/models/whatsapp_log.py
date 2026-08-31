# A record of every WhatsApp message this app has tried to send via GetGabs
# (see tracking.api.v1.notifs.send_whatsapp_text), so we can confirm a
# message actually went out and look up its provider message id if a
# customer says they never received it.
from django.db import models


class WhatsAppMessageLog(models.Model):
    STATUS_CHOICES = [
        ("pending", "Pending"),
        ("sent", "Sent"),
        ("failed", "Failed"),
    ]

    id = models.AutoField(primary_key=True)

    # Who we tried to message, and why.
    to_number = models.CharField(max_length=20, db_index=True)
    purpose = models.CharField(max_length=50, blank=True)  # e.g. "delivery_enquiry"
    order_id = models.CharField(max_length=100, blank=True, db_index=True)  # pa_order_id, when applicable
    message_body = models.TextField()

    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default="pending")
    error = models.TextField(blank=True, null=True)

    # Populated from GetGabs's response on success — see the sample response
    # in the API doc: {"contacts": [{"wa_id": ...}], "messages": [{"id": ...}]}.
    wa_id = models.CharField(max_length=32, blank=True)
    wa_message_id = models.CharField(max_length=128, blank=True, db_index=True)
    raw_response = models.JSONField(blank=True, null=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "whatsapp_message_log"
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.to_number} [{self.status}] {self.purpose or 'message'}"
