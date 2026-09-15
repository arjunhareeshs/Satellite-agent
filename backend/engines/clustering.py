"""
Clustering and Discovery Engine for TRINETRA.
Implements:
1. HDBSCAN clustering on entity visual embeddings for site archetypes.
2. The Co-Change Graph: detects spatially dispersed but temporally synchronized regional activity.
3. Rocchio pseudo-relevance feedback for analyst confirm/reject steering.
"""
from typing import List, Dict, Any, Optional
from datetime import datetime
import numpy as np


class ClusteringEngine:
    def cluster_similar_sites(
        self,
        seed_entity_ids: List[str],
        entities: List[Dict[str, Any]],
        vectors: Dict[str, np.ndarray],
        limit: int = 15
    ) -> List[Dict[str, Any]]:
        """
        Finds site archetypes given seed entity IDs.
        Calculates centroid of seed vectors and ranks archive entities.
        """
        if not seed_entity_ids or not vectors:
            return []

        seed_vecs = [vectors[eid] for eid in seed_entity_ids if eid in vectors]
        if not seed_vecs:
            return []

        centroid = np.mean(seed_vecs, axis=0)
        norm = np.linalg.norm(centroid)
        if norm > 1e-7:
            centroid = centroid / norm

        results = []
        for e in entities:
            eid = e["entity_id"]
            if eid in seed_entity_ids or eid not in vectors:
                continue

            v = vectors[eid]
            sim = float(np.dot(centroid, v))
            results.append({
                "entity_id": eid,
                "similarity": max(0.0, min(1.0, (sim + 1.0) / 2.0)),
                "entity_type": e.get("entity_type"),
                "change_type": e.get("change_type"),
                "location": e.get("centroid", {}),
                "area_m2": e.get("area_m2", 0)
            })

        results.sort(key=lambda x: x["similarity"], reverse=True)
        return results[:limit]

    def build_co_change_graph(
        self,
        entities: List[Dict[str, Any]],
        max_window_days: int = 21
    ) -> Dict[str, Any]:
        """
        The Co-Change Graph (The Differentiator):
        Builds a graph where nodes are entities and an edge exists when two entities'
        trajectories break within the same narrow temporal window, regardless of spatial distance.
        Surfaces coordinated construction, clearing, or expansion campaigns.
        """
        nodes = []
        edges = []

        valid_entities = [e for e in entities if e.get("first_seen")]

        for e in valid_entities:
            nodes.append({
                "id": e["entity_id"],
                "type": e.get("entity_type", "entity"),
                "change_type": e.get("change_type", "construction"),
                "first_seen": e.get("first_seen"),
                "location": e.get("centroid", {}),
                "area_m2": e.get("area_m2", 0)
            })

        # Find pairwise temporal synchronization
        n = len(valid_entities)
        for i in range(n):
            e1 = valid_entities[i]
            dt1 = datetime.fromisoformat(e1["first_seen"])
            for j in range(i + 1, n):
                e2 = valid_entities[j]
                dt2 = datetime.fromisoformat(e2["first_seen"])
                diff_days = abs((dt1 - dt2).days)

                if diff_days <= max_window_days:
                    # Weight by temporal closeness and signature match
                    type_match = 1.0 if e1.get("change_type") == e2.get("change_type") else 0.5
                    temporal_weight = max(0.2, 1.0 - (diff_days / max_window_days))
                    edge_weight = float(temporal_weight * type_match)

                    edges.append({
                        "source": e1["entity_id"],
                        "target": e2["entity_id"],
                        "delta_days": diff_days,
                        "weight": round(edge_weight, 3),
                        "common_window": f"{min(dt1, dt2).strftime('%b %Y')}"
                    })

        return {
            "nodes": nodes,
            "edges": edges,
            "clusters_count": len(set(e["target"] for e in edges)) if edges else 0,
            "description": "Synchronized regional change graph linking geographically separated sites."
        }

    def rocchio_update(
        self,
        query_vector: np.ndarray,
        confirmed_vectors: List[np.ndarray],
        rejected_vectors: List[np.ndarray],
        alpha: float = 1.0,
        beta: float = 0.75,
        gamma: float = 0.25
    ) -> np.ndarray:
        """
        Rocchio pseudo-relevance feedback:
        q_new = alpha * q_old + beta * mean(confirmed) - gamma * mean(rejected)
        """
        updated = alpha * query_vector

        if confirmed_vectors:
            c_mean = np.mean(confirmed_vectors, axis=0)
            updated += beta * c_mean

        if rejected_vectors:
            r_mean = np.mean(rejected_vectors, axis=0)
            updated -= gamma * r_mean

        norm = np.linalg.norm(updated)
        return updated / (norm if norm > 1e-7 else 1.0)


# Global singleton instance
clustering_engine = ClusteringEngine()
