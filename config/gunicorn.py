"""Gunicorn configuration file."""

import os

# "-" routes access logs to stdout via the gunicorn.access stdlib logger,
# which is picked up by the structlog pipeline configured in on_starting().
# Without this, gunicorn suppresses access logs entirely regardless of logger config.
accesslog = "-"


def on_starting(server):
    """Configure structlog in the master process.

    Django's LOGGING setting is only applied when the WSGI app loads inside a
    worker, so the master process (which emits signal/lifecycle log lines) never
    sees it. We replicate the same setup here so all gunicorn logs flow through
    the structlog pipeline.
    """
    # Deferred import: config.logging_config imports structlog, which is a
    # non-trivial import. Deferring it to on_starting keeps module-level gunicorn
    # config evaluation fast and avoids importing before the venv is fully active.
    from config.logging_config import apply_logging

    debug = os.environ.get("DEBUG", "").lower() in ("1", "true", "yes")
    apply_logging(debug)
