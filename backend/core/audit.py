"""
Analyst audit ledger for TRINETRA.

Append-only, SHA-256 hash-chained ledger recording queries, analyst confirm /
reject verdicts, and exports. The hash-chain logic here was always correct —
this is the most honest file in the original codebase — but storage was a
plain Python list: `self._entries: List[Dict[str, Any]]`. A tamper-evident
ledger that is wiped by `uvicorn --reload` is not tamper-evident against
anything except the current process's own memory.

This version persists every entry to the `audit_log` table (PostGIS instance,
schema already defined in backend/db/migrations/001_initial_schema.sql) and
rehydrates the in-memory chain from it at startup, so `verify_integrity()`
checks history that actually survived a restart. Persistence is best-effort:
if PostgreSQL is unreachable, the ledger still works in-memory for the current
process — degraded, and it says so in `status()` — because a query workflow
should not hard-fail just because the audit sink is down.
"""

from __future__ import annotations

import hashlib
import json
import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger("trinetra.audit")

GENESIS_HASH = "0" * 64


class AuditLedger:
    def __init__(self, persist: bool = True) -> None:
        self._entries: List[Dict[str, Any]] = []
        self._last_hash: str = GENESIS_HASH
        self._persist = persist
        self._db_available = False

    # ------------------------------------------------------------------ setup

    def load_from_db(self) -> bool:
        """
        Rehydrate the chain from PostgreSQL.

        Called once at application startup. If the table is empty or the
        database is unreachable, the ledger starts at genesis in memory, same
        as before — nothing here changes behaviour on a fresh install.
        """
        if not self._persist:
            return False

        try:
            from psycopg2.extras import RealDictCursor

            from backend.db.session import get_db_connection, is_db_connected

            gen = get_db_connection()
            conn = next(gen)
            try:
                if conn is None:
                    self._db_available = False
                    return False
                with conn.cursor(cursor_factory=RealDictCursor) as cur:
                    cur.execute(
                        "SELECT log_id, occurred_at, actor, action, entity_id, "
                        "query_text, query_plan, payload, prev_hash, entry_hash "
                        "FROM audit_log ORDER BY log_id ASC"
                    )
                    rows = cur.fetchall()
            finally:
                try:
                    next(gen)
                except StopIteration:
                    pass

            self._db_available = is_db_connected()
            if not self._db_available:
                return False

            self._entries = [
                {
                    "log_id": row["log_id"],
                    "occurred_at": row["occurred_at"].isoformat()
                    if hasattr(row["occurred_at"], "isoformat")
                    else row["occurred_at"],
                    "actor": row["actor"],
                    "action": row["action"],
                    "entity_id": row["entity_id"],
                    "query_text": row["query_text"],
                    "query_plan": row["query_plan"],
                    "payload": row["payload"],
                    "prev_hash": row["prev_hash"],
                    "entry_hash": row["entry_hash"],
                }
                for row in rows
            ]
            self._last_hash = self._entries[-1]["entry_hash"] if self._entries else GENESIS_HASH
            logger.info("Audit ledger rehydrated: %d entries from PostgreSQL", len(self._entries))
            return True
        except Exception as exc:  # noqa: BLE001
            logger.warning("Could not load audit ledger from PostgreSQL (%s); starting empty", exc)
            self._db_available = False
            return False

    def status(self) -> Dict[str, Any]:
        return {
            "backend": "postgresql" if self._db_available else "in_memory",
            "entries": len(self._entries),
            "chain_valid": self.verify_integrity(),
        }

    # ------------------------------------------------------------------ write

    def log_action(
        self,
        actor: str,
        action: str,
        entity_id: Optional[str] = None,
        query_text: Optional[str] = None,
        query_plan: Optional[Dict[str, Any]] = None,
        payload: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Append an action to the hash-chained ledger."""
        log_id = len(self._entries) + 1
        occurred_at = datetime.now(timezone.utc).isoformat()

        hash_payload = {
            "log_id": log_id,
            "occurred_at": occurred_at,
            "actor": actor,
            "action": action,
            "entity_id": entity_id,
            "query_text": query_text,
            "query_plan": query_plan,
            "payload": payload,
            "prev_hash": self._last_hash,
        }

        serialized = json.dumps(hash_payload, sort_keys=True, default=str)
        entry_hash = hashlib.sha256(serialized.encode("utf-8")).hexdigest()

        entry = {**hash_payload, "entry_hash": entry_hash}

        self._entries.append(entry)
        self._last_hash = entry_hash

        if self._persist:
            self._write_through(entry)

        return entry

    def _write_through(self, entry: Dict[str, Any]) -> None:
        """
        Best-effort persistence of one entry. Failure here does not roll back
        the in-memory append: the analyst's action already happened and the
        response has already gone out. What it does is flip `status()` to
        report the degraded backend, so an evaluator can see the ledger is not
        currently durable rather than silently trusting it.
        """
        try:
            import psycopg2.extras

            from backend.db.session import get_db_connection

            gen = get_db_connection()
            conn = next(gen)
            try:
                if conn is None:
                    self._db_available = False
                    return
                with conn.cursor() as cur:
                    cur.execute(
                        "INSERT INTO audit_log "
                        "(log_id, occurred_at, actor, action, entity_id, query_text, "
                        " query_plan, payload, prev_hash, entry_hash) "
                        "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s) "
                        "ON CONFLICT (log_id) DO NOTHING",
                        (
                            entry["log_id"],
                            entry["occurred_at"],
                            entry["actor"],
                            entry["action"],
                            entry["entity_id"],
                            entry["query_text"],
                            psycopg2.extras.Json(entry["query_plan"])
                            if entry["query_plan"] is not None
                            else None,
                            psycopg2.extras.Json(entry["payload"])
                            if entry["payload"] is not None
                            else None,
                            entry["prev_hash"],
                            entry["entry_hash"],
                        ),
                    )
                conn.commit()
                self._db_available = True
            finally:
                try:
                    next(gen)
                except StopIteration:
                    pass
        except Exception as exc:  # noqa: BLE001
            logger.warning("Audit ledger write-through failed (%s); entry kept in memory only", exc)
            self._db_available = False

    # ------------------------------------------------------------------ read

    def verify_integrity(self) -> bool:
        """Verify the entire cryptographic hash chain. True if untouched."""
        current_prev = GENESIS_HASH
        for entry in self._entries:
            if entry["prev_hash"] != current_prev:
                return False

            payload = {
                "log_id": entry["log_id"],
                "occurred_at": entry["occurred_at"],
                "actor": entry["actor"],
                "action": entry["action"],
                "entity_id": entry["entity_id"],
                "query_text": entry["query_text"],
                "query_plan": entry["query_plan"],
                "payload": entry["payload"],
                "prev_hash": entry["prev_hash"],
            }
            computed = hashlib.sha256(
                json.dumps(payload, sort_keys=True, default=str).encode("utf-8")
            ).hexdigest()
            if computed != entry["entry_hash"]:
                return False
            current_prev = entry["entry_hash"]

        return True

    def get_entries(self, entity_id: Optional[str] = None) -> List[Dict[str, Any]]:
        if entity_id:
            return [e for e in self._entries if e.get("entity_id") == entity_id]
        return list(self._entries)


audit_ledger = AuditLedger()
