"""HTTP Basic authentication middleware and helpers."""

import base64

from django.contrib.auth import authenticate
from django.http import HttpResponse


def _get_basic_auth_user(request):
    """Authenticate a request using HTTP Basic Auth credentials.

    Returns the authenticated User, or None if credentials are absent or invalid.
    """
    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Basic "):
        return None
    try:
        decoded = base64.b64decode(auth_header[6:]).decode("utf-8")
        username, password = decoded.split(":", 1)
    except Exception:
        return None
    return authenticate(request, username=username, password=password)


class BasicAuthMiddleware:
    """Populate request.user from HTTP Basic Auth credentials if present.

    Runs after AuthenticationMiddleware so it only overrides an anonymous user.
    Does not enforce authentication — views are responsible for returning 401.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if not request.user.is_authenticated:
            user = _get_basic_auth_user(request)
            if user is not None:
                request.user = user
        return self.get_response(request)


def unauthorized_response():
    """Return a 401 response that prompts the client for Basic Auth credentials."""
    response = HttpResponse("Unauthorized", status=401)
    response["WWW-Authenticate"] = 'Basic realm="gitinator"'
    return response
