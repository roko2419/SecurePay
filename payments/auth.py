import secrets
from hashlib import sha512

from django_redis import get_redis_connection

from payments.models.merchantinfo import MerchantInfo


TOKEN_TTL_SECONDS = 300


def _normalize_session_token(merchant_id, auth_token):
    """Accept either raw token or <merchant_id>-<token> format."""
    token = str(auth_token)
    provided_merchant_id = str(merchant_id) if merchant_id is not None else None
    prefix, separator, remainder = token.partition("-")

    if separator and prefix.isdigit() and remainder:
        if provided_merchant_id and prefix != provided_merchant_id:
            return None, None
        return int(prefix), remainder

    if merchant_id is None:
        return None, None

    try:
        return int(merchant_id), token
    except (TypeError, ValueError):
        return None, None


def _verify_session_token_and_refresh(merchant_id, auth_token):
    """Validate session token from Redis and refresh TTL on each valid request."""
    redis_key = f"merchant_{merchant_id}:{auth_token}"
    try:
        redis_conn = get_redis_connection("default")
        exists = redis_conn.exists(redis_key)
        if not exists:
            return False
        redis_conn.expire(redis_key, TOKEN_TTL_SECONDS)
        return True
    except Exception:
        return False


def get_merchant_id_from_token(auth_token):
    """Return merchant_id from an active session token, else None."""
    if not auth_token:
        return None

    normalized_merchant_id, normalized_token = _normalize_session_token(None, auth_token)
    if not normalized_merchant_id or not normalized_token:
        return None

    if _verify_session_token_and_refresh(normalized_merchant_id, normalized_token):
        return normalized_merchant_id

    return None


def verify_merchant_auth_token(merchant_id, auth_token, merchant_order_id=None):
    if not auth_token:
        return False

    token_merchant_id = get_merchant_id_from_token(auth_token)
    if token_merchant_id is not None:
        if merchant_id is None:
            return True
        try:
            return int(merchant_id) == token_merchant_id
        except (TypeError, ValueError):
            return False

    normalized_merchant_id, normalized_token = _normalize_session_token(merchant_id, auth_token)
    if not normalized_merchant_id or not normalized_token:
        return False

    if not merchant_order_id:
        return False

    try:
        merchant = MerchantInfo.objects.get(id=normalized_merchant_id)
        expected_auth_token = sha512(
            (merchant.merchant_key + merchant_order_id + merchant.merchant_salt).encode()
        ).hexdigest()
        return secrets.compare_digest(str(auth_token), expected_auth_token)
    except MerchantInfo.DoesNotExist:
        return False