from django.db import models

class EnquiryData(models.Model):
    id = models.AutoField(primary_key=True)
    enquiry_id = models.CharField(max_length=100, null=False, blank=False, unique=True)
    order_id = models.CharField(max_length=100, null=False, blank=False)
    enquiry_text = models.TextField(null=False, blank=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "enquiry_data"