"""
Ranking Engine for TRINETRA.
Combines scores from semantic retrieval, visual similarity, temporal change confidence,
spatial proximity, and dual-sensor fusion according to config/ranking.yaml weights.
"""
import os
import yaml
from typing import Dict, Any
from backend.schemas.query import EntityScores

# Default weights if config/ranking.yaml is missing
DEFAULT_WEIGHTS = {
    "semantic": 0.30,
    "visual": 0.20,
    "temporal": 0.25,
    "spatial": 0.15,
    "sensor": 0.10
}


class RankingEngine:
    def __init__(self, config_path: str = "config/ranking.yaml"):
        self.weights = DEFAULT_WEIGHTS.copy()
        if os.path.exists(config_path):
            try:
                with open(config_path, "r", encoding="utf-8") as f:
                    cfg = yaml.safe_load(f)
                    if "weights" in cfg:
                        self.weights.update(cfg["weights"])
            except Exception:
                pass

    def compute_score(
        self,
        semantic_sim: float,
        visual_sim: float,
        temporal_score: float,
        spatial_rel: float,
        sensor_score: float
    ) -> EntityScores:
        """
        Computes composite final score according to the TRINETRA weighting contract.
        """
        final = (
            self.weights["semantic"] * semantic_sim +
            self.weights["visual"] * visual_sim +
            self.weights["temporal"] * temporal_score +
            self.weights["spatial"] * spatial_rel +
            self.weights["sensor"] * sensor_score
        )

        return EntityScores(
            semantic=round(float(semantic_sim), 3),
            visual=round(float(visual_sim), 3),
            temporal=round(float(temporal_score), 3),
            spatial=round(float(spatial_rel), 3),
            sensor=round(float(sensor_score), 3),
            final=round(float(final), 3)
        )


ranking_engine = RankingEngine()
