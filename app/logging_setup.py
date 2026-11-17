"""Logging for the API: a console handler plus packages/common_logger's rolling log files, every line
carrying the request ID of the request that wrote it ('-' outside a request).

Modules log with logging.getLogger(__name__) as usual.
"""

import logging

from app.config import Settings
from app.request_id import get_request_id
from packages.common_logger import LogSetup

CONSOLE_FORMAT = "%(asctime)s | %(levelname)-8s | %(request_id)s | %(name)s | %(message)s"

_configured = False


def _install_request_id_factory() -> None:
    """Every LogRecord gets request_id from the current request's ContextVar when it is created, so
    every handler (console, log files, test capture) sees it, whichever logger made the call."""
    previous = logging.getLogRecordFactory()

    def factory(*args, **kwargs) -> logging.LogRecord:
        record = previous(*args, **kwargs)
        record.request_id = get_request_id() or "-"
        return record

    logging.setLogRecordFactory(factory)


def configure_logging(settings: Settings) -> None:
    """Once per process: request ID on every record, console + log files (logger.properties)."""
    global _configured
    if _configured:
        return
    _install_request_id_factory()
    root = logging.getLogger()
    root.setLevel(logging.INFO)  # LogSetup replaces this with log_level when log files are on

    console = logging.StreamHandler()
    console.setFormatter(logging.Formatter(CONSOLE_FORMAT))
    root.addHandler(console)  # before LogSetup.configure, so it masks the console lines too

    LogSetup.configure(str(settings.logger_properties))
    _configured = True
    logging.getLogger(__name__).info(
        "Logging configured: %s, log files per %s", settings.app_name, settings.logger_properties)
