"""
00 — Stage the model weights locally and write a truthful MANIFEST.json.

models/ previously held four empty directories while config/MANIFEST.json listed
five models with SHA-256 digests for files that did not exist and declared
"offline_compliant": true.

This script downloads the real weights from HuggingFace, computes real digests
from the bytes on disk, and rewrites MANIFEST.json to describe what is actually
staged. `offline_compliant` becomes true only when every declared artifact is
present.

Model choices, and why:

  Prithvi-EO-2.0-300M   PRD section 5.3. The repo ships prithvi_mae.py and
                        config.json alongside the checkpoint, so we avoid a
                        terratorch dependency. ~1.2 GB, fits 4 GB VRAM.

  RemoteCLIP ViT-B/32   PRD section 5.3. Loads into an open_clip ViT-B-32
                        skeleton. ~600 MB.

  FastSAM-s             PRD section 3.3 permits "SAM (or FastSAM)". FastSAM is
                        roughly 50x faster and is the default here because the
                        entity pass covers ~19 dates x 324 chips; SAM ViT-B is
                        staged too and selectable with --quality for comparison.

  s2cloudless           Ships its own model inside the pip package; we locate
                        and record it rather than re-downloading.

Usage:
    python scripts/00_download_models.py
    python scripts/00_download_models.py --skip vlm     # weights only
    python scripts/00_download_models.py --verify       # re-check, no download
"""

from __future__ import annotations

import argparse
import os
import shutil
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.core.manifest import build_manifest, verify_manifest  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MODELS_DIR = os.path.join(ROOT, "models")

# (hf_repo, filename, destination relative to models/)
DOWNLOADS = [
    (
        "prithvi",
        "ibm-nasa-geospatial/Prithvi-EO-2.0-300M",
        [
            ("Prithvi_EO_V2_300M.pt", "prithvi_eo_2_300m/Prithvi_EO_V2_300M.pt"),
            ("config.json", "prithvi_eo_2_300m/config.json"),
            ("prithvi_mae.py", "prithvi_eo_2_300m/prithvi_mae.py"),
        ],
    ),
    (
        "remoteclip",
        "chendelong/RemoteCLIP",
        [("RemoteCLIP-ViT-B-32.pt", "remoteclip_vit_b32/RemoteCLIP-ViT-B-32.pt")],
    ),
]


def download_hf(repo_id: str, filename: str, dest_rel: str, attempts: int = 4) -> str:
    """
    Fetch one file from HuggingFace into models/ at a stable path.

    Retried with backoff. These are multi-gigabyte transfers from a CDN, and a
    transient DNS or connection-reset partway through is common enough that
    without retry a single blip costs the whole staging run. huggingface_hub
    resumes from its own cache, so a retry does not restart from zero.
    """
    import time as _time

    from huggingface_hub import hf_hub_download

    dest = os.path.join(MODELS_DIR, dest_rel)
    os.makedirs(os.path.dirname(dest), exist_ok=True)

    if os.path.exists(dest):
        print("    cached   %s" % dest_rel)
        return dest

    last_error = None
    for attempt in range(1, attempts + 1):
        try:
            if attempt == 1:
                print("    fetching %s : %s" % (repo_id, filename))
            else:
                print("    retry %d/%d %s : %s" % (attempt, attempts, repo_id, filename))
            cached = hf_hub_download(repo_id=repo_id, filename=filename)
            shutil.copy2(cached, dest)
            print("    staged   %s  (%.1f MB)" % (dest_rel, os.path.getsize(dest) / 1e6))
            return dest
        except Exception as exc:  # noqa: BLE001
            last_error = exc
            if attempt < attempts:
                delay = 5 * attempt
                print("    failed (%s); retrying in %ds" % (type(exc).__name__, delay))
                _time.sleep(delay)

    raise RuntimeError("could not fetch %s/%s: %s" % (repo_id, filename, last_error))


def download_fastsam() -> str:
    """
    FastSAM-s via ultralytics, which resolves and caches the checkpoint itself.
    """
    dest = os.path.join(MODELS_DIR, "fastsam", "FastSAM-s.pt")
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    if os.path.exists(dest):
        print("    cached   fastsam/FastSAM-s.pt")
        return dest

    from ultralytics import FastSAM

    print("    fetching ultralytics : FastSAM-s.pt")
    model = FastSAM("FastSAM-s.pt")
    src = getattr(model, "ckpt_path", None) or "FastSAM-s.pt"
    if os.path.exists(src):
        shutil.move(src, dest)
    print("    staged   fastsam/FastSAM-s.pt  (%.1f MB)" % (os.path.getsize(dest) / 1e6))
    return dest


def download_sam_vit_b() -> str:
    """SAM ViT-B as the quality tier, via the HF transformers checkpoint."""
    from huggingface_hub import snapshot_download

    dest_dir = os.path.join(MODELS_DIR, "sam_vit_b")
    os.makedirs(dest_dir, exist_ok=True)
    marker = os.path.join(dest_dir, "model.safetensors")
    if os.path.exists(marker):
        print("    cached   sam_vit_b/model.safetensors")
        return marker

    print("    fetching facebook/sam-vit-base")
    snapshot_download(
        repo_id="facebook/sam-vit-base",
        local_dir=dest_dir,
        allow_patterns=["*.json", "*.safetensors"],
    )
    print("    staged   sam_vit_b/  (%.1f MB)" % (os.path.getsize(marker) / 1e6))
    return marker


def locate_s2cloudless() -> str:
    """
    s2cloudless bundles its LightGBM classifier inside the installed package.
    Copy it into models/ so the offline bundle is self-describing.
    """
    dest = os.path.join(MODELS_DIR, "s2cloudless", "pixel_s2_cloud_detector_lightGBM_v0.1.txt")
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    if os.path.exists(dest):
        print("    cached   s2cloudless/")
        return dest

    import s2cloudless

    pkg_dir = os.path.dirname(os.path.abspath(s2cloudless.__file__))
    for dirpath, _dirnames, filenames in os.walk(pkg_dir):
        for fn in filenames:
            if fn.endswith((".txt", ".pkl")) and "cloud" in fn.lower():
                shutil.copy2(os.path.join(dirpath, fn), dest)
                print("    staged   s2cloudless/%s" % os.path.basename(dest))
                return dest

    print("    WARNING  s2cloudless model file not found inside the package")
    return dest


def main() -> int:
    ap = argparse.ArgumentParser(description="Stage model weights and write MANIFEST.json")
    ap.add_argument("--verify", action="store_true", help="Verify only, do not download")
    ap.add_argument(
        "--skip", nargs="*", default=[],
        choices=["prithvi", "remoteclip", "fastsam", "sam", "s2cloudless"],
        help="Components to skip",
    )
    args = ap.parse_args()

    if args.verify:
        res = verify_manifest()
        print("MANIFEST verification: %s" % ("OK" if res.ok else "FAILED"))
        print("  %s" % res.message)
        for item in res.missing + res.mismatched:
            print("    %s" % item)
        return 0 if res.ok else 1

    os.makedirs(MODELS_DIR, exist_ok=True)
    print("TRINETRA — model staging")
    print("  destination : models/")
    print()

    if "prithvi" not in args.skip:
        print("  Prithvi-EO-2.0-300M")
        for repo_key, repo_id, files in DOWNLOADS:
            if repo_key != "prithvi":
                continue
            for filename, dest_rel in files:
                try:
                    download_hf(repo_id, filename, dest_rel)
                except Exception as exc:  # noqa: BLE001
                    print("    WARNING  %s" % exc)

    if "remoteclip" not in args.skip:
        print("  RemoteCLIP ViT-B/32")
        for repo_key, repo_id, files in DOWNLOADS:
            if repo_key != "remoteclip":
                continue
            for filename, dest_rel in files:
                try:
                    download_hf(repo_id, filename, dest_rel)
                except Exception as exc:  # noqa: BLE001
                    print("    WARNING  %s" % exc)

    if "fastsam" not in args.skip:
        print("  FastSAM-s (segmentation, default)")
        try:
            download_fastsam()
        except Exception as exc:  # noqa: BLE001
            print("    WARNING  FastSAM staging failed: %s" % exc)

    if "sam" not in args.skip:
        print("  SAM ViT-B (segmentation, quality tier)")
        try:
            download_sam_vit_b()
        except Exception as exc:  # noqa: BLE001
            print("    WARNING  SAM staging failed: %s" % exc)

    if "s2cloudless" not in args.skip:
        print("  s2cloudless (cloud masking)")
        try:
            locate_s2cloudless()
        except Exception as exc:  # noqa: BLE001
            print("    WARNING  s2cloudless staging failed: %s" % exc)

    print()
    print("  writing config/MANIFEST.json with digests computed from disk...")

    models = [
        {
            "name": "Prithvi-EO-2.0",
            "architecture": "Temporal ViT (300M)",
            "weights_version": "v2.0-300m",
            "source": "https://huggingface.co/ibm-nasa-geospatial/Prithvi-EO-2.0-300M",
            "license": "Apache-2.0 (NASA-IBM)",
            "embedding_dimension": 768,
            "local_path": "models/prithvi_eo_2_300m/Prithvi_EO_V2_300M.pt",
            "role": "Multi-spectral satellite representation & visual trajectory modeling",
        },
        {
            "name": "RemoteCLIP-ViT-B-32",
            "architecture": "Dual Vision-Language Transformer",
            "weights_version": "ViT-B/32",
            "source": "https://huggingface.co/chendelong/RemoteCLIP",
            "license": "Research & Academic Evaluation",
            "embedding_dimension": 512,
            "local_path": "models/remoteclip_vit_b32/RemoteCLIP-ViT-B-32.pt",
            "role": "Shared image-text semantic retrieval space",
        },
        {
            "name": "FastSAM-s",
            "architecture": "YOLOv8-seg instance segmentation",
            "weights_version": "FastSAM-s",
            "source": "https://github.com/ultralytics/ultralytics",
            "license": "AGPL-3.0",
            "local_path": "models/fastsam/FastSAM-s.pt",
            "role": "Class-agnostic geo-object segmentation (default tier)",
        },
        {
            "name": "SAM (Segment Anything Model)",
            "architecture": "ViT-B Mask Decoder",
            "weights_version": "facebook/sam-vit-base",
            "source": "https://huggingface.co/facebook/sam-vit-base",
            "license": "Apache-2.0",
            "local_path": "models/sam_vit_b/model.safetensors",
            "role": "Class-agnostic geo-object segmentation (quality tier)",
        },
        {
            "name": "s2cloudless",
            "architecture": "Gradient Boosted Cloud Masking (LightGBM)",
            "weights_version": "1.7.2",
            "source": "https://github.com/sentinel-hub/sentinel2-cloud-detector",
            "license": "CC-BY-SA-4.0",
            "local_path": "models/s2cloudless/pixel_s2_cloud_detector_lightGBM_v0.1.txt",
            "role": "Deterministic cloud & cloud-shadow masking (Gate 1)",
        },
    ]

    # The PCA basis is fitted in stage 11 from real embeddings, so it is declared
    # here but will show staged=false until that stage runs.
    frozen = {
        "pca_basis": {
            "name": "pca_basis",
            "local_path": "models/pca_basis.npz",
            "dimensions": [768, 32],
            "role": "Frozen projection for embedding trajectories (PRD section 7.2)",
            "note": "Fitted by scripts/11_generate_embeddings.py from real embeddings",
        }
    }

    manifest = build_manifest(models=models, frozen_components=frozen)

    print()
    print("  artifacts   : %d/%d staged"
          % (manifest["artifacts_staged"], manifest["artifacts_declared"]))
    print("  offline     : %s" % manifest["offline_compliant"])
    print("  manifest    : %s" % manifest["manifest_hash"][:32])
    print()
    for entry in manifest["models"]:
        mark = "ok  " if entry["staged"] else "MISS"
        size = "%.1f MB" % (entry.get("size_bytes", 0) / 1e6) if entry["staged"] else "-"
        print("    %s %-28s %10s  %s"
              % (mark, entry["name"], size, (entry.get("sha256") or "")[:16]))

    if not manifest["offline_compliant"]:
        print()
        print("  NOTE: not all artifacts staged. offline_compliant is recorded as")
        print("        false rather than asserted. Re-run to complete.")

    print("OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
