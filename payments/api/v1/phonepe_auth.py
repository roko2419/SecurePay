# payments/phonepe_oauth.py
import time
import requests
from django.conf import settings
from django.core.cache import cache

_OAUTH_CACHE_KEY = "phonepe_oauth_token_v1"
_MODULE_CACHE = {"token": None, "expires_at": 0}

def fetch_new_token():
    url = settings.PHONEPE_OAUTH_URL
    data = {
        "client_id": settings.PHONEPE_CLIENT_ID,
        "client_version": settings.PHONEPE_CLIENT_VERSION,
        "client_secret": settings.PHONEPE_CLIENT_SECRET,
        "grant_type": "client_credentials"
    }
    headers = {"Content-Type": "application/x-www-form-urlencoded"}
    resp = requests.post(url, data=data, headers=headers, timeout=10)
    resp.raise_for_status()
    return resp.json()

def get_phonepe_oauth_token(force_refresh=False) -> str:
    """
    Return access token string. Cached until expiry.
    """
    now = time.time()
    try:
        if not force_refresh:
            cached = cache.get(_OAUTH_CACHE_KEY)
            if cached and cached.get("access_token") and cached.get("expires_at", 0) > now + 5:
                return cached["access_token"]
    except Exception:
        cached = None

    if not force_refresh and _MODULE_CACHE["token"] and _MODULE_CACHE["expires_at"] > now + 5:
        return _MODULE_CACHE["token"]

    data = fetch_new_token()
    access_token = data.get("access_token")
    expires_in = int(data.get("expires_in", 3600))
    if not access_token:
        raise RuntimeError(f"PhonePe token missing access_token: {data!r}")

    expires_at = now + expires_in
    cache_payload = {"access_token": access_token, "expires_at": expires_at}
    try:
        cache.set(_OAUTH_CACHE_KEY, cache_payload, timeout=max(0, expires_in - 5))
    except Exception:
        pass

    _MODULE_CACHE["token"] = access_token
    _MODULE_CACHE["expires_at"] = expires_at

    return access_token