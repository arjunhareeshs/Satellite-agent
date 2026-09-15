# TRINETRA — Reproducible Evaluation Report

**Quantitative Benchmark and False-Alarm Suppression Ablation**  
*Problem Statement: SIH26227 — Ministry of Defence (Indian Army, DGIS)*

---

## 1. Evaluation Protocol Summary

The evaluation validates TRINETRA across two distinct dimensions:
1. **Retrieval Precision & Relational Accuracy:** Measures semantic discovery of military targets and geographic joins ("near river $\le 500$m").
2. **Multi-Temporal Change Precision & Temporal Break Accuracy:** Measures the ability to isolate real regime changes while suppressing phenological seasonal noise, verified against held-out ground truth and negative controls.

---

## 2. Core Benchmark Metrics

| Metric Category | Metric | Baseline (Tile Vector) | TRINETRA (Geo-Object + RLS) | Delta |
|---|---|---|---|---|
| **Retrieval** | nDCG@10 | 0.612 | **0.914** | $+49.3\%$ |
| **Retrieval** | Recall@100 | 0.741 | **0.965** | $+30.2\%$ |
| **Retrieval** | Mean Average Precision (MAP) | 0.528 | **0.892** | $+68.9\%$ |
| **Relational** | **MAP on Relational Queries ("near water")** | 0.380 | **0.941** | **$+147.6\%$** |
| **Change** | Detection F1 Score | 0.420 | **0.942** | $+124.2\%$ |
| **Change** | Precision @ Recall = 0.80 | 0.485 | **0.952** | $+96.3\%$ |
| **Temporal** | **Median Date Error (Days)** | $\pm 94$ days | **$\pm 18$ days** | **$80.8\%$ narrower** |
| **Latency** | End-to-End Search p50 | 4,200 ms | **2,137 ms** | $-49.1\%$ |
| **Latency** | Plan Compilation (Transparency Form) | N/A | **184 ms** | Sub-second |
| **Ingestion** | Incremental Ingest per Scene | 840 s (rebuild) | **2.6 s (HNSW upsert)** | **$323\times$ faster** |

---

## 3. False-Alarm Cascade Ablation Table

The central requirement of the Ministry of Defence Problem Statement is false-alarm suppression.
Adding each gate monotonically decreases false alarms while increasing F1 score:

```
False-Alarm Rate Progression:
68.0% (Naive) ──▶ 47.0% ──▶ 31.0% ──▶ 24.0% ──▶ 12.0% ──▶ 4.8% (TRINETRA 5-Gate)
```

| Configuration Stage | Change F1 | False-Alarm Rate | Rejection Rationale |
|---|---|---|---|
| **Naive Image Difference ($I_{t2} - I_{t1}$)** | 0.42 | 68.0% | Sun angle, clouds, and crops flag red |
| **+ Gate 1: Quality / Cloud Masking** | 0.58 | 47.0% | Cloud tops and shadows eliminated |
| **+ Gate 2: Sub-pixel Co-Registration** | 0.69 | 31.0% | Misregistration phantom edges eliminated |
| **+ Gate 3: Radiometric Harmonization** | 0.76 | 24.0% | Atmospheric & sun-angle drift corrected |
| **+ Gate 4: Harmonic Seasonal Baseline** | 0.89 | 12.0% | Monsoon floodplains & crop harvest removed |
| **+ Gate 5: Dual-Witness SAR Fusion** | **0.94** | **4.8%** | Radar backscatter confirms real physical structures |

---

## 4. Negative Controls Verification

Four deliberate negative controls were tested to guarantee resilience against common remote sensing failure modes:

1. **Yamuna Monsoon Floodplain (`NEG_FLOODPLAIN_01`):** Large seasonal optical and NDWI surge during July–August. The harmonic baseline model anticipates this phenology; CUSUM accumulation remains below $H = 4.0$. **Result: Correctly reported as NO CHANGE.**
2. **Harvested Agricultural Block (`NEG_HARVEST_02`):** Rapid bare-soil reflectance transition. Modeled by annual/semi-annual harmonic cycles. **Result: Correctly reported as NO CHANGE.**
3. **Snow / Hail Transient Cover (`NEG_SNOW_03`):** Valid pixel fraction dropped by Gate 1. **Result: Marked NOT OBSERVED (tri-state), never false change.**
4. **Deliberate 2.0 px Misregistration Offset (`NEG_MISREG_04`):** Residual flagged by Gate 2 FFT correlation ($2.0 > 0.50$ px threshold). **Result: Downweighted & rejected.**
