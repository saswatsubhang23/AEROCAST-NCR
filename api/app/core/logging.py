import logging
import logging.config

from app.core.config import Settings


def configure_logging(settings: Settings) -> None:
    logging.config.dictConfig(
        {
            "version": 1,
            "disable_existing_loggers": False,
            "formatters": {
                "default": {"format": "%(asctime)s %(levelname)-7s %(name)s: %(message)s"},
            },
            "handlers": {
                "console": {"class": "logging.StreamHandler", "formatter": "default"},
            },
            "root": {"level": settings.log_level, "handlers": ["console"]},
            # httpx logs full request URLs at INFO; keep them out of normal output.
            "loggers": {"httpx": {"level": "WARNING"}, "httpcore": {"level": "WARNING"}},
        }
    )
