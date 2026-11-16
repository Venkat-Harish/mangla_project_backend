"""Database (engine + sessions for db.target) and Repository (every read and write) for the orm models."""

import os
from functools import cache
from pathlib import Path
from urllib.parse import quote_plus

from dotenv import load_dotenv
from sqlalchemy import URL, Engine, create_engine, event
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.sql.expression import Executable

from packages.sql_token import SQL_COPT_SS_ACCESS_TOKEN, TokenCache  # noqa: F401 -- re-exported

ROOT = Path(__file__).resolve().parents[1]
NOI_MODEL_SCHEMA = "NOIDev"  # the schema orm/models/noi are written against (audit.json names audit_dev)
NOI_SCHEMAS = ("dbo", "NOIDev", "NOITest")  # where NOI tables live; settings.noi_schema takes the same


def noi_schema_map() -> dict[str, str]:
    """Where the NOI tables really are: NOI_SCHEMA, the setting 4B reads (src.lib.settings.noi_schema, same
    default dbo). Read from the environment so this module never imports the settings' Azure SDKs.
    A schema outside NOI_SCHEMAS raises here, not as "invalid object name" on the first NOI query."""
    target = os.environ.get("NOI_SCHEMA", "dbo").strip()
    if target not in NOI_SCHEMAS:
        raise RuntimeError(f"NOI_SCHEMA={target!r} is not one of {', '.join(NOI_SCHEMAS)}.")
    return {} if target == NOI_MODEL_SCHEMA else {NOI_MODEL_SCHEMA: target}


@cache
def _credential():
    """Built on first use, so a string that signs itself in never imports azure.identity."""
    from azure.identity import DefaultAzureCredential

    return DefaultAzureCredential(process_timeout=60)  # locally the token comes from `az`, ~16 s


def _signs_itself_in(conn: str) -> bool:
    """True when the string names its own sign-in: Authentication= (ActiveDirectoryMsi on Azure) or
    UID/PWD. Otherwise -- a local Fabric string -- each connection gets an Entra token, as
    src.lib.db does; ActiveDirectoryInteractive would hang inside a Functions host."""
    lowered = conn.lower().replace(" ", "")
    return "authentication=" in lowered or ("uid=" in lowered and "pwd=" in lowered)


_sql_token = TokenCache(lambda: _credential())  # looked up per fetch, so tests can swap it


def _inject_token(dialect, conn_rec, cargs, cparams) -> None:  # noqa: ANN001
    cparams["attrs_before"] = _sql_token.attrs_before()


class Database:
    """Engine and session factory for the database named by db.target; one instance per process."""

    TARGETS = ("local", "fabric_dev", "fabric_prod")

    def __init__(
        self, properties_file: Path = ROOT / "app.properties", env_file: Path = ROOT / ".env"
    ) -> None:
        load_dotenv(env_file, override=False)  # real env vars / App Settings always win over .env
        self.target: str = self._target(properties_file)
        # quote_plus because the pyodbc dialect unquotes odbc_connect, which would mangle '+' and '%'
        conn = self._connection_string()
        url = URL.create("mssql+pyodbc", query={"odbc_connect": quote_plus(conn)})
        # pyodbc's timeout, not a LoginTimeout tag (msodbcsql 18 ignores it); Entra sign-in needs longer
        timeout = 15 if self.target == "local" else 60
        # every NOIDev statement (the NOI models, the audit table) runs against NOI_SCHEMA's tables instead
        options = {"schema_translate_map": noi_schema_map()}
        self.engine: Engine = create_engine(
            url, pool_pre_ping=True, connect_args={"timeout": timeout}, execution_options=options
        )
        if not _signs_itself_in(conn):
            event.listen(self.engine, "do_connect", _inject_token)
        self._sessions = sessionmaker(self.engine, expire_on_commit=False)

    def session(self) -> Session:
        """A new session on the shared engine; use it in a with block."""
        return self._sessions()

    def _target(self, properties_file: Path) -> str:
        """AARC_DB_TARGET, else db.target in the properties file; raises when unset or unknown."""
        raw = os.environ.get("AARC_DB_TARGET") or self._read_properties(properties_file).get("db.target", "")
        target = raw.strip().lower()
        if target not in self.TARGETS:
            raise RuntimeError(
                f"db.target={raw!r} is not one of {', '.join(self.TARGETS)}. "
                f"Set it in {properties_file} or override with AARC_DB_TARGET."
            )
        return target

    def _connection_string(self) -> str:
        """DB_CONN_<TARGET> from the environment or .env, used exactly as written; raises when empty."""
        name = f"DB_CONN_{self.target.upper()}"
        value = os.environ.get(name, "").strip()
        if not value:
            raise RuntimeError(f"{name} is empty or unset, and db.target={self.target!r} selects it.")
        return value

    @staticmethod
    def _read_properties(path: Path) -> dict[str, str]:
        """Parse a flat key=value file; '#' and '!' start comments; a missing file is empty."""
        if not path.is_file():
            return {}
        pairs = (line.strip().partition("=") for line in path.read_text(encoding="utf-8").splitlines())
        return {k.strip(): v.strip().strip("'\"") for k, sep, v in pairs if sep and k[:1] not in "#!"}


class Repository:
    """Every query and every write against the orm models goes through here."""

    def __init__(self, database: Database) -> None:
        self._database = database

    def read(self, statement, params: dict | None = None) -> list:
        """Run a query: one selected entity/column gives models/values, several give rows."""
        with self._database.session() as session:
            result = session.execute(statement, params)
            return list(result.scalars()) if len(result.keys()) == 1 else list(result)

    def write(self, *items) -> int:
        """Add ORM objects and run insert/update/delete statements in order, all-or-nothing.
        Returns the rows the statements changed (added objects are not counted)."""
        changed = 0
        with self._database.session() as session, session.begin():
            added = []
            for item in items:
                if isinstance(item, Executable):
                    changed += max(session.execute(item).rowcount, 0)  # -1: the driver could not tell
                else:
                    session.add(item)
                    session.flush()  # without relationship()s one flush orders tables by class name, not FK
                    added.append(item)
            for obj in added:
                session.refresh(obj)  # load server defaults and trigger-written columns before close
        return changed


database = Database()  # built when the application first imports packages.db
repository = Repository(database)
