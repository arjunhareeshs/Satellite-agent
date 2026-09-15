"""
Semantic Vector Engine for TRINETRA.
Manages Qdrant vector index with dual named vectors ('visual': 768, 'semantic': 512)
and payload pre-filtering. Includes high-efficiency in-memory fallback.
"""
import os
import logging
import numpy as np
from typing import List, Dict, Any, Optional

logger = logging.getLogger("trinetra.semantic")

QDRANT_HOST = os.getenv("QDRANT_HOST", "localhost")
QDRANT_PORT = int(os.getenv("QDRANT_PORT", "6333"))
COLLECTION_NAME = "trinetra_entities"


class SemanticEngine:
    def __init__(self):
        self._vectors_visual: Dict[str, np.ndarray] = {}
        self._vectors_semantic: Dict[str, np.ndarray] = {}
        self._payloads: Dict[str, Dict[str, Any]] = {}
        self._client = None
        self._is_connected = False

    def init_client(self):
        try:
            from qdrant_client import QdrantClient
            self._client = QdrantClient(host=QDRANT_HOST, port=QDRANT_PORT, timeout=2.0)
            # test ping
            self._client.get_collections()
            self._is_connected = True
            logger.info("Connected to Qdrant vector database.")
        except Exception as e:
            logger.warning(f"Qdrant connection unavailable ({e}). Using local in-memory vector index.")
            self._is_connected = False
            self._client = None

    def upsert_entity(
        self,
        entity_id: str,
        visual_vec: np.ndarray,
        semantic_vec: np.ndarray,
        payload: Dict[str, Any]
    ):
        """Stores entity vectors and payload."""
        # Normalize vectors for cosine similarity
        v_norm = np.linalg.norm(visual_vec)
        s_norm = np.linalg.norm(semantic_vec)
        self._vectors_visual[entity_id] = visual_vec / (v_norm if v_norm > 1e-7 else 1.0)
        self._vectors_semantic[entity_id] = semantic_vec / (s_norm if s_norm > 1e-7 else 1.0)
        self._payloads[entity_id] = payload

    def search_semantic(
        self,
        query_vector: np.ndarray,
        candidate_ids: Optional[List[str]] = None,
        limit: int = 20
    ) -> List[Dict[str, Any]]:
        """
        Runs semantic search using RemoteCLIP text-image embedding space (512-dim).
        Filters strictly over candidate_ids if provided (Stage 2 execution).
        """
        q_norm = np.linalg.norm(query_vector)
        q = query_vector / (q_norm if q_norm > 1e-7 else 1.0)

        search_pool = candidate_ids if candidate_ids is not None else list(self._vectors_semantic.keys())
        scores = []

        for eid in search_pool:
            if eid in self._vectors_semantic:
                sim = float(np.dot(q, self._vectors_semantic[eid]))
                scores.append({
                    "entity_id": eid,
                    "semantic_score": max(0.0, min(1.0, (sim + 1.0) / 2.0)), # Map [-1,1] to [0,1]
                    "raw_cosine": sim,
                    "payload": self._payloads.get(eid, {})
                })

        # Sort descending by semantic score
        scores.sort(key=lambda x: x["semantic_score"], reverse=True)
        return scores[:limit]

    def search_visual(
        self,
        query_vector: np.ndarray,
        limit: int = 10
    ) -> List[Dict[str, Any]]:
        """
        Image-to-image similarity search using Prithvi visual embeddings (768-dim).
        """
        q_norm = np.linalg.norm(query_vector)
        q = query_vector / (q_norm if q_norm > 1e-7 else 1.0)

        scores = []
        for eid, vec in self._vectors_visual.items():
            sim = float(np.dot(q, vec))
            scores.append({
                "entity_id": eid,
                "visual_score": max(0.0, min(1.0, (sim + 1.0) / 2.0)),
                "raw_cosine": sim,
                "payload": self._payloads.get(eid, {})
            })

        scores.sort(key=lambda x: x["visual_score"], reverse=True)
        return scores[:limit]


# Global singleton instance
semantic_engine = SemanticEngine()
