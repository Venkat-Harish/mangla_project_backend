"""Create the audit tables listed in packages/audit/audit.json in Supabase.

Today: orders_audit, review_audit, home_audit (public schema). Each table has the 5 columns of
packages/audit/audit_store.py's build_audit_table (the same definition the audit writes use),
primary key (request_id, step_name), and Row Level Security enabled with no policies.
Run from mangla_backend/:  python -m scripts.create_audit_tables

Safe to re-run: existing tables are left as they are (no columns are changed or dropped), and
enabling RLS on a table that already has it does nothing. A table added to audit.json later is
created on the next run. Everything runs in one transaction.
"""

import sqlalchemy as sa

from packages.audit.audit_config import load_audit_config
from packages.audit.audit_store import build_audit_table
from packages.database.db import engine


def main():
    config = load_audit_config()
    metadata = sa.MetaData()
    tables = [build_audit_table(s.name, metadata, s.schema) for s in config.tables.values()]
    with engine.begin() as conn:
        existing = {(t.schema, t.name) for t in tables
                    if sa.inspect(conn).has_table(t.name, schema=t.schema)}
        metadata.create_all(conn, checkfirst=True)
        for table in tables:
            conn.execute(sa.text(f"ALTER TABLE {table.schema}.{table.name} ENABLE ROW LEVEL SECURITY"))
            state = "exists" if (table.schema, table.name) in existing else "created"
            print(f"{table.schema}.{table.name:<16} {state}, RLS enabled")


if __name__ == "__main__":
    main()
