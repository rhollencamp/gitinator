"""Shared structlog configuration used by both Django settings and the gunicorn master process."""

import logging
import logging.config

import structlog


def _get_shared_processors() -> list[structlog.types.Processor]:
    return [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
    ]


def _get_final_processors(debug: bool) -> list[structlog.types.Processor]:
    if debug:
        return [
            structlog.stdlib.ProcessorFormatter.remove_processors_meta,
            structlog.dev.ConsoleRenderer(),
        ]
    return [
        structlog.processors.ExceptionRenderer(),
        structlog.stdlib.ProcessorFormatter.remove_processors_meta,
        structlog.processors.JSONRenderer(),
    ]


def _configure_structlog(shared_processors: list[structlog.types.Processor]) -> None:
    structlog.configure(
        processors=shared_processors
        + [structlog.stdlib.ProcessorFormatter.wrap_for_formatter],
        wrapper_class=structlog.stdlib.BoundLogger,
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )


def build_logging_dict(debug: bool) -> dict:
    """Return a logging.config dictConfig dict wired to structlog."""
    shared_processors = _get_shared_processors()
    _configure_structlog(shared_processors)
    final_processors = _get_final_processors(debug)

    return {
        "version": 1,
        "disable_existing_loggers": False,
        "formatters": {
            "structlog": {
                "()": structlog.stdlib.ProcessorFormatter,
                "processors": final_processors,
                "foreign_pre_chain": shared_processors,
            },
        },
        "handlers": {
            "console": {
                "class": "logging.StreamHandler",
                "formatter": "structlog",
            },
        },
        "root": {
            "handlers": ["console"],
            "level": "WARNING",
        },
        "loggers": {
            "django": {
                "handlers": ["console"],
                "level": "INFO",
                "propagate": False,
            },
            "gitinator": {
                "handlers": ["console"],
                "level": "DEBUG",
                "propagate": False,
            },
            "gunicorn": {
                "handlers": ["console"],
                "level": "INFO",
                "propagate": False,
            },
            "gunicorn.access": {
                "handlers": ["console"],
                "level": "INFO",
                "propagate": False,
            },
            "gunicorn.error": {
                "handlers": ["console"],
                "level": "INFO",
                "propagate": False,
            },
        },
    }


def apply_logging(debug: bool) -> None:
    """Configure stdlib logging + structlog. Safe to call from gunicorn config."""
    logging.config.dictConfig(build_logging_dict(debug))
