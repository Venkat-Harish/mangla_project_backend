"""Settings from app.properties (the backend root). Secrets stay in .env."""

from dataclasses import dataclass
from functools import cache
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PROPERTIES_FILE = ROOT / "app.properties"


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
    """The settings, read once per process."""
    p = read_properties(path)
    prefix = "/" + p.get("api.prefix", "/app").strip("/")
    origins = tuple(o.strip() for o in p.get("cors.allow_origins", "*").split(",") if o.strip())
    logger_properties = Path(p.get("logger.properties", "logger.properties"))
    return Settings(
        app_name=p.get("app.name", "Mangla Backend"),
        app_version=p.get("app.version", "0.1.0"),
        api_prefix="" if prefix == "/" else prefix,
        server_host=p.get("server.host", "0.0.0.0"),
        server_port=int(p.get("server.port", "8000")),
        server_reload=p.get("server.reload", "false").lower() == "true",
        cors_allow_origins=origins,
        request_id_header=p.get("request_id.header", "X-Request-ID"),
        logger_properties=logger_properties if logger_properties.is_absolute()
        else path.parent / logger_properties,
        audit_enabled=p.get("audit.enabled", "true").lower() == "true",
        audit_background=p.get("audit.background", "true").lower() == "true",
        audit_max_pending=int(p.get("audit.max_pending", "10000")),
        audit_flush_timeout_seconds=float(p.get("audit.flush_timeout_seconds", "10")),
        storage_signed_url_seconds=int(p.get("storage.signed_url_seconds", "3600")),
        review_allowed_order_statuses=frozenset(
            s.strip().casefold()
            for s in p.get("review.allowed_order_statuses", "delivered,completed").split(",")
            if s.strip()
        ),
    )
