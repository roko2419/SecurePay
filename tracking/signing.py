# Signs the enquiry link a customer gets (via WhatsApp — see
# tracking.api.v1.track_shipments.notify_customer_delivered) so
# tracking.api.v1.enquiry.SubmitEnquiry can trust the order_id in the query
# string wasn't tampered with, without requiring the customer to log in.
#
# --- How the signature is keyed, and what that means for SECRET_KEY -------
# The signature is an HMAC-SHA256 over the order_id, keyed on Django's own
# SECRET_KEY (settings.SECRET_KEY). Two consequences of that worth knowing:
#   1. No separate secret to configure — this rides on whatever SECRET_KEY
#      is already set for the Django install, so there's nothing extra to
#      set up for this feature specifically.
#   2. If SECRET_KEY is ever rotated (e.g. after a leak, or during a
#      redeploy that regenerates it), every enquiry link already sent out
#      instantly becomes invalid — verify_order_signature() will reject it,
#      and the customer's link will show as "invalid or tampered" even
#      though nothing malicious happened. If you need to rotate SECRET_KEY
#      in production, be aware this silently invalidates all outstanding
#      enquiry links (there's no separate signing key here to rotate
#      independently of the main one).
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
    """True only if `signature` is exactly what sign_order_id(order_id)
    would produce right now. Uses hmac.compare_digest (constant-time) rather
    than `==` specifically because this IS a security-sensitive signature
    check — unlike a plain equality check on an already-hashed password,
    getting this one wrong would open a timing side-channel an attacker
    could actually use to forge a valid signature bit-by-bit."""
    if not order_id or not signature:
        return False
    expected = sign_order_id(order_id)
    return hmac.compare_digest(expected, signature)


def build_enquiry_link(base_url: str, order_id: str) -> str:
    """Build the full customer-facing enquiry URL: base_url with `order_id`
    and its signature (`sig`) as query params. The customer clicks/taps this
    link straight from WhatsApp; no login, no other proof of identity is
    required or possible — the signature IS the only thing standing between
    "this is genuinely about order X" and "someone guessed/enumerated an
    order id and is trying to submit a fake complaint about it".

    base_url is the frontend origin + /enquiry path, e.g.
    https://shop.example.com/enquiry — see settings.FRONTEND_ENQUIRY_URL,
    which is what callers pass in here in practice (don't hardcode a
    different base_url per call site; go through that setting so there's
    one place to change it for all environments).
    """
    signature = sign_order_id(order_id)
    return f"{base_url}?order_id={order_id}&sig={signature}"
