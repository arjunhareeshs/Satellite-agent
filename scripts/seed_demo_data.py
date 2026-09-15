"""
TRINETRA Master Demo Seed Script.
Generates realistic Delhi-NCR Yamuna satellite imagery chips, geo-objects,
harmonic seasonal trajectories, Qdrant vectors, and negative controls.
Enables instant, zero-dependency offline operation.
"""
import os
import sys

# Ensure repository root is on sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import json
import math
import numpy as np
from datetime import datetime, timedelta
from PIL import Image, ImageDraw, ImageFilter

from backend.engines.spatial import spatial_engine
from backend.engines.semantic import semantic_engine
from backend.engines.temporal import temporal_engine, CellModel
from backend.models.encoders import encoders


def generate_chip_images(output_dir: str):
    """
    Renders high-fidelity synthetic satellite chips for before, after, and SAR observations.
    """
    os.makedirs(output_dir, exist_ok=True)
    size = (300, 300)

    # 1. BEFORE CHIP (Optical 2024-07-11: Vegetated/soil riverbank)
    img_before = Image.new("RGB", size, (74, 98, 54))  # Agricultural olive green
    draw_b = ImageDraw.Draw(img_before)
    # Draw winding river in blue-gray
    draw_b.polygon([(0, 220), (300, 250), (300, 300), (0, 300)], fill=(45, 65, 78))
    # Draw soil patches and field borders
    for x in range(20, 280, 40):
        draw_b.line([(x, 0), (x + 10, 220)], fill=(65, 88, 48), width=2)
    img_before = img_before.filter(ImageFilter.GaussianBlur(1.0))
    img_before.save(os.path.join(output_dir, "before_sample.png"))

    # 2. AFTER CHIP (Optical 2025-06-14: New concrete structure erected)
    img_after = img_before.copy()
    draw_a = ImageDraw.Draw(img_after)
    # Cleared bare ground around site
    draw_a.rectangle([(110, 100), (210, 190)], fill=(150, 140, 125))
    # Structure roof (bright reflective concrete)
    draw_a.rectangle([(130, 120), (190, 170)], fill=(215, 218, 220), outline=(80, 80, 80), width=2)
    # Structure shadow
    draw_a.polygon([(190, 120), (200, 125), (200, 175), (190, 170)], fill=(40, 40, 40))
    img_after = img_after.filter(ImageFilter.GaussianBlur(0.8))
    img_after.save(os.path.join(output_dir, "after_sample.png"))

    # 3. SAR CHIP (Sentinel-1 GRD 2024-08-19: Radar backscatter)
    # Grayscale radar speckle
    sar_arr = np.random.normal(loc=60, scale=25, size=(size[1], size[0])).clip(0, 255).astype(np.uint8)
    img_sar = Image.fromarray(sar_arr, mode="L").convert("RGB")
    draw_s = ImageDraw.Draw(img_sar)
    # River absorbs specularly (very dark in SAR)
    draw_s.polygon([(0, 220), (300, 250), (300, 300), (0, 300)], fill=(15, 15, 18))
    # Building dihedral corner reflectors (extremely bright SAR double-bounce)
    draw_s.rectangle([(130, 120), (190, 170)], fill=(245, 245, 250))
    img_sar.save(os.path.join(output_dir, "sar_sample.png"))


def generate_time_series(break_date: str, is_change: bool = True) -> list:
    """
    Generates 24-month observation time series (Jan 2024 -> Dec 2025)
    with seasonal harmonic variation and persistent step break if changed.
    """
    history = []
    base_date = datetime(2024, 1, 5)
    break_dt = datetime.fromisoformat(break_date)

    for i in range(24):
        obs_dt = base_date + timedelta(days=i * 30.4)
        date_str = obs_dt.strftime("%Y-%m-%d")
        doy = obs_dt.timetuple().tm_yday

        # Harmonic seasonal component (annual + semi-annual monsoon cycles)
        seasonal_val = 1.0 + 0.25 * math.cos(2 * math.pi * doy / 365.25) + 0.15 * math.sin(4 * math.pi * doy / 365.25)

        is_post_break = is_change and (obs_dt >= break_dt)
        step = 0.85 if is_post_break else 0.0
        noise = np.random.normal(0.0, 0.03)

        observed = seasonal_val + step + noise
        baseline = seasonal_val

        residual = abs(observed - baseline)
        z = (residual / 0.08) if is_post_break else (residual / 0.08)

        # Monsoon cloud drop in Jul-Aug
        valid_frac = 0.85 if (6 <= obs_dt.month <= 8) else 0.98

        history.append({
            "date": date_str,
            "embed_norm": float(observed),
            "baseline_norm": float(baseline),
            "residual_norm": float(residual),
            "z": float(z),
            "valid_fraction": valid_frac,
            "sensor": "sentinel-2" if (i % 2 == 0) else "sentinel-1",
            "ndvi": float(0.55 - (0.35 if is_post_break else 0.0) + 0.1 * math.sin(2 * math.pi * doy / 365.25)),
            "sar_vv_db": float(-14.0 + (4.5 if is_post_break else 0.0))
        })

    return history


def seed_all():
    print("==================================================")
    print("TRINETRA: Seeding Delhi-NCR Yamuna Intelligence Archive")
    print("==================================================")

    # 1. Generate Chips
    static_chips_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "backend", "static", "chips"))
    generate_chip_images(static_chips_dir)
    print("[OK] Synthetic optical & SAR satellite chips generated.")

    # 2. Define Entities
    entities = [
        {
            "entity_id": "BLDG_004281",
            "entity_type": "building",
            "class_confidence": 0.94,
            "centroid": {"lat": 28.6142, "lon": 77.2451},
            "geometry": {
                "type": "Polygon",
                "coordinates": [[[77.2445, 28.6138], [77.2458, 28.6138], [77.2458, 28.6146], [77.2445, 28.6146], [77.2445, 28.6138]]]
            },
            "h3_r9": "8961a4c2b3fffff",
            "area_m2": 1840.0,
            "first_seen": "2024-08-21",
            "first_seen_ci": ["2024-07-14", "2024-08-21"],
            "last_seen": "2025-11-28",
            "change_type": "construction",
            "change_confidence": 0.94,
            "optical_z": 5.2,
            "sar_z": 4.1,
            "valid_fraction": 0.97,
            "registration_residual_px": 0.18,
            "cloud_free_pct": 97.2,
            "observations_after_break": 7,
            "sensors": ["sentinel-2", "sentinel-1"],
            "source_scenes": ["S2A_MSIL2A_20240821T052651", "S1A_IW_GRDH_20240819"],
            "relations": {
                "river_distance_m": 320.0,
                "road_distance_m": 85.0,
                "nearest_water_id": "WTR_YAMUNA_MAIN",
                "nearest_road_id": "ROAD_RING_MAIN"
            },
            "imagery": {
                "before": "/api/v1/static/chips/before_sample.png",
                "after": "/api/v1/static/chips/after_sample.png",
                "sar": "/api/v1/static/chips/sar_sample.png"
            }
        },
        {
            "entity_id": "BLDG_004282",
            "entity_type": "building",
            "class_confidence": 0.89,
            "centroid": {"lat": 28.5980, "lon": 77.2580},
            "geometry": {
                "type": "Polygon",
                "coordinates": [[[77.2572, 28.5975], [77.2588, 28.5975], [77.2588, 28.5985], [77.2572, 28.5985], [77.2572, 28.5975]]]
            },
            "h3_r9": "8961a4c2b7fffff",
            "area_m2": 2450.0,
            "first_seen": "2024-10-18",
            "first_seen_ci": ["2024-09-22", "2024-10-18"],
            "last_seen": "2025-11-28",
            "change_type": "construction",
            "change_confidence": 0.91,
            "optical_z": 4.8,
            "sar_z": 3.9,
            "valid_fraction": 0.96,
            "registration_residual_px": 0.22,
            "cloud_free_pct": 96.0,
            "observations_after_break": 5,
            "sensors": ["sentinel-2", "sentinel-1"],
            "source_scenes": ["S2A_MSIL2A_20241018T052651", "S1A_IW_GRDH_20241016"],
            "relations": {
                "river_distance_m": 410.0,
                "road_distance_m": 120.0,
                "nearest_water_id": "WTR_YAMUNA_MAIN",
                "nearest_road_id": "ROAD_RING_MAIN"
            },
            "imagery": {
                "before": "/api/v1/static/chips/before_sample.png",
                "after": "/api/v1/static/chips/after_sample.png",
                "sar": "/api/v1/static/chips/sar_sample.png"
            }
        },
        {
            "entity_id": "BLDG_004283",
            "entity_type": "building",
            "class_confidence": 0.86,
            "centroid": {"lat": 28.6320, "lon": 77.2470},
            "geometry": {
                "type": "Polygon",
                "coordinates": [[[77.2462, 28.6315], [77.2478, 28.6315], [77.2478, 28.6325], [77.2462, 28.6325], [77.2462, 28.6315]]]
            },
            "h3_r9": "8961a4c2b1fffff",
            "area_m2": 1120.0,
            "first_seen": "2024-04-12",
            "first_seen_ci": ["2024-03-18", "2024-04-12"],
            "last_seen": "2025-11-28",
            "change_type": "construction",
            "change_confidence": 0.88,
            "optical_z": 4.1,
            "sar_z": 3.4,
            "valid_fraction": 0.95,
            "registration_residual_px": 0.20,
            "cloud_free_pct": 95.0,
            "observations_after_break": 11,
            "sensors": ["sentinel-2", "sentinel-1"],
            "source_scenes": ["S2A_MSIL2A_20240412T052651", "S1A_IW_GRDH_20240410"],
            "relations": {
                "river_distance_m": 180.0,
                "road_distance_m": 310.0,
                "nearest_water_id": "WTR_YAMUNA_MAIN",
                "nearest_road_id": "ROAD_RING_MAIN"
            },
            "imagery": {
                "before": "/api/v1/static/chips/before_sample.png",
                "after": "/api/v1/static/chips/after_sample.png",
                "sar": "/api/v1/static/chips/sar_sample.png"
            }
        },
        {
            "entity_id": "ROAD_001920",
            "entity_type": "road",
            "class_confidence": 0.92,
            "centroid": {"lat": 28.6250, "lon": 77.2510},
            "geometry": {
                "type": "Polygon",
                "coordinates": [[[77.2490, 28.6240], [77.2530, 28.6260], [77.2535, 28.6250], [77.2495, 28.6230], [77.2490, 28.6240]]]
            },
            "h3_r9": "8961a4c2b9fffff",
            "area_m2": 3200.0,
            "first_seen": "2024-09-14",
            "first_seen_ci": ["2024-08-20", "2024-09-14"],
            "last_seen": "2025-11-28",
            "change_type": "road_development",
            "change_confidence": 0.89,
            "optical_z": 4.5,
            "sar_z": 2.8,
            "valid_fraction": 0.94,
            "registration_residual_px": 0.19,
            "cloud_free_pct": 94.0,
            "observations_after_break": 6,
            "sensors": ["sentinel-2"],
            "source_scenes": ["S2A_MSIL2A_20240914T052651"],
            "relations": {
                "river_distance_m": 280.0,
                "road_distance_m": 10.0,
                "nearest_water_id": "WTR_YAMUNA_MAIN",
                "nearest_road_id": "ROAD_RING_MAIN"
            },
            "imagery": {
                "before": "/api/v1/static/chips/before_sample.png",
                "after": "/api/v1/static/chips/after_sample.png",
                "sar": "/api/v1/static/chips/sar_sample.png"
            }
        }
    ]

    # Load into spatial engine
    spatial_engine.load_memory_entities(entities)
    print(f"[OK] {len(entities)} core geo-entities loaded into Spatial Engine.")

    # Load vectors into semantic engine & timelines into temporal engine
    for e in entities:
        eid = e["entity_id"]
        v_vec = encoders.encode_visual_prithvi(eid)
        s_vec = encoders.encode_text_remoteclip(f"{e['entity_type']} {e.get('change_type', '')}")
        semantic_engine.upsert_entity(eid, v_vec, s_vec, e)

        # Time series trajectory
        trajectory = generate_time_series(e["first_seen"], is_change=True)
        temporal_engine.register_entity_timeline(eid, trajectory)

    print("[OK] Entity vectors registered in Qdrant semantic engine.")
    print("[OK] 24-month harmonic trajectories registered in Temporal Engine.")

    # Metadata files
    meta_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "data", "metadata"))
    os.makedirs(meta_dir, exist_ok=True)
    with open(os.path.join(meta_dir, "s2_scenes.json"), "w") as f:
        json.dump({"total": 58, "aoi": "delhi_ncr_yamuna", "cloud_filtered": True}, f, indent=2)
    with open(os.path.join(meta_dir, "s1_scenes.json"), "w") as f:
        json.dump({"total": 36, "aoi": "delhi_ncr_yamuna", "polarizations": ["VV", "VH"]}, f, indent=2)

    print("==================================================")
    print("Seed Complete! All systems ready for offline demo.")
    print("==================================================")


if __name__ == "__main__":
    seed_all()
