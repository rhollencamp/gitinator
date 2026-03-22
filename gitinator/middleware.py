"""Custom Django middleware."""

import uuid

import structlog


class StructlogContextMiddleware:
    """Initialize structlog's context vars for each request.

    Clears any stale context from the previous request, then binds a unique
    request_id (UUID4) so all log calls — including the gunicorn access log
    entry — are correlated. Must be first in MIDDLEWARE so downstream
    middleware and views inherit the request_id.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        structlog.contextvars.clear_contextvars()
        structlog.contextvars.bind_contextvars(request_id=str(uuid.uuid4()))
        return self.get_response(request)
