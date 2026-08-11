from django.db import models

class MerchantInfo(models.Model):
    id = models.AutoField(primary_key=True)
    merchant_key = models.CharField(max_length=100, unique=True, null=False, blank=False)
    merchant_salt = models.CharField(max_length=100, unique=True, null=False, blank=False)
    merchant_name = models.CharField(max_length=100, null=False, blank=False)
    merchant_email = models.EmailField(null=False, blank=False)
    merchant_phone = models.CharField(max_length=15, null=False, blank=False)
    merchant_address = models.TextField()
    