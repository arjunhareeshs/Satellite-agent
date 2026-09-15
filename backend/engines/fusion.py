"""
TRINETRA Multi-Sensor Fusion & False-Alarm Suppression Cascade.
Implements the 5-Gate Cascade (Quality, Geometric, Radiometric, Phenological, Dual-Witness)
to suppress seasonal water extent, harvest, and misregistration false alarms.
"""
import math
from typing import Dict, Any, Tuple, List

# Weights for dual-witness sensor fusion
W_OPTICAL = 0.45
W_SAR = 0.35
W_AGREEMENT = 0.20
TAU = 2.0  # Anomaly z-score threshold


def sigmoid(x: float) -> float:
    return 1.0 / (1.0 + math.exp(-max(-20.0, min(20.0, x))))


class SensorFusionEngine:
    def evaluate_gate_cascade(
        self,
        valid_pixel_fraction: float,
        registration_residual_px: float,
        radiometric_offset_applied: bool,
        seasonal_anomaly_z: float,
        sar_anomaly_z: float,
        cloud_context: float = 0.05
    ) -> Dict[str, Any]:
        """
        Executes the 5-Gate false-alarm suppression cascade.
        """
        gates = {}

        # Gate 1: Observation validity
        gates["gate_1_quality"] = {
            "passed": valid_pixel_fraction >= 0.80,
            "metric": f"{valid_pixel_fraction * 100:.1f}% valid",
            "threshold": ">= 80%"
        }

        # Gate 2: Geometric co-registration
        gates["gate_2_geometric"] = {
            "passed": registration_residual_px <= 0.50,
            "metric": f"{registration_residual_px:.2f} px residual",
            "threshold": "<= 0.50 px"
        }

        # Gate 3: Radiometric harmonization
        gates["gate_3_radiometric"] = {
            "passed": radiometric_offset_applied,
            "metric": "Histogram matched to reference" if radiometric_offset_applied else "Raw radiance drift",
            "threshold": "Normalized to baseline"
        }

        # Gate 4: Phenological seasonal baseline
        gates["gate_4_phenological"] = {
            "passed": seasonal_anomaly_z >= TAU,
            "metric": f"z = {seasonal_anomaly_z:.2f} above harmonic baseline",
            "threshold": f">= {TAU:.1f} sigma"
        }

        # Gate 5: Dual-witness sensor agreement
        fusion_score, change_class, evidence = self.fuse_sensors(
            z_optical=seasonal_anomaly_z,
            z_sar=sar_anomaly_z,
            cloud_ctx=cloud_context
        )
        gates["gate_5_dual_witness"] = {
            "passed": sar_anomaly_z >= TAU,
            "metric": f"SAR z = {sar_anomaly_z:.2f}",
            "threshold": "Dual-sensor agreement"
        }

        all_passed = all(g["passed"] for g in gates.values())

        return {
            "all_gates_passed": all_passed,
            "gates": gates,
            "fusion_score": fusion_score,
            "change_class": change_class,
            "evidence_flags": evidence
        }

    def fuse_sensors(
        self,
        z_optical: float,
        z_sar: float,
        cloud_ctx: float = 0.05
    ) -> Tuple[float, str, List[str]]:
        """
        Cross-sensor agreement logic from PRD Section 7.8.
        Optical responds to reflectance; SAR responds to physical structure/roughness.
        """
        agreement = 0.0
        evidence = []
        change_class = "unconfirmed"

        both_fired = (z_optical >= TAU) and (z_sar >= TAU)

        if both_fired:
            agreement = 1.0
            change_class = "structural"
            evidence = ["optical_change", "sar_confirmation", "dual_witness_aligned"]

        elif z_optical >= TAU and z_sar < TAU:
            if cloud_ctx > 0.30:
                agreement = -0.5
                change_class = "cloud_artifact_suspected"
                evidence = ["optical_only", "high_cloud_context", "sar_refutes"]
            else:
                agreement = 0.0
                change_class = "surface_phenological"
                evidence = ["optical_only", "surface_change"]

        elif z_sar >= TAU and z_optical < TAU:
            agreement = 0.3
            change_class = "structural_under_cloud"
            evidence = ["sar_only", "optical_obscured"]

        raw_linear = (W_OPTICAL * z_optical) + (W_SAR * z_sar) + (W_AGREEMENT * agreement * 3.0)
        calibrated_score = float(sigmoid(raw_linear - 2.0))

        return calibrated_score, change_class, evidence


# Global singleton instance
fusion_engine = SensorFusionEngine()
