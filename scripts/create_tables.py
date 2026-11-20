"""Create any ORM tables (packages/database/models/) that don't exist in Supabase yet.

Runs Base.metadata.create_all, which also runs the DDL hooked up in packages/database/ddl.py
(functions, triggers, RLS, backfills) for each table it creates.
Run from mangla_backend/:  python -m scripts.create_tables

Safe to re-run: existing tables are left as they are (no columns are changed or dropped).
Everything runs in one transaction.
"""

import sqlalchemy as sa

from packages.database import Base, engine


def main():
    with engine.begin() as conn:
        existing = {name for name in Base.metadata.tables if sa.inspect(conn).has_table(name)}
        Base.metadata.create_all(conn, checkfirst=True)
    for name in sorted(Base.metadata.tables):
        print(f"{name:<16} {'exists' if name in existing else 'created'}")


if __name__ == "__main__":
    main()
