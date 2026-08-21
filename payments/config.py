import os


RAZORPAY_CREATE_ORDER_URL = "https://api.razorpay.com/v1/orders"
RAZORPAY_KEY_ID = "rzp_test_TMSImQ7xA7UKnb"
RAZORPAY_KEY_SECRET = "DsSY85jJ32Rs7yrkKkIBOuBh"

PHONEPE_OAUTH_URL = os.getenv('PHONEPE_OAUTH_URL', 'https://api-preprod.phonepe.com/apis/pg-sandbox/v1/oauth/token')
PHONEPE_CLIENT_ID = 'M22J56EQ0Q3FO_2608121252'
PHONEPE_CLIENT_VERSION = '1'
PHONEPE_CLIENT_SECRET = 'ODg3YjE2OWYtN2FlOS00M2MyLWJmODAtZDc1MzQ2NzA3OTdm'

# existing PhonePe settings you may already have:
PHONEPE_BASE_URL = os.getenv('PHONEPE_BASE_URL', 'https://api-preprod.phonepe.com/apis/pg-sandbox/v1')
# Initiate Payment endpoint path (PhonePe Standard Checkout)
PHONEPE_INIT_ENDPOINT = os.getenv('PHONEPE_INIT_ENDPOINT', '/pg/v1/pay')
PHONEPE_INIT_URL = PHONEPE_BASE_URL + PHONEPE_INIT_ENDPOINT

# Callback URL path that PhonePe will POST to (must match what you pass in initiate)
PHONEPE_CALLBACK_ENDPOINT = os.getenv('PHONEPE_CALLBACK_ENDPOINT', '/payments/phonepe/callback/')
