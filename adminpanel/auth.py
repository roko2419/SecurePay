import secrets

from django_redis import get_redis_connection

TOKEN_TTL_SECONDS = 1800
REDIS_PREFIX = "admin_session"


def _redis_key(token):
    return f"{REDIS_PREFIX}:{token}"


def create_admin_session(user):
    token = secrets.token_urlsafe(32)
    redis_conn = get_redis_connection("default")
    redis_conn.setex(_redis_key(token), TOKEN_TTL_SECONDS, str(user.id))
    return token


def get_admin_user_id_from_token(auth_token):
    if not auth_token:
        return None
    try:
        redis_conn = get_redis_connection("default")
        user_id = redis_conn.get(_redis_key(auth_token))
        if not user_id:
            return None
        redis_conn.expire(_redis_key(auth_token), TOKEN_TTL_SECONDS)
        return int(user_id)
    except Exception:
        return None


def destroy_admin_session(auth_token):
    try:
        redis_conn = get_redis_connection("default")
        redis_conn.delete(_redis_key(auth_token))
    except Exception:
        pass


def get_auth_token_from_request(request):
    auth_header = request.headers.get("Authorization", "")
    if auth_header.lower().startswith("bearer "):
        return auth_header.split(" ", 1)[1].strip()
    return None
