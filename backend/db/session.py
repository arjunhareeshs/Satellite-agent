"""
Database session management for TRINETRA.
Supports PostgreSQL 16 + PostGIS 3.4 with fallback to in-memory/sqlite+shapely
for local testing when Docker is inactive.
"""
import os
import json
import logging
from typing import Generator, Any, Optional
import psycopg2
from psycopg2.extras import RealDictCursor
from psycopg2.pool import SimpleConnectionPool

logger = logging.getLogger("trinetra.db")

POSTGRES_HOST = os.getenv("POSTGRES_HOST", "localhost")
POSTGRES_PORT = int(os.getenv("POSTGRES_PORT", "5432"))
POSTGRES_DB = os.getenv("POSTGRES_DB", "trinetra_db")
POSTGRES_USER = os.getenv("POSTGRES_USER", "trinetra")
POSTGRES_PASSWORD = os.getenv("POSTGRES_PASSWORD", "trinetra_secure_password")

_pool: Optional[SimpleConnectionPool] = None
_is_connected: bool = False


def init_db_pool():
    global _pool, _is_connected
    if _pool is not None:
        return
    try:
        _pool = SimpleConnectionPool(
            minconn=1,
            maxconn=10,
            host=POSTGRES_HOST,
            port=POSTGRES_PORT,
            dbname=POSTGRES_DB,
            user=POSTGRES_USER,
            password=POSTGRES_PASSWORD,
            connect_timeout=3
        )
        # Test connection
        conn = _pool.getconn()
        with conn.cursor() as cur:
            cur.execute("SELECT 1;")
        _pool.putconn(conn)
        _is_connected = True
        logger.info("Connected successfully to PostgreSQL + PostGIS.")
    except Exception as e:
        logger.warning(f"PostgreSQL connection failed ({e}). System will use SQLite/in-memory spatial fallback.")
        _is_connected = False
        _pool = None


def is_db_connected() -> bool:
    global _is_connected
    return _is_connected


def get_db_connection():
    global _pool
    if _pool is None:
        init_db_pool()
    if _pool is not None:
        conn = _pool.getconn()
        try:
            yield conn
        finally:
            _pool.putconn(conn)
    else:
        yield None
