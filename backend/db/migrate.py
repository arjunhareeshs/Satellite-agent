"""
Run every migration in backend/db/migrations/ against the active PostgreSQL
connection, in filename order.

docker-compose mounts this directory as `/docker-entrypoint-initdb.d`, which
Postgres only executes on a *fresh* volume. That leaves no path for applying a
migration to a database that already exists -- which is exactly the situation
after adding 002_entity_relation_columns.sql to a volume created under 001.
This module is that path.

Every migration here is written with `IF NOT EXISTS` / `ADD COLUMN IF NOT
EXISTS`, so re-running the full set is always safe; there is no migration
ledger to maintain.
"""

from __future__ import annotations

import glob
import os

MIGRATIONS_DIR = os.path.dirname(os.path.abspath(__file__))
MIGRATIONS_DIR = os.path.join(MIGRATIONS_DIR, "migrations")


def migration_files():
    return sorted(glob.glob(os.path.join(MIGRATIONS_DIR, "*.sql")))


def run_migrations(conn) -> list:
    """Apply every .sql file in order. Returns the list of files applied."""
    applied = []
    for path in migration_files():
        with open(path, "r", encoding="utf-8") as fh:
            sql = fh.read()
        with conn.cursor() as cur:
            cur.execute(sql)
        conn.commit()
        applied.append(os.path.basename(path))
    return applied


if __name__ == "__main__":
    from backend.db.session import get_db_connection, init_db_pool, is_db_connected

    init_db_pool()
    if not is_db_connected():
        raise SystemExit("PostgreSQL is not reachable. Start it with 'make up' first.")

    gen = get_db_connection()
    connection = next(gen)
    try:
        files = run_migrations(connection)
        print("Applied %d migration(s):" % len(files))
        for name in files:
            print("  %s" % name)
    finally:
        try:
            next(gen)
        except StopIteration:
            pass
