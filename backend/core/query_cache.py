"""
Bounded query result cache, keyed by query_id.

Solves a specific bug: `GET /api/v1/export/{query_id}` ignored `query_id`
entirely and always returned the first 20 entities of the whole archive
(`backend/api/export.py:18`, before this change). The frontend's per-entity
export button and its "export the whole archive" button consequently returned
the same payload.

Every `execute_plan` call registers the entity IDs it ranked, keyed by the
`query_id` it minted. Export then looks those exact IDs back up. An unknown or
expired query_id is a 404, not a silent substitution — the two are different
failure modes and only one of them is honest.

In-process and bounded (LRU-ish via move-to-end), which is enough for a
single-instance deployment; a multi-worker deployment would need this backed by
Redis or the database instead, but that is out of scope for what this fixes.
"""

from __future__ import annotations

import threading
import time
from collections import OrderedDict
from typing import Any, Dict, List, Optional

MAX_ENTRIES = 500
TTL_SECONDS = 3600  # an export link is meaningful for the session that made it


class QueryResultCache:
    def __init__(self, max_entries: int = MAX_ENTRIES, ttl_seconds: int = TTL_SECONDS) -> None:
        self._max_entries = max_entries
        self._ttl = ttl_seconds
        self._lock = threading.Lock()
        self._store: "OrderedDict[str, Dict[str, Any]]" = OrderedDict()

    def register(self, query_id: str, query_text: str, entity_ids: List[str]) -> None:
        with self._lock:
            self._store[query_id] = {
                "query_text": query_text,
                "entity_ids": list(entity_ids),
                "created_at": time.time(),
            }
            self._store.move_to_end(query_id)
            while len(self._store) > self._max_entries:
                self._store.popitem(last=False)

    def get(self, query_id: str) -> Optional[Dict[str, Any]]:
        with self._lock:
            entry = self._store.get(query_id)
            if entry is None:
                return None
            if time.time() - entry["created_at"] > self._ttl:
                del self._store[query_id]
                return None
            self._store.move_to_end(query_id)
            return entry


query_result_cache = QueryResultCache()
