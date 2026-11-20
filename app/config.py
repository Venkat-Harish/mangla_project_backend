"""Settings from app.properties (the backend root). Secrets stay in .env.

An environment variable MANGLA_<KEY> overrides a key, with the key upper-cased and '.' as '_'
(audit.background -> MANGLA_AUDIT_BACKGROUND). Azure app settings set these: names there can't
contain dots, and the prefix keeps them apart from the platform's own variables.
"""

import os
from dataclasses import dataclass
from functools import cache
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PROPERTIES_FILE = ROOT / "app.properties"
ENV_PREFIX = "MANGLA_"


def env_name(key: str) -> str:
    """The environment variable that overrides key: audit.background -> MANGLA_AUDIT_BACKGROUND."""
    return ENV_PREFIX + key.upper().replace(".", "_")


def read_properties(path: Path) -> dict[str, str]:
    """Parse a flat key=value file; '#' and '!' start comment lines; a missing file is empty."""
    if not path.is_file():
        return {}
    values = {}
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        key, sep, value = line.strip().partition("=")
        if sep and key[:1] not in "#!":
            values[key.strip()] = value.strip().strip("'\"")
    return values


@dataclass(frozen=True)
class Settings:
    app_name: str
    app_version: str
    api_prefix: str
    server_host: str
    server_port: int
    server_reload: bool
    cors_allow_origins: tuple[str, ...]
    request_id_header: str
    logger_properties: Path
    audit_enabled: bool
    audit_background: bool
    audit_max_pending: int
    audit_flush_timeout_seconds: float
    storage_signed_url_seconds: int
    review_allowed_order_statuses: frozenset[str]  # casefolded


@cache
def get_settings(path: Path = PROPERTIES_FILE) -> Settings:
    """The settings, read once per process: MANGLA_<KEY> environment variables, then the file,
    then the defaults."""
    p = read_properties(path)

    def get(key: str, default: str) -> str:
        value = os.environ.get(env_name(key))
        return value.strip() if value is not None else p.get(key, default)

    prefix = "/" + get("api.prefix", "/app").strip("/")
    origins = tuple(o.strip() for o in get("cors.allow_origins", "*").split(",") if o.strip())
    logger_properties = Path(get("logger.properties", "logger.properties"))
    return Settings(
        app_name=get("app.name", "Mangla Backend"),
        app_version=get("app.version", "0.1.0"),
        api_prefix="" if prefix == "/" else prefix,
        server_host=get("server.host", "0.0.0.0"),
        server_port=int(get("server.port", "8000")),
        server_reload=get("server.reload", "false").lower() == "true",
        cors_allow_origins=origins,
        request_id_header=get("request_id.header", "X-Request-ID"),
        logger_properties=logger_properties if logger_properties.is_absolute()
        else path.parent / logger_properties,
        audit_enabled=get("audit.enabled", "true").lower() == "true",
        audit_background=get("audit.background", "true").lower() == "true",
        audit_max_pending=int(get("audit.max_pending", "10000")),
        audit_flush_timeout_seconds=float(get("audit.flush_timeout_seconds", "10")),
        storage_signed_url_seconds=int(get("storage.signed_url_seconds", "3600")),
        review_allowed_order_statuses=frozenset(
            s.strip().casefold()
            for s in get("review.allowed_order_statuses", "delivered,completed").split(",")
            if s.strip()
        ),
    )
