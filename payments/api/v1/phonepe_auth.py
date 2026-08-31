# payments/phonepe_oauth.py
#
# Gets and caches the OAuth "O-Bearer" token PhonePe requires on every API
# call (initiate payment, check status). Called by payments/api/v1/phonepe.py
# — nothing else needs to import this module.
#
# --- Where the PhonePe credentials come from --------------------------------
# settings.PHONEPE_CLIENT_ID / PHONEPE_CLIENT_VERSION / PHONEPE_CLIENT_SECRET
# / PHONEPE_OAUTH_URL are read from Django settings (securepay/settings.py),
# NOT from payments/config.py — see the big warning at the top of
# payments/config.py if you're looking for where to change these. These are
# PhonePe *sandbox* (api-preprod.phonepe.com) credentials right now; to go
# live you'd get production credentials from the PhonePe merchant dashboard
# and point PHONEPE_OAUTH_URL / PHONEPE_INIT_URL / PHONEPE_STATUS_URL at
# PhonePe's production hosts instead of the preprod ones.
#
# --- Why the token is cached two different ways ----------------------------
# PhonePe's OAuth tokens are valid for ~1 hour (expires_in, from PhonePe's
# response) and issuing a new one on every single payment API call would be
# both slow and wasteful. So the token is cached twice:
#   1. Django's cache framework (`cache`, configured in settings.py — this
#      project uses Redis). This is the "real" cache: it's shared across
#      every worker process/thread serving requests, so only ONE of them
#      ever has to actually call PhonePe for a new token; the rest just read
#      it from Redis.
#   2. _MODULE_CACHE, a plain Python dict at module scope. This exists purely
#      as a fallback for the (hopefully rare) case where reading from Redis
#      itself throws — see the `try/except: cached = None` below. Without
#      this, a blip in the Redis connection would force every single request
#      to fetch a brand-new PhonePe token, which is both slow and burns
#      through PhonePe's own rate limits on token issuance.
# Both caches store the same {"access_token": ..., "expires_at": ...} shape,
# expire 5 seconds early (the `+ 5` / `- 5` throughout) to avoid a token that
# looks valid when read but has expired by the time it's actually used a
# moment later in the HTTP call to PhonePe.
import time
import requests
from django.conf import settings
from django.core.cache import cache

_OAUTH_CACHE_KEY = "phonepe_oauth_token_v1"
_MODULE_CACHE = {"token": None, "expires_at": 0}

def fetch_new_token():
    """Unconditionally request a fresh token from PhonePe — no caching here.
    Only get_phonepe_oauth_token() below should call this; everything else
    should go through that function so caching is respected."""
    url = settings.PHONEPE_OAUTH_URL
    data = {
        "client_id": settings.PHONEPE_CLIENT_ID,
        "client_version": settings.PHONEPE_CLIENT_VERSION,
        "client_secret": settings.PHONEPE_CLIENT_SECRET,
        "grant_type": "client_credentials"
    }
    headers = {"Content-Type": "application/x-www-form-urlencoded"}
    resp = requests.post(url, data=data, headers=headers, timeout=10)
    resp.raise_for_status()  # raises requests.HTTPError if PhonePe rejects the credentials
    return resp.json()

def get_phonepe_oauth_token(force_refresh=False) -> str:
    """
    Return a valid PhonePe OAuth access token, fetching+caching a new one
    only when necessary.

    Lookup order (each one only happens if the previous one missed):
      1. force_refresh=True skips straight to fetching a new token — pass
         this if you know the cached token was rejected by PhonePe (e.g. a
         call to phonepe.py got a 401) and want to retry with a fresh one.
      2. Django cache (Redis) — the shared, cross-process cache.
      3. The module-level dict — same-process fallback if step 2's cache
         backend itself errors out (doesn't help if step 2 just returned
         "no token cached", only if reading it *raised*).
      4. Fetch a brand-new token from PhonePe via fetch_new_token(), then
         write it into BOTH caches for next time.

    Raises:
        requests.HTTPError: if PhonePe rejects fetch_new_token()'s request
            (e.g. bad client_id/client_secret).
        RuntimeError: if PhonePe returns 200 but the response body has no
            access_token — treated as a hard failure rather than silently
            returning None, since a caller using None as a bearer token
            would just get a confusing 401 further down the line instead.
    """
    now = time.time()
    try:
        if not force_refresh:
            cached = cache.get(_OAUTH_CACHE_KEY)
            if cached and cached.get("access_token") and cached.get("expires_at", 0) > now + 5:
                return cached["access_token"]
    except Exception:
        # Redis (or whatever cache backend) itself is having a problem —
        # fall through to the module-level cache rather than failing outright.
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
        # If Redis can't be written to, we still have the module-level cache
        # below for this process — better than crashing here.
        pass

    _MODULE_CACHE["token"] = access_token
    _MODULE_CACHE["expires_at"] = expires_at

    return access_token
