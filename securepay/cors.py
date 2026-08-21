from django.conf import settings
from django.http import HttpResponse


class SimpleCORSMiddleware:
    """Minimal CORS middleware for local development origins."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        origin = request.headers.get("Origin")
        is_allowed_origin = origin in getattr(settings, "CORS_ALLOWED_ORIGINS", [])
        public_paths = getattr(settings, "CORS_PUBLIC_ALLOW_ALL_PATH_PREFIXES", [])
        allow_all_for_path = any(request.path.startswith(prefix) for prefix in public_paths)

        if request.method == "OPTIONS":
            response = HttpResponse(status=204)
        else:
            response = self.get_response(request)

        if allow_all_for_path:
            response["Access-Control-Allow-Origin"] = "*"
            response["Access-Control-Allow-Methods"] = "GET, POST, PUT, PATCH, DELETE, OPTIONS"
            response["Access-Control-Allow-Headers"] = "Authorization, Content-Type, X-Requested-With"
        elif is_allowed_origin:
            response["Access-Control-Allow-Origin"] = origin
            response["Vary"] = "Origin"
            response["Access-Control-Allow-Credentials"] = "true"
            response["Access-Control-Allow-Methods"] = "GET, POST, PUT, PATCH, DELETE, OPTIONS"
            response["Access-Control-Allow-Headers"] = "Authorization, Content-Type, X-Requested-With"

        return response
