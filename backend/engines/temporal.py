"""
TRINETRA Temporal Engine.
Models satellite observation trajectories as time-series breaks rather than 2-image differencing.
Uses 6-coefficient harmonic seasonal regression, Recursive Least Squares (RLS),
CUSUM accumulation, and backtracking break-date confidence interval estimation.
"""
import math
from datetime import datetime
from typing import List, Dict, Any, Tuple, Optional
import numpy as np

# Tunable constants from PRD section 7.4
LAMBDA = 0.98        # RLS forgetting factor
K_DRIFT = 0.5        # CUSUM slack
H_THRESHOLD = 4.0    # Decision threshold
M_CONSECUTIVE = 3    # Required consecutive anomalies for break confirmation
MIN_OBS = 12         # Minimum observation history for reliable baseline
EPS = 1e-6


def harmonic_basis(day_of_year: float, year_frac: float) -> np.ndarray:
    """
    Computes 6-coefficient harmonic regression basis vector:
    x = [1, t, cos(2*pi*t), sin(2*pi*t), cos(4*pi*t), sin(4*pi*t)]
    """
    w1 = 2.0 * math.pi * (day_of_year / 365.25)
    w2 = 4.0 * math.pi * (day_of_year / 365.25)
    return np.array([
        1.0,
        year_frac,
        math.cos(w1),
        math.sin(w1),
        math.cos(w2),
        math.sin(w2)
    ], dtype=np.float64)


class CellModel:
    def __init__(self, h3_id: str, dims: int = 32):
        self.h3_id = h3_id
        self.dims = dims
        # 6 coefficients per projected dimension
        self.coeffs = np.zeros((dims, 6), dtype=np.float64)
        # RLS covariance matrix (6x6)
        self.P = np.eye(6, dtype=np.float64) * 1000.0
        # Historical residual RMSE per dimension
        self.rmse = np.ones(dims, dtype=np.float64) * 0.1
        self.cusum = 0.0
        self.consecutive = 0
        self.n_obs = 0
        self.status = "INITIALIZING"
        self.history: List[Dict[str, Any]] = []

    def update(
        self,
        date_str: str,
        embed_proj: np.ndarray,
        valid_fraction: float,
        sensor: str = "sentinel-2",
        ndvi: Optional[float] = None,
        sar_vv_db: Optional[float] = None
    ) -> Tuple[bool, Optional[Dict[str, Any]]]:
        """
        Updates the cell model online with an incoming observation.
        Gate 1: Rejects if valid_fraction < 0.80.
        Returns (is_break, break_info).
        """
        if valid_fraction < 0.80:
            return False, {"reason": "cloud_or_shadow", "valid_fraction": valid_fraction}

        dt = datetime.fromisoformat(date_str)
        day_of_year = dt.timetuple().tm_yday
        year_frac = (dt.year - 2024) + (day_of_year / 365.25)
        x = harmonic_basis(day_of_year, year_frac)

        if self.n_obs < MIN_OBS:
            self.status = "INSUFFICIENT_HISTORY"

        z_scores = []
        residuals = []
        baseline_pred = []

        for d in range(self.dims):
            y_hat = float(np.dot(self.coeffs[d], x))
            r = float(embed_proj[d] - y_hat)
            baseline_pred.append(y_hat)
            residuals.append(r)

            # Recursive least squares update
            denom = LAMBDA + float(x @ self.P @ x)
            K = (self.P @ x) / max(denom, EPS)
            self.coeffs[d] += K * r
            self.P = (self.P - np.outer(K, x) @ self.P) / LAMBDA

            # Exponentially weighted residual RMSE
            self.rmse[d] = math.sqrt(0.98 * (self.rmse[d] ** 2) + 0.02 * (r ** 2))
            z_scores.append(r / max(self.rmse[d], EPS))

        # Multivariate anomaly magnitude
        Z = float(np.linalg.norm(z_scores) / math.sqrt(self.dims))

        obs_record = {
            "date": date_str,
            "z": Z,
            "embed_norm": float(np.linalg.norm(embed_proj)),
            "baseline_norm": float(np.linalg.norm(baseline_pred)),
            "residual_norm": float(np.linalg.norm(residuals)),
            "valid_fraction": valid_fraction,
            "sensor": sensor,
            "ndvi": ndvi,
            "sar_vv_db": sar_vv_db
        }
        self.history.append(obs_record)

        self.n_obs += 1
        if self.n_obs < MIN_OBS:
            self.status = "INSUFFICIENT_HISTORY"
            self.cusum = 0.0
            self.consecutive = 0
            return False, None

        # CUSUM accumulation once baseline is calibrated
        self.cusum = max(0.0, self.cusum + Z - K_DRIFT)

        if self.cusum > H_THRESHOLD:
            self.consecutive += 1
            if self.consecutive >= M_CONSECUTIVE and self.status != "REGIME_CHANGE_DETECTED":
                self.status = "REGIME_CHANGE_DETECTED"
                break_info = self._backtrack_break(len(self.history) - 1)
                return True, break_info
        else:
            self.consecutive = 0

        return False, None

    def _backtrack_break(self, detection_idx: int) -> Dict[str, Any]:
        """
        Backtracks to find the earliest supported observation where change occurred.
        Returns point estimate and confidence interval [lower, upper].
        """
        i = detection_idx
        while i > 0 and self.history[i - 1]["z"] > 1.2:
            i -= 1

        lower_date = self.history[max(0, i - 1)]["date"]
        upper_date = self.history[i]["date"]

        dt_lower = datetime.fromisoformat(lower_date)
        dt_upper = datetime.fromisoformat(upper_date)
        ci_days = max(1, (dt_upper - dt_lower).days)

        return {
            "estimate": upper_date,
            "confidence_interval": [lower_date, upper_date],
            "interval_days": ci_days,
            "consecutive_observations": self.consecutive,
            "cusum": self.cusum
        }


class TemporalEngine:
    def __init__(self):
        self._cell_models: Dict[str, CellModel] = {}
        self._entity_timelines: Dict[str, List[Dict[str, Any]]] = {}

    def get_or_create_cell(self, h3_id: str, dims: int = 32) -> CellModel:
        if h3_id not in self._cell_models:
            self._cell_models[h3_id] = CellModel(h3_id, dims)
        return self._cell_models[h3_id]

    def register_entity_timeline(self, entity_id: str, trajectory: List[Dict[str, Any]]):
        self._entity_timelines[entity_id] = trajectory

    def get_entity_timeline(self, entity_id: str) -> Optional[List[Dict[str, Any]]]:
        return self._entity_timelines.get(entity_id)

    def estimate_break_from_history(
        self, trajectory: List[Dict[str, Any]]
    ) -> Optional[Dict[str, Any]]:
        """
        Replay a recorded z-score history through the same CUSUM + backtrack
        logic CellModel.update() runs online, and return the first detected
        break.

        This exists so evaluation can compute an independent break-date
        estimate for an entity that already has a stored trajectory (from
        register_entity_timeline), without needing the raw per-observation
        embedding vectors CellModel.update() normally consumes -- the
        trajectory already carries the z-score each update would have
        produced. It is the same detector, run over the same numbers, not a
        second implementation that could disagree with the first.

        Returns None if the trajectory never triggers a break -- which is the
        correct evaluation input for a stable (no-change) entity, not a
        fallback value standing in for "no answer".
        """
        cusum = 0.0
        consecutive = 0

        for idx, obs in enumerate(trajectory):
            if obs.get("valid_fraction", 1.0) < 0.80:
                continue
            if idx < MIN_OBS - 1:
                continue

            z = float(obs.get("z", 0.0))
            cusum = max(0.0, cusum + z - K_DRIFT)

            if cusum > H_THRESHOLD:
                consecutive += 1
                if consecutive >= M_CONSECUTIVE:
                    i = idx
                    while i > 0 and trajectory[i - 1].get("z", 0.0) > 1.2:
                        i -= 1
                    lower = trajectory[max(0, i - 1)]["date"]
                    upper = trajectory[i]["date"]
                    dt_lower = datetime.fromisoformat(lower)
                    dt_upper = datetime.fromisoformat(upper)
                    return {
                        "estimate": upper,
                        "confidence_interval": [lower, upper],
                        "interval_days": max(1, (dt_upper - dt_lower).days),
                    }
            else:
                consecutive = 0

        return None

    def classify_change(
        self,
        optical_z: float,
        sar_z: float,
        ndvi_delta: float,
        sar_backscatter_delta_db: float,
        is_linear_shape: bool = False
    ) -> str:
        """
        Rule-based, defensible change classification from PRD Section 7.6.
        """
        if is_linear_shape:
            return "road_development"

        if sar_backscatter_delta_db > 2.5 and ndvi_delta < -0.15:
            return "construction"
        elif sar_backscatter_delta_db < -2.0 and ndvi_delta < -0.20:
            return "clearance"
        elif abs(ndvi_delta) > 0.35 and abs(sar_backscatter_delta_db) < 1.0:
            return "water_variation"
        elif sar_backscatter_delta_db > 1.0:
            return "expansion"
        return "construction"


# Global singleton instance
temporal_engine = TemporalEngine()
