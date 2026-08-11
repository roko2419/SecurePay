# payments/models.py
from django.db import models
from django.utils import timezone
import uuid

STATUS_CHOICES = [
    ("CREATED", "Created"),
    ("AWAITING_PAYMENT", "Awaiting Payment"),
    ("PAID", "Paid"),
    ("HELD", "Held"),
    ("RELEASED", "Released"),
    ("FAILED", "Failed"),
    ("DELIVERED", "Delivered"),
    ("REFUNDED", "Refunded"),
    ("SETTLED", "Settled"),
]

def gen_awb():
    return f"AWB{uuid.uuid4().hex[:10].upper()}"

class Shipment(models.Model):
    awb = models.CharField(max_length=64, unique=True, default=gen_awb)
    courier = models.CharField(max_length=128, blank=True, null=True)
    pa_order_id = models.CharField(max_length=128, blank=True, null=True)
    invoice = models.CharField(max_length=128, blank=True, null=True)
    status = models.CharField(max_length=32, choices=STATUS_CHOICES, default="CREATED")
    history = models.JSONField(default=list)  # list of {ts, status, note}
    created_at = models.DateTimeField(default=timezone.now)

    def add_history(self, status, note=None):
        entry = {"ts": timezone.now().isoformat(), "status": status}
        if note:
            entry["note"] = note
        h = self.history or []
        h.append(entry)
        self.history = h
        self.save(update_fields=["history"])

    def __str__(self):
        return self.awb