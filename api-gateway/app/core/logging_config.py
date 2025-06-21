# File: app/core/logging_config.py
import logging
import sys
import structlog
from app.core.config import settings

def setup_logging():
    shared_processors = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        structlog.processors.StackInfoRenderer(),
    ]

    if settings.LOG_LEVEL.upper() == "DEBUG":
        shared_processors.append(structlog.processors.CallsiteParameterAdder(
            {
                structlog.processors.CallsiteParameter.FILENAME,
                structlog.processors.CallsiteParameter.LINENO,
            }
        ))

    structlog.configure(
        processors=shared_processors + [
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )

    formatter = structlog.stdlib.ProcessorFormatter(
        processors=[
            structlog.stdlib.ProcessorFormatter.remove_processors_meta,
            structlog.processors.JSONRenderer(),
        ],
    )

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(formatter)
    root_logger = logging.getLogger()

    if not any(isinstance(h, logging.StreamHandler) for h in root_logger.handlers):
        root_logger.addHandler(handler)

    try:
        root_logger.setLevel(settings.LOG_LEVEL.upper())
    except ValueError:
        root_logger.setLevel(logging.INFO)
        logging.warning(f"Invalid LOG_LEVEL '{settings.LOG_LEVEL}'. Defaulting to INFO.")

    # Silenciar librerías verbosas
    logging.getLogger("uvicorn").setLevel(logging.WARNING)
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
    logging.getLogger("gunicorn.error").setLevel(logging.INFO)
    logging.getLogger("gunicorn.access").setLevel(logging.WARNING)
    logging.getLogger("httpx").setLevel(logging.WARNING)

    log = structlog.get_logger("api_gateway.config")
    log.info("Structlog logging configured", log_level=settings.LOG_LEVEL.upper())