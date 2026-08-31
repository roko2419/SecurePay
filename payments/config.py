# Payment-provider credentials/endpoints.
#
# IMPORTANT — read this before touching PhonePe settings anywhere in this
# project: there are TWO separate places PhonePe config lives, and only one
# of them is actually used at runtime.
#
#   1. THIS FILE (payments/config.py) — PHONEPE_OAUTH_URL, PHONEPE_CLIENT_ID,
#      PHONEPE_CLIENT_VERSION, PHONEPE_CLIENT_SECRET, PHONEPE_BASE_URL,
#      PHONEPE_INIT_ENDPOINT, PHONEPE_INIT_URL, PHONEPE_CALLBACK_ENDPOINT
#      below are DEAD CODE. Nothing in the codebase imports them. Editing
#      them will change nothing.
#   2. securepay/securepay/settings.py — defines its OWN
#      PHONEPE_OAUTH_URL / PHONEPE_CLIENT_ID / PHONEPE_CLIENT_SECRET /
#      PHONEPE_INIT_URL / PHONEPE_STATUS_URL. These are what
#      payments/api/v1/phonepe.py and payments/api/v1/phonepe_auth.py
#      actually read, via Django's `from django.conf import settings` and
#      then `settings.PHONEPE_...`. THIS is the file to edit if you need to
#      change a PhonePe client id/secret/URL.
#
# Why both exist: this file looks like an earlier attempt at centralizing
# config that was later superseded by putting the real values directly in
# settings.py, without deleting the old ones here. Left as-is (not asked to
# fix) — but if you're refactoring this later, the safe move is deleting the
# PHONEPE_* constants below and confirming `grep -rn "payments.config"` finds
# nothing PhonePe-related still importing them (RAZORPAY_* below, on the
# other hand, IS actively used — don't delete those).
#
# --- Razorpay: ACTUALLY USED (by payments/api/v1/generate_order.py) --------
# Test/sandbox credentials. Get real ones from the Razorpay dashboard
# (Settings > API Keys) before accepting real payments, and move them to
# environment variables rather than leaving them hardcoded here — see
# securepay/settings.py's own note about hardcoded secrets for why.
import os


RAZORPAY_CREATE_ORDER_URL = "https://api.razorpay.com/v1/orders"
RAZORPAY_KEY_ID = "rzp_test_TMSImQ7xA7UKnb"
RAZORPAY_KEY_SECRET = "DsSY85jJ32Rs7yrkKkIBOuBh"

# --- PhonePe: DEAD CODE — see the big note above. Not read by anything. -----
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
