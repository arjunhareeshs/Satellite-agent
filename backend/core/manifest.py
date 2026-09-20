"""
Model manifest: real hashes, verified at startup.

config/MANIFEST.json previously listed five models with SHA-256 digests and
`local_path` entries for files that did not exist, alongside
`"offline_compliant": true`. Nothing in the codebase read the file, so nothing
caught it.

This module is what makes the manifest mean something. `build_manifest` writes
digests computed from bytes on disk; `verify_manifest` recomputes them and
reports drift. The FastAPI app calls `verify_manifest` at startup, so a missing
or altered weight file surfaces as a health-check failure rather than as
silently wrong embeddings.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
MANIFEST_PATH = os.path.join(ROOT, "config", "MANIFEST.json")


def sha256_file(path: str, chunk_size: int = 1 << 20) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(chunk_size), b""):
            h.update(chunk)
    return h.hexdigest()


def manifest_hash(entries: List[Dict[str, Any]]) -> str:
    """
    A digest over the component digests.

    Derived from the per-model hashes rather than chosen, so it changes if and
    only if a weight file changes. This is the value shown in the UI's
    provenance block and exported with every GeoJSON result.
    """
    payload = json.dumps(
        [
            {"name": e.get("name"), "sha256": e.get("sha256")}
            for e in sorted(entries, key=lambda e: str(e.get("name")))
        ],
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


@dataclass
class VerificationResult:
    ok: bool
    checked: int = 0
    missing: List[str] = field(default_factory=list)
    mismatched: List[str] = field(default_factory=list)
    unhashed: List[str] = field(default_factory=list)
    manifest_hash_ok: bool = True
    message: str = ""

    def as_dict(self) -> Dict[str, Any]:
        return {
            "ok": self.ok,
            "checked": self.checked,
            "missing": self.missing,
            "mismatched": self.mismatched,
            "unhashed": self.unhashed,
            "manifest_hash_ok": self.manifest_hash_ok,
            "message": self.message,
        }


def load_manifest(path: Optional[str] = None) -> Dict[str, Any]:
    with open(path or MANIFEST_PATH, "r", encoding="utf-8") as fh:
        return json.load(fh)


def save_manifest(manifest: Dict[str, Any], path: Optional[str] = None) -> str:
    target = path or MANIFEST_PATH
    with open(target, "w", encoding="utf-8") as fh:
        json.dump(manifest, fh, indent=2)
    return target


def _resolve(local_path: str) -> str:
    return local_path if os.path.isabs(local_path) else os.path.join(ROOT, local_path)


def verify_manifest(path: Optional[str] = None, strict: bool = False) -> VerificationResult:
    """
    Recompute every digest in the manifest against the files on disk.

    `strict` makes an incomplete manifest a failure. The default is lenient so
    the API can start and report degraded status rather than refusing to boot on
    a machine where the weights have not been staged yet.
    """
    try:
        manifest = load_manifest(path)
    except (OSError, ValueError) as exc:
        return VerificationResult(ok=False, message="cannot read manifest: %s" % exc)

    entries: List[Dict[str, Any]] = list(manifest.get("models", []))
    frozen = manifest.get("frozen_components", {})
    for name, comp in frozen.items():
        entry = dict(comp)
        entry.setdefault("name", name)
        entries.append(entry)

    result = VerificationResult(ok=True)

    for entry in entries:
        name = str(entry.get("name", "<unnamed>"))
        local_path = entry.get("local_path") or entry.get("path")
        if not local_path:
            result.unhashed.append(name)
            continue

        resolved = _resolve(local_path)
        if not os.path.exists(resolved):
            result.missing.append("%s (%s)" % (name, local_path))
            continue

        recorded = entry.get("sha256")
        if not recorded:
            result.unhashed.append(name)
            continue

        actual = sha256_file(resolved)
        result.checked += 1
        if actual != recorded:
            result.mismatched.append(
                "%s: recorded %s... actual %s..." % (name, recorded[:12], actual[:12])
            )

    recorded_manifest_hash = manifest.get("manifest_hash")
    if recorded_manifest_hash:
        result.manifest_hash_ok = recorded_manifest_hash == manifest_hash(entries)

    problems = []
    if result.missing:
        problems.append("%d missing" % len(result.missing))
    if result.mismatched:
        problems.append("%d checksum mismatch" % len(result.mismatched))
    if not result.manifest_hash_ok:
        problems.append("manifest_hash stale")
    if strict and result.unhashed:
        problems.append("%d unhashed" % len(result.unhashed))

    if problems:
        result.ok = False
        result.message = "; ".join(problems)
    else:
        result.message = "%d artifact(s) verified" % result.checked

    return result


def build_manifest(
    models: List[Dict[str, Any]],
    frozen_components: Optional[Dict[str, Dict[str, Any]]] = None,
    base: Optional[Dict[str, Any]] = None,
    path: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Write a manifest whose digests come from files that actually exist.

    Each entry needs `name` and `local_path`; the digest and size are filled in
    here. An entry whose file is absent is kept but marked, so the manifest
    records what is staged rather than asserting compliance it cannot support.
    """
    base = base or {}
    frozen_components = frozen_components or {}

    def _fill(entry: Dict[str, Any]) -> Dict[str, Any]:
        out = dict(entry)
        local_path = out.get("local_path") or out.get("path")
        resolved = _resolve(local_path) if local_path else None
        if resolved and os.path.exists(resolved):
            out["sha256"] = sha256_file(resolved)
            out["size_bytes"] = os.path.getsize(resolved)
            out["staged"] = True
        else:
            out["sha256"] = None
            out["staged"] = False
        return out

    filled_models = [_fill(m) for m in models]
    filled_frozen = {k: _fill(v) for k, v in frozen_components.items()}

    all_entries = filled_models + [
        dict(v, name=v.get("name", k)) for k, v in filled_frozen.items()
    ]
    staged = [e for e in all_entries if e.get("staged")]

    manifest = dict(base)
    manifest.update(
        {
            "system_name": base.get("system_name", "TRINETRA"),
            "version": base.get("version", "1.0.0"),
            "evaluation_context": base.get(
                "evaluation_context", "SIH26227 - Ministry of Defence (Indian Army, DGIS)"
            ),
            "created_at": dt.datetime.now(dt.timezone.utc).isoformat(),
            # Honest: true only when every declared artifact is present locally.
            "offline_compliant": len(staged) == len(all_entries) and bool(all_entries),
            "artifacts_staged": len(staged),
            "artifacts_declared": len(all_entries),
            "manifest_hash": manifest_hash(all_entries),
            "models": filled_models,
            "frozen_components": filled_frozen,
        }
    )

    save_manifest(manifest, path)
    return manifest


if __name__ == "__main__":
    res = verify_manifest()
    print("manifest verification: %s" % ("OK" if res.ok else "FAILED"))
    print("  %s" % res.message)
    for label, items in (
        ("missing", res.missing),
        ("mismatched", res.mismatched),
        ("unhashed", res.unhashed),
    ):
        for item in items:
            print("  %-12s %s" % (label, item))
    raise SystemExit(0 if res.ok else 1)
