"""Add users.app_installed (boolean, NOT NULL, default false): true once the user has opened the
installed app (home-screen PWA). Written by /app/account/update-installed; metrics only.

Run from mangla_backend/:  python -m scripts.migrate_users_app_installed
Safe to re-run: ADD COLUMN IF NOT EXISTS skips it when it is already there.
Run it before deploying code that reads users.app_installed.
"""

from sqlalchemy import text

from packages.database import engine


def main():
    with engine.begin() as conn:
        # Fail fast instead of queueing live traffic behind this ALTER's exclusive lock
        conn.execute(text("SET LOCAL lock_timeout = '5s'"))
        conn.execute(text(
            "ALTER TABLE public.users ADD COLUMN IF NOT EXISTS app_installed BOOLEAN DEFAULT false NOT NULL"
        ))
        print("users.app_installed: present")


if __name__ == "__main__":
    main()
