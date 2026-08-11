from django.db import models

class CustomerInfo(models.Model):
    id = models.AutoField(primary_key=True)
    customer_name = models.CharField(max_length=100, null=False, blank=False)
    customer_email = models.EmailField(null=False, blank=False)
    customer_phone = models.CharField(max_length=15, null=False, blank=False, unique=True)
    customer_address = models.TextField()