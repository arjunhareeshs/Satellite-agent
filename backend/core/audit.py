"""
Analyst Audit Ledger for TRINETRA.
Append-only, SHA-256 hash-chained ledger recording queries, analyst confirm/reject verdicts,
and exports. Guarantees tamper-evident data provenance for sovereign defense operations.
"""
import json
import hashlib
from datetime import datetime, timezone
from typing import Dict, Any, List, Optional


class AuditLedger:
    def __init__(self):
        self._entries: List[Dict[str, Any]] = []
        self._last_hash: str = "0" * 64

    def log_action(
        self,
        actor: str,
        action: str,
        entity_id: Optional[str] = None,
        query_text: Optional[str] = None,
        query_plan: Optional[Dict[str, Any]] = None,
        payload: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Appends an action to the hash-chained ledger.
        """
        log_id = len(self._entries) + 1
        occurred_at = datetime.now(timezone.utc).isoformat()

        # Construct deterministic hash payload
        hash_payload = {
            "log_id": log_id,
            "occurred_at": occurred_at,
            "actor": actor,
            "action": action,
            "entity_id": entity_id,
            "query_text": query_text,
            "query_plan": query_plan,
            "payload": payload,
            "prev_hash": self._last_hash
        }

        serialized = json.dumps(hash_payload, sort_keys=True)
        entry_hash = hashlib.sha256(serialized.encode("utf-8")).hexdigest()

        entry = {
            **hash_payload,
            "entry_hash": entry_hash
        }

        self._entries.append(entry)
        self._last_hash = entry_hash
        return entry

    def verify_integrity(self) -> bool:
        """
        Verifies the entire cryptographic hash chain. Returns True if untouched.
        """
        current_prev = "0" * 64
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
                "prev_hash": entry["prev_hash"]
            }
            computed = hashlib.sha256(json.dumps(payload, sort_keys=True).encode("utf-8")).hexdigest()
            if computed != entry["entry_hash"]:
                return False
            current_prev = entry["entry_hash"]

        return True

    def get_entries(self, entity_id: Optional[str] = None) -> List[Dict[str, Any]]:
        if entity_id:
            return [e for e in self._entries if e.get("entity_id") == entity_id]
        return list(self._entries)


audit_ledger = AuditLedger()
