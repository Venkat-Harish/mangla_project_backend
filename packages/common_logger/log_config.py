import os


class LogConfig:
    """Reads a logger.properties file and exposes each setting as a typed attribute."""

    def __init__(self, properties_path):
        """Load the properties file and convert every setting to its Python type."""
        self.properties_path = os.path.abspath(properties_path)
        self._values = self._read_pairs(self.properties_path)

        self.logging_enabled = self._get_bool("logging_enabled")
        self.log_directory = self._resolve_directory(self._get_str("log_directory", "logs"))
        self.log_file_prefix = self._get_str("log_file_prefix", "app")
        self.max_file_bytes = int(float(self._get_str("max_file_size_mb", "10")) * 1024 * 1024)
        self.log_level = self._get_str("log_level", "INFO").upper()
        self.mask_sensitive_data = self._get_bool("mask_sensitive_data")

        self.include_timestamp = self._get_bool("include_timestamp")
        self.include_process_id = self._get_bool("include_process_id")
        self.include_thread_id = self._get_bool("include_thread_id")
        self.include_level = self._get_bool("include_level")
        self.include_elapsed = self._get_bool("include_elapsed")
        self.include_source = self._get_bool("include_source")
        # Off unless asked for: the record's request_id attribute, which the application's own
        # logging filter sets (e.g. from a per-request ContextVar).
        self.include_request_id = self._get_bool("include_request_id", "false")

    def _read_pairs(self, path):
        """Return every key=value line as a dict, skipping blank lines and # or ! comments."""
        values = {}
        with open(path, encoding="utf-8-sig") as file:
            for line in file:
                line = line.strip()
                if not line or line.startswith(("#", "!")):
                    continue
                key, _, value = line.partition("=")
                values[key.strip()] = value.strip()
        return values

    def _get_str(self, key, default):
        """Return the raw string value for key, or default when the key is missing."""
        return self._values.get(key, default)

    def _get_bool(self, key, default="true"):
        """Return True only when the value is 'true' (any case)."""
        return self._values.get(key, default).lower() == "true"

    def _resolve_directory(self, directory):
        """Expand %VARS% / $VARS and resolve a relative path against the properties file's folder."""
        directory = os.path.expandvars(directory)
        return os.path.abspath(os.path.join(os.path.dirname(self.properties_path), directory))
