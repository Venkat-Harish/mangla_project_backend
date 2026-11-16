import contextlib
import logging
import os
import re
import sys
from datetime import datetime

from .log_masker import masker


class RolloverFileHandler(logging.Handler):
    """Appends lines to <prefix>_<timestamp>.log and starts a new file when the max size would be exceeded."""

    def __init__(self, config):
        """Create the log folder and continue the newest log file if it still has room."""
        super().__init__()
        self.config = config
        os.makedirs(config.log_directory, exist_ok=True)
        self.current_path = self._find_latest_file() or self._new_file_path()

    def emit(self, record):
        """Write one formatted line, rolling over to a new file first if this line would not fit.

        A failed write (full disk, lost file share) goes to handleError like in any logging handler,
        so it never reaches the code that logged; that line is missing from the file.
        """
        try:
            data = (self.format(record) + "\n").encode("utf-8")
            if os.path.exists(self.current_path):
                size = os.path.getsize(self.current_path)
                if size > 0 and size + len(data) > self.config.max_file_bytes:
                    self.current_path = self._new_file_path()
            with open(self.current_path, "ab") as file:
                file.write(data)
        except Exception:
            self.handleError(record)

    def handleError(self, record):
        """Report a failed write as one masked line on stderr; never raises.

        logging's own handleError also prints the record's raw message and arguments, which are not
        masked (ER numbers would reach the console log). Like it, this is silent when
        logging.raiseExceptions is False.
        """
        if not (logging.raiseExceptions and sys.stderr):
            return
        error = sys.exception()
        with contextlib.suppress(Exception):  # a failure here has nowhere left to be reported
            sys.stderr.write(masker.mask(
                f"--- Logging error: {type(error).__name__}: {error} "
                f"(logged from {record.filename}, line {record.lineno})"
            ) + "\n")

    def _new_file_path(self):
        """Return a path for a fresh log file named with the current local time."""
        stamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S_%f")
        return os.path.join(self.config.log_directory, f"{self.config.log_file_prefix}_{stamp}.log")

    def _find_latest_file(self):
        """Return the newest existing log file for this prefix if it is under the max size, else None."""
        pattern = re.compile(
            re.escape(self.config.log_file_prefix) + r"_\d{4}-\d{2}-\d{2}_\d{2}-\d{2}-\d{2}_\d{6}\.log"
        )
        paths = [
            os.path.join(self.config.log_directory, name)
            for name in os.listdir(self.config.log_directory)
            if pattern.fullmatch(name)
        ]
        if not paths:
            return None
        # Files written within the same clock tick share an mtime; the timestamped name breaks the tie.
        latest = max(paths, key=lambda path: (os.path.getmtime(path), path))
        return latest if os.path.getsize(latest) < self.config.max_file_bytes else None
