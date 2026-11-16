import logging
import os
import sys
import threading
from datetime import datetime

from .log_masker import masker as shared_masker

# Fixed widths so the ' | ' separators line up from line to line (the source path stays unpadded).
ID_WIDTH = 5  # PID / TID digits, right-aligned; a longer id still prints in full
LEVEL_WIDTH = len("CRITICAL")
TIME_WIDTH = len("0.004")  # seconds: 4 digits and the dot


def to_milliseconds(seconds):
    """Whole milliseconds, cut not rounded: round to microseconds first (so 4.35 stays 4350), then drop."""
    return round(seconds * 1_000_000) // 1000


def format_seconds(milliseconds):
    """Seconds in 4 digits and a dot, extra decimals cut (not rounded): 0.004, 23.54, 123.4, 1234.

    10000 s (2.7 hours) or more prints in full, so that line is wider. Negative values count as 0.
    """
    seconds, rest = divmod(max(0, milliseconds), 1000)
    if seconds < 10:
        return f"{seconds}.{rest:03d}"
    if seconds < 100:
        return f"{seconds}.{rest // 10:02d}"
    if seconds < 1000:
        return f"{seconds}.{rest // 100}"
    return str(seconds)


class LogLineFormatter(logging.Formatter):
    """Builds one log line: the enabled parts joined by ' | ', with the message wrapped in [ ]."""

    def __init__(self, config, masker=shared_masker):
        """Keep the LogConfig so each include_* flag can be checked per line, and the masker for the line."""
        super().__init__()
        self.config = config
        self.masker = masker
        self._previous = None  # (process id, time in ms) of the last line this formatter wrote

    def format(self, record):
        """Return the full log line for one logging call."""
        parts = []
        if self.config.include_timestamp:
            parts.append(datetime.fromtimestamp(record.created).astimezone().isoformat(timespec="milliseconds"))
        if self.config.include_process_id:
            parts.append(f"PID {record.process:>{ID_WIDTH}}")
        if self.config.include_thread_id:
            # Formatting runs in the thread that made the logging call, so this is the caller's OS thread id.
            parts.append(f"TID {threading.get_native_id():>{ID_WIDTH}}")
        if self.config.include_level:
            parts.append(f"{record.levelname:<{LEVEL_WIDTH}}")
        if self.config.include_elapsed:
            parts.append(f"{self._elapsed(record):>{TIME_WIDTH}}")
        if self.config.include_source:
            parts.append(self._find_source(record))

        message = record.getMessage()
        if record.exc_info:
            message += "\n" + self.formatException(record.exc_info)
        if record.stack_info:
            message += "\n" + self.formatStack(record.stack_info)
        parts.append(f"[{message}]")
        # Last step, so the message, traceback and every other part are masked (see LogMasker).
        return self.masker.mask(" | ".join(parts))

    def _elapsed(self, record):
        """Seconds as '0.004': the call's extra={"runtime": seconds}, else the gap since the previous line.

        The gap is measured in whole milliseconds, the same precision as the timestamp column, so it
        matches subtracting the two timestamps. The first line of a process shows 0.000: the line
        before it in the file came from another process (an earlier run) and is ignored.
        """
        now_ms = to_milliseconds(record.created)  # the same milliseconds the timestamp column shows
        previous, self._previous = self._previous, (record.process, now_ms)
        runtime = getattr(record, "runtime", None)
        if isinstance(runtime, (int, float)) and not isinstance(runtime, bool):
            return format_seconds(to_milliseconds(runtime))
        if previous is None or previous[0] != record.process:
            return format_seconds(0)
        # Records are stamped before the handler lock is taken, so two threads can arrive a few
        # microseconds out of order; format_seconds shows that as 0, never as a negative gap.
        return format_seconds(now_ms - previous[1])

    def _find_source(self, record):
        """Return 'module.path.ClassName' of the code that made the logging call."""
        frame = sys._getframe()
        while frame is not None:
            if frame.f_code.co_filename == record.pathname and frame.f_lineno == record.lineno:
                return self._source_from_frame(frame)
            frame = frame.f_back
        return record.name

    def _source_from_frame(self, frame):
        """Combine the frame's dotted module name with its enclosing class name, if any."""
        module = frame.f_globals.get("__name__", "")
        if module == "__main__":
            spec = frame.f_globals.get("__spec__")
            module = spec.name if spec else os.path.splitext(os.path.basename(frame.f_code.co_filename))[0]

        # co_qualname is e.g. "DraftCallbacks.draft_created" or
        # "DraftCallbacks.draft_created.<locals>.helper".
        class_name = frame.f_code.co_qualname.split(".<locals>")[0].rpartition(".")[0]
        return f"{module}.{class_name}" if class_name else module
