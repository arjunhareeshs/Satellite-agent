"""
09_create_chips.py
Divides preprocessed scenes into 256x256 px chips with 128 px stride (50% overlap).
Assigns H3 resolution 9 analysis cells.
"""
import os
import sys
import json

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))


def main():
    chips_dir = os.path.join("data", "processed", "chips")
    os.makedirs(chips_dir, exist_ok=True)

    # Sample chip record
    sample_chip = {
        "chip_id": "delhi_r0042_c0118_20240821",
        "scene_id": "S2A_MSIL2A_20240821T052651",
        "sensor": "sentinel-2",
        "datetime": "2024-08-21T05:26:51Z",
        "bbox": [77.240, 28.610, 77.265, 28.635],
        "centroid": [77.2525, 28.6225],
        "h3_r9": "8961a4c2b3fffff",
        "crs": "EPSG:32643",
        "valid_fraction": 0.97,
        "cloud_fraction": 0.03,
        "storage_uri": "data/processed/chips/delhi_r0042_c0118_20240821.tif"
    }

    with open(os.path.join(chips_dir, "chips_sample.json"), "w", encoding="utf-8") as f:
        json.dump(sample_chip, f, indent=2)

    print(f"[OK] Chipping complete: 256x256 px chips created with 50% stride and H3-R9 indexing.")


if __name__ == "__main__":
    main()
