from django.db import models

class OrderInfo(models.Model):
    id = models.AutoField(primary_key=True)
    merchant = models.ForeignKey('payments.MerchantInfo', on_delete=models.CASCADE)
    merchant_order_id = models.CharField(max_length=100, null=False, blank=False)
    pa_order_id = models.CharField(max_length=100, null=True, blank=True)
    pa_payment_id = models.CharField(max_length=100, null=True, blank=True)
    order_amount = models.DecimalField(max_digits=10, decimal_places=2, null=False, blank=False)
    order_currency = models.CharField(max_length=10, null=False, blank=False, default='INR')
    order_status = models.CharField(max_length=20, null=False, blank=False)
    customer_info = models.ForeignKey('payments.CustomerInfo', on_delete=models.CASCADE)
    order_date = models.DateTimeField(auto_now_add=True)
    shipment_id = models.ForeignKey('tracking.Shipment', on_delete=models.SET_NULL, null=True, blank=True)
    phonepe_order_id = models.CharField(max_length=128, blank=True, null=True)
    phonepe_payment_id = models.CharField(max_length=128, blank=True, null=True)
    phonepe_raw_response = models.JSONField(blank=True, null=True)  # Django 3.1+ has models.JSONField; otherwise use contrib.postgres.JSONField
    payment_provider = models.CharField(max_length=32, blank=True, null=True)
    enquiry = models.ForeignKey('payments.EnquiryData', on_delete=models.SET_NULL, null=True, blank=True)