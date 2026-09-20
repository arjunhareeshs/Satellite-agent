"""
Semantic vector engine — real Qdrant HNSW with two named vectors per point.

The previous implementation connected to Qdrant in `init_client()` and then
never touched `self._client` again: `upsert_entity`, `search_semantic` and
`search_visual` all operated on plain Python dicts, and search was a for-loop
of `np.dot` over four seeded-random vectors. There was no HNSW, no ANN, and no
payload filtering — the "vector database" was decoration.

This version issues real Qdrant queries. Both vectors live on the same point as
named vectors (PRD section 5.3) so either space can be queried independently,
or both and the scores fused, without duplicating payloads:

    visual    768-d  Prithvi-EO-2.0    image-to-image search, trajectories
    semantic  512-d  RemoteCLIP        natural-language retrieval

The in-memory path is retained deliberately, but as a declared fallback rather
than the silent default: unit tests and the demo fixture need to run without a
container, and `/health` reports which path is live so an evaluator can tell.
"""

from __future__ import annotations

import logging
import os
import uuid
from typing import Any, Dict, List, Optional

import numpy as np

logger = logging.getLogger("trinetra.semantic")

QDRANT_HOST = os.getenv("QDRANT_HOST", "localhost")
QDRANT_PORT = int(os.getenv("QDRANT_PORT", "6333"))
COLLECTION_NAME = os.getenv("QDRANT_COLLECTION", "trinetra_entities")

VISUAL_VECTOR = "visual"
SEMANTIC_VECTOR = "semantic"
VISUAL_DIM = 768
SEMANTIC_DIM = 512

# HNSW parameters. m=16 is the PRD's stated build setting; ef=128 at query time
# trades a little latency for recall, which matters more here than raw speed
# because a missed candidate never reaches the analyst at all.
HNSW_M = 16
HNSW_EF_CONSTRUCT = 128
SEARCH_EF = 128

# Payload fields that get an index. Without these, a filtered search degrades to
# a full scan and the spatial prefilter's benefit is thrown away.
INDEXED_PAYLOAD_FIELDS = {
    "entity_type": "keyword",
    "h3_r9": "keyword",
    "change_type": "keyword",
    "first_seen": "keyword",
    "scene_id": "keyword",
    "area_m2": "float",
    "change_confidence": "float",
}


def _normalize(vec: np.ndarray) -> np.ndarray:
    arr = np.asarray(vec, dtype=np.float32).ravel()
    norm = float(np.linalg.norm(arr))
    return arr / norm if norm > 1e-7 else arr


def _point_id(entity_id: str) -> str:
    """
    Qdrant point IDs must be a UUID or an unsigned int, not an arbitrary string.
    A deterministic UUID5 keeps `BLDG_004281` addressable and makes re-ingesting
    the same entity an update rather than a duplicate — which is what PRD
    section 4.7 needs for incremental ingestion.
    """
    return str(uuid.uuid5(uuid.NAMESPACE_URL, "trinetra/entity/%s" % entity_id))


class SemanticEngine:
    def __init__(self) -> None:
        self._client = None
        self._is_connected = False
        # Fallback store, used only when Qdrant is unreachable.
        self._vectors_visual: Dict[str, np.ndarray] = {}
        self._vectors_semantic: Dict[str, np.ndarray] = {}
        self._payloads: Dict[str, Dict[str, Any]] = {}

    # ------------------------------------------------------------------ setup

    def init_client(self, create: bool = False) -> bool:
        try:
            from qdrant_client import QdrantClient

            self._client = QdrantClient(host=QDRANT_HOST, port=QDRANT_PORT, timeout=5.0)
            self._client.get_collections()
            self._is_connected = True
            logger.info("Connected to Qdrant at %s:%s", QDRANT_HOST, QDRANT_PORT)
            if create:
                self.ensure_collection()
            return True
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "Qdrant unavailable (%s). Falling back to the in-memory index; "
                "searches will be exact but unindexed.", exc
            )
            self._is_connected = False
            self._client = None
            return False

    def ensure_collection(self, recreate: bool = False) -> None:
        """Create the collection with two named vectors and payload indexes."""
        if not self._is_connected:
            raise RuntimeError("Qdrant is not connected")

        from qdrant_client.models import Distance, HnswConfigDiff, VectorParams

        exists = self._client.collection_exists(COLLECTION_NAME)
        if exists and recreate:
            self._client.delete_collection(COLLECTION_NAME)
            exists = False

        if not exists:
            self._client.create_collection(
                collection_name=COLLECTION_NAME,
                vectors_config={
                    VISUAL_VECTOR: VectorParams(size=VISUAL_DIM, distance=Distance.COSINE),
                    SEMANTIC_VECTOR: VectorParams(size=SEMANTIC_DIM, distance=Distance.COSINE),
                },
                hnsw_config=HnswConfigDiff(m=HNSW_M, ef_construct=HNSW_EF_CONSTRUCT),
            )
            logger.info("Created Qdrant collection %s", COLLECTION_NAME)

        for field, schema in INDEXED_PAYLOAD_FIELDS.items():
            try:
                self._client.create_payload_index(
                    collection_name=COLLECTION_NAME,
                    field_name=field,
                    field_schema=schema,
                )
            except Exception:  # noqa: BLE001
                # Already indexed. Qdrant has no idempotent create.
                pass

    @property
    def is_connected(self) -> bool:
        return self._is_connected

    def status(self) -> Dict[str, Any]:
        """Reported by /health so the active backend is visible, not assumed."""
        info: Dict[str, Any] = {
            "backend": "qdrant" if self._is_connected else "in_memory",
            "host": "%s:%s" % (QDRANT_HOST, QDRANT_PORT),
            "collection": COLLECTION_NAME,
        }
        if self._is_connected:
            try:
                collection = self._client.get_collection(COLLECTION_NAME)
                info["points_count"] = collection.points_count
                info["vectors"] = sorted(
                    (collection.config.params.vectors or {}).keys()
                )
            except Exception as exc:  # noqa: BLE001
                info["error"] = str(exc)
        else:
            info["points_count"] = len(self._vectors_semantic)
        return info

    def count(self) -> int:
        if self._is_connected:
            try:
                return self._client.get_collection(COLLECTION_NAME).points_count or 0
            except Exception:  # noqa: BLE001
                return 0
        return len(self._vectors_semantic)

    # ------------------------------------------------------------------ write

    def upsert_entity(
        self,
        entity_id: str,
        visual_vec: np.ndarray,
        semantic_vec: np.ndarray,
        payload: Dict[str, Any],
    ) -> None:
        self.upsert_batch([(entity_id, visual_vec, semantic_vec, payload)])

    def upsert_batch(self, records) -> int:
        """
        Upsert many entities at once.

        HNSW supports incremental insert, so this is also the incremental
        ingestion path (PRD section 4.7) — no index rebuild is required for a
        new scene.
        """
        records = list(records)
        if not records:
            return 0

        if self._is_connected:
            from qdrant_client.models import PointStruct

            points = []
            for entity_id, visual, semantic, payload in records:
                points.append(
                    PointStruct(
                        id=_point_id(entity_id),
                        vector={
                            VISUAL_VECTOR: _normalize(visual).tolist(),
                            SEMANTIC_VECTOR: _normalize(semantic).tolist(),
                        },
                        payload={**payload, "entity_id": entity_id},
                    )
                )
            self._client.upsert(collection_name=COLLECTION_NAME, points=points, wait=True)
            return len(points)

        for entity_id, visual, semantic, payload in records:
            self._vectors_visual[entity_id] = _normalize(visual)
            self._vectors_semantic[entity_id] = _normalize(semantic)
            self._payloads[entity_id] = payload
        return len(records)

    # ------------------------------------------------------------------ read

    def get_visual_vector(self, entity_id: str) -> Optional[np.ndarray]:
        """The stored visual embedding, for image-to-image search."""
        if self._is_connected:
            try:
                found = self._client.retrieve(
                    collection_name=COLLECTION_NAME,
                    ids=[_point_id(entity_id)],
                    with_vectors=True,
                )
                if found and found[0].vector:
                    vector = found[0].vector
                    if isinstance(vector, dict):
                        vector = vector.get(VISUAL_VECTOR)
                    return np.asarray(vector, dtype=np.float32) if vector else None
            except Exception as exc:  # noqa: BLE001
                logger.warning("Qdrant retrieve failed for %s: %s", entity_id, exc)
            return None
        return self._vectors_visual.get(entity_id)

    def _search(
        self,
        vector_name: str,
        query_vector: np.ndarray,
        score_field: str,
        candidate_ids: Optional[List[str]],
        limit: int,
    ) -> List[Dict[str, Any]]:
        query = _normalize(query_vector)

        if self._is_connected:
            from qdrant_client.models import (
                FieldCondition,
                Filter,
                MatchAny,
                SearchParams,
            )

            query_filter = None
            if candidate_ids is not None:
                if not candidate_ids:
                    return []
                query_filter = Filter(
                    must=[
                        FieldCondition(
                            key="entity_id", match=MatchAny(any=list(candidate_ids))
                        )
                    ]
                )

            try:
                hits = self._client.search(
                    collection_name=COLLECTION_NAME,
                    query_vector=(vector_name, query.tolist()),
                    query_filter=query_filter,
                    limit=limit,
                    search_params=SearchParams(hnsw_ef=SEARCH_EF),
                    with_payload=True,
                )
            except Exception as exc:  # noqa: BLE001
                logger.warning("Qdrant search failed (%s); using in-memory index", exc)
            else:
                return [
                    {
                        "entity_id": (hit.payload or {}).get("entity_id"),
                        score_field: max(0.0, min(1.0, (float(hit.score) + 1.0) / 2.0)),
                        "raw_cosine": float(hit.score),
                        "payload": hit.payload or {},
                    }
                    for hit in hits
                ]

        store = self._vectors_semantic if vector_name == SEMANTIC_VECTOR else self._vectors_visual
        pool = candidate_ids if candidate_ids is not None else list(store.keys())

        scores = []
        for entity_id in pool:
            vec = store.get(entity_id)
            if vec is None:
                continue
            sim = float(np.dot(query, vec))
            scores.append(
                {
                    "entity_id": entity_id,
                    score_field: max(0.0, min(1.0, (sim + 1.0) / 2.0)),
                    "raw_cosine": sim,
                    "payload": self._payloads.get(entity_id, {}),
                }
            )

        scores.sort(key=lambda item: item[score_field], reverse=True)
        return scores[:limit]

    def search_semantic(
        self,
        query_vector: np.ndarray,
        candidate_ids: Optional[List[str]] = None,
        limit: int = 20,
    ) -> List[Dict[str, Any]]:
        """Natural-language retrieval in the RemoteCLIP 512-d space."""
        return self._search(SEMANTIC_VECTOR, query_vector, "semantic_score",
                            candidate_ids, limit)

    def search_visual(
        self,
        query_vector: np.ndarray,
        limit: int = 10,
        candidate_ids: Optional[List[str]] = None,
    ) -> List[Dict[str, Any]]:
        """Image-to-image retrieval in the Prithvi 768-d space (PRD section 8.5)."""
        return self._search(VISUAL_VECTOR, query_vector, "visual_score",
                            candidate_ids, limit)


semantic_engine = SemanticEngine()
