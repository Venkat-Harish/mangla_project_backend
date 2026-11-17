"""Load audit.json and build the in-memory step name -> table name map.

audit.json maps each audit table to its settings:

    {"orders_audit": {"stepNameList": ["orderPlace", "orderCancel"], "auditflag": true,
                      "rollingSize": 10000, "schema": "public"}}

- stepNameList: the step names the calling code passes for that table (may be empty until the code
  is wired). A step belongs to one table only, so the step name alone picks the table. Callers pass
  the exact spelling; names that differ only in case are refused, so two steps never look alike.
- auditflag: false turns the table off; its steps are known but nothing is written.
- rollingSize: optional, default 10000; the most rows the table keeps. Past it the oldest whole
  requests are deleted.
- schema: optional, default public.

Table and schema names must be plain lowercase Postgres identifiers (letters, digits, underscores,
not starting with a digit, at most 63 characters), so they match the unquoted names the tables were
created with (scripts/create_audit_tables.py).
"""

import json
import re
from dataclasses import dataclass
from functools import cache
from pathlib import Path

DEFAULT_CONFIG_FILE = Path(__file__).resolve().with_name("audit.json")
DEFAULT_SCHEMA = "public"
DEFAULT_ROLLING_SIZE = 10000
SQL_NAME_MAX_LENGTH = 63  # Postgres truncates longer identifiers (NAMEDATALEN - 1)
_TABLE_KEYS = {"_comment", "stepNameList", "auditflag", "rollingSize", "schema"}
# Lowercase only: Postgres folds unquoted names to lowercase, and SQLAlchemy quotes a name with capitals,
# so "OrdersAudit" would point at a different table than the unquoted orders_audit.
_SQL_NAME = re.compile(r"[a-z_][a-z0-9_]*", re.ASCII)  # used with fullmatch: "$" would accept a final newline


class AuditConfigError(Exception):
    """Raised when audit.json is missing or holds something unusable."""


@dataclass(frozen=True)
class TableSettings:
    """One audit table from audit.json.

    Attributes:
        name: the table name (the audit.json key).
        schema: the schema that holds it.
        step_names: its stepNameList.
        audit_flag: its auditflag; False = write nothing for its steps.
        rolling_size: its rollingSize, the most rows kept.
    """

    name: str
    schema: str
    step_names: tuple[str, ...]
    audit_flag: bool
    rolling_size: int


@dataclass(frozen=True)
class AuditConfig:
    """The loaded audit.json.

    Attributes:
        tables: table name -> its settings.
        step_to_table: step name -> the table it is audited in.
    """

    tables: dict[str, TableSettings]
    step_to_table: dict[str, str]

    def table_for(self, step_name: str) -> TableSettings | None:
        """The settings of the table that audits this step, or None for an unknown step."""
        name = self.step_to_table.get(step_name) if isinstance(step_name, str) else None
        return self.tables[name] if name else None


def load_audit_config(path: Path | str | None = None) -> AuditConfig:
    """Read and check audit.json (cached per file).

    Args:
        path: the config file, or None for the audit.json next to this module.

    Returns:
        The AuditConfig.

    Raises:
        AuditConfigError: if the file is missing, is not valid JSON, or breaks a rule.
    """
    return _load(Path(path or DEFAULT_CONFIG_FILE).resolve())


@cache
def _load(path: Path) -> AuditConfig:
    """load_audit_config for one resolved path (an error is not cached)."""
    problem = ""
    try:
        data = json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=_reject_duplicate_keys)
    except FileNotFoundError:
        problem = f"Audit config file not found: {path}"
    except AuditConfigError as exc:
        problem = f"{path.name}: {exc}"
    except (OSError, ValueError) as exc:
        problem = f"Could not read the audit config file {path.name}: {exc}"
    if problem:
        raise AuditConfigError(problem)
    return _check_config(data, path.name)


def _reject_duplicate_keys(pairs: list[tuple]) -> dict:
    """json object_pairs_hook: json.loads would silently keep only the last of two equal keys."""
    keys = [key for key, _value in pairs]
    duplicates = sorted({key for key in keys if keys.count(key) > 1})
    if duplicates:
        raise AuditConfigError(f"{duplicates} listed more than once")
    return dict(pairs)


def _check_config(data, name: str) -> AuditConfig:
    """Validate the parsed JSON and build the AuditConfig."""
    def fail(message: str):
        raise AuditConfigError(f"{name}: {message}")

    if not isinstance(data, dict):
        fail("must be a JSON object of table name -> settings")
    tables: dict[str, TableSettings] = {}
    step_to_table: dict[str, str] = {}
    seen_steps: dict[str, str] = {}  # step casefolded -> table
    for table, raw in data.items():
        if table == "_comment":
            continue
        if not _is_sql_name(table):
            fail(f"table name {table!r} is not a plain lowercase Postgres identifier "
                 f"(a-z, 0-9, _; at most {SQL_NAME_MAX_LENGTH} characters)")
        if not isinstance(raw, dict):
            fail(f"{table} must be an object with stepNameList and auditflag")
        unknown = set(raw) - _TABLE_KEYS
        if unknown:
            fail(f"{table} has unknown key(s) {sorted(unknown)}; "
                 f"allowed: {sorted(_TABLE_KEYS - {'_comment'})}")

        steps, flag = raw.get("stepNameList"), raw.get("auditflag")
        size = raw.get("rollingSize", DEFAULT_ROLLING_SIZE)
        schema = raw.get("schema", DEFAULT_SCHEMA)
        if not isinstance(steps, list):
            fail(f"{table}.stepNameList must be a list of step names")
        if not isinstance(flag, bool):
            fail(f"{table}.auditflag must be true or false")
        if isinstance(size, bool) or not isinstance(size, int) or size < 1:
            fail(f"{table}.rollingSize must be a whole number of at least 1")
        if not _is_sql_name(schema):
            fail(f"{table}.schema {schema!r} is not a plain lowercase Postgres identifier "
                 f"(a-z, 0-9, _; at most {SQL_NAME_MAX_LENGTH} characters)")

        for step in steps:
            if not isinstance(step, str) or not step.strip() or step != step.strip():
                fail(f"{table}.stepNameList entries must be non-empty text without surrounding spaces")
            key = step.casefold()
            if key in seen_steps:
                fail(f"step {step!r} in {table} is already listed in {seen_steps[key]} (case is ignored)")
            seen_steps[key] = table
            step_to_table[step] = table
        tables[table] = TableSettings(table, schema, tuple(steps), flag, size)

    if not tables:
        fail("lists no audit table")
    return AuditConfig(tables, step_to_table)


def _is_sql_name(name) -> bool:
    """True for a plain lowercase Postgres identifier that needs no quoting, at most 63 characters."""
    return isinstance(name, str) and len(name) <= SQL_NAME_MAX_LENGTH and bool(_SQL_NAME.fullmatch(name))
