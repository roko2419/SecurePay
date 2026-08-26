import hashlib
import hmac

from django.conf import settings


def sign_order_id(order_id: str) -> str:
    """Return an HMAC signature for order_id, keyed on SECRET_KEY."""
    return hmac.new(
        settings.SECRET_KEY.encode(),
        order_id.encode(),
        hashlib.sha256,
    ).hexdigest()


def verify_order_signature(order_id: str, signature: str) -> bool:
    if not order_id or not signature:
        return False
    expected = sign_order_id(order_id)
    return hmac.compare_digest(expected, signature)


def build_enquiry_link(base_url: str, order_id: str) -> str:
    """base_url is the frontend origin, e.g. https://shop.example.com/enquiry"""
    signature = sign_order_id(order_id)
    return f"{base_url}?order_id={order_id}&sig={signature}"
