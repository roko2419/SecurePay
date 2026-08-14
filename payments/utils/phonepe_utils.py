# payments/phonepe_utils.py
import base64
import hashlib
import hmac
import json
from django.conf import settings

def base64_encode_json(obj):
    """
    Return base64-encoded compact JSON string (PhonePe expects compact JSON before base64).
    """
    body = json.dumps(obj, separators=(',', ':'))
    return base64.b64encode(body.encode('utf-8')).decode('utf-8')

def generate_phonepe_signature(base64_payload: str, endpoint_path: str, salt_key: str | None = None, salt_index: str | None = None) -> str:
    """
    Compute HMAC-SHA256 hex digest over (base64_payload + endpoint_path + salt_key)
    Return header string: "{hex_digest}###{salt_index}"
    """
    if salt_key is None:
        salt_key = getattr(settings, "PHONEPE_SALT_KEY", None) or ""
    if salt_index is None:
        salt_index = getattr(settings, "PHONEPE_SALT_INDEX", None) or "1"

    to_sign = base64_payload + endpoint_path + salt_key
    mac = hmac.new(salt_key.encode('utf-8'), to_sign.encode('utf-8'), hashlib.sha256)
    signature_hex = mac.hexdigest()
    return f"{signature_hex}###{salt_index}"