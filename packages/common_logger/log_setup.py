import logging
import os

from .log_config import LogConfig
from .log_formatter import LogLineFormatter
from .log_handler import RolloverFileHandler
from .log_masker import MaskingFormatter, masker


class LogSetup:
    """One-time setup that masks the root logger's handlers and attaches the rolling file handler."""

    DEFAULT_PROPERTIES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "logger.properties")
    _handler = None

    @classmethod
    def configure(cls, properties_path=None):
        """Read the properties file, mask every root handler, and write each logging call to the log folder.

        With logging_enabled=false no file is written, but the other root handlers (e.g. the console,
        which a container ships to its log store) are still masked.
        """
        config = LogConfig(properties_path or cls.DEFAULT_PROPERTIES)
        root = logging.getLogger()

        # Calling configure() again replaces the old handler instead of writing every line twice.
        if cls._handler is not None:
            root.removeHandler(cls._handler)
            cls._handler.close()
            cls._handler = None

        # Before the logging_enabled check: the code's own masking calls and the console follow this flag too.
        masker.enabled = config.mask_sensitive_data
        cls._mask_other_handlers(root)

        if not config.logging_enabled:
            return

        handler = RolloverFileHandler(config)
        handler.setFormatter(LogLineFormatter(config))
        # The handler level also filters records from child loggers that set their own lower level.
        handler.setLevel(config.log_level)
        root.addHandler(handler)
        root.setLevel(config.log_level)
        cls._handler = handler

    @staticmethod
    def _mask_other_handlers(root):
        """Wrap the formatter of every other root handler (e.g. a console) so its lines are masked too."""
        for other in root.handlers:
            if isinstance(other.formatter, (LogLineFormatter, MaskingFormatter)):
                continue  # our file handler, or already wrapped by an earlier configure()
            other.setFormatter(MaskingFormatter(other.formatter, masker))
