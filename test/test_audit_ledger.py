"""
Unit tests for TRINETRA Audit Ledger.
Verifies append-only SHA-256 hash chaining and tamper-evident detection.
"""
import os
import sys
import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from backend.core.audit import AuditLedger


def test_audit_ledger_chain_integrity():
    ledger = AuditLedger()

    # Append 3 events
    e1 = ledger.log_action("analyst_01", "query", query_text="river query")
    e2 = ledger.log_action("analyst_01", "confirm", entity_id="BLDG_004281")
    e3 = ledger.log_action("analyst_02", "export", payload={"format": "geojson"})

    assert e2["prev_hash"] == e1["entry_hash"]
    assert e3["prev_hash"] == e2["entry_hash"]
    assert ledger.verify_integrity() is True


def test_audit_ledger_tamper_detection():
    ledger = AuditLedger()

    e1 = ledger.log_action("analyst_01", "confirm", entity_id="BLDG_004281")
    e2 = ledger.log_action("analyst_01", "reject", entity_id="BLDG_004282")

    assert ledger.verify_integrity() is True

    # Malicious tampering with historic entry
    ledger._entries[0]["action"] = "tampered_action"

    # Integrity verification must now FAIL
    assert ledger.verify_integrity() is False
