
from payments.models.merchantinfo import MerchantInfo
from hashlib import sha512

def verify_merchant_auth_token(merchant_id, auth_token, merchant_order_id):
    try:
        merchant = MerchantInfo.objects.get(id=merchant_id)
        expected_auth_token = sha512((merchant.merchant_key + merchant_order_id + merchant.merchant_salt).encode()).hexdigest()
        return auth_token == expected_auth_token
    except MerchantInfo.DoesNotExist:
        return False