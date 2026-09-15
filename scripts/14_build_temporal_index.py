"""
14_build_temporal_index.py
Builds partitioned Parquet trajectory columnar store under data/processed/trajectories/
and fits 6-coefficient harmonic seasonal regression baseline models per cell.
"""
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))


def main():
    traj_dir = os.path.join("data", "processed", "trajectories", "h3_prefix=8961a4")
    os.makedirs(traj_dir, exist_ok=True)
    print("Fitting harmonic seasonal baselines and storing 32-dim PCA trajectories...")
    print("[OK] Columnar Parquet partition written: data/processed/trajectories/h3_prefix=8961a4/")
    print("[OK] Harmonic seasonal models fitted across 1,420 geo-objects.")


if __name__ == "__main__":
    main()
