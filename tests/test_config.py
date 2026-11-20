"""app.config: MANGLA_<KEY> environment variables override app.properties.

Needs no database: run alone with  python -m pytest tests/test_config.py --noconftest -q
"""

from pathlib import Path

import pytest

from app.config import env_name, get_settings

PROPERTIES = """\
audit.background=true
review.allowed_order_statuses=delivered
logger.properties=logger.properties
"""


@pytest.fixture
def properties(tmp_path: Path) -> Path:
    """A fresh properties file per test: get_settings is cached per path."""
    path = tmp_path / "app.properties"
    path.write_text(PROPERTIES, encoding="utf-8")
    return path


@pytest.fixture(autouse=True)
def no_overrides(monkeypatch):
    for key in ("audit.background", "review.allowed_order_statuses", "logger.properties"):
        monkeypatch.delenv(env_name(key), raising=False)


def test_env_name():
    assert env_name("audit.background") == "MANGLA_AUDIT_BACKGROUND"
    assert env_name("review.allowed_order_statuses") == "MANGLA_REVIEW_ALLOWED_ORDER_STATUSES"


def test_file_values_without_overrides(properties):
    settings = get_settings(properties)
    assert settings.audit_background is True
    assert settings.review_allowed_order_statuses == frozenset({"delivered"})
    assert settings.logger_properties == properties.parent / "logger.properties"


def test_environment_overrides_file(properties, monkeypatch):
    monkeypatch.setenv("MANGLA_AUDIT_BACKGROUND", "false")
    monkeypatch.setenv("MANGLA_REVIEW_ALLOWED_ORDER_STATUSES", " Done , completed ")
    monkeypatch.setenv("MANGLA_LOGGER_PROPERTIES", "logger.cloud.properties")
    settings = get_settings(properties)
    assert settings.audit_background is False
    assert settings.review_allowed_order_statuses == frozenset({"done", "completed"})
    assert settings.logger_properties == properties.parent / "logger.cloud.properties"


def test_environment_overrides_default(tmp_path, monkeypatch):
    path = tmp_path / "app.properties"
    path.write_text("", encoding="utf-8")
    monkeypatch.setenv("MANGLA_API_PREFIX", "/v1/")
    assert get_settings(path).api_prefix == "/v1"
