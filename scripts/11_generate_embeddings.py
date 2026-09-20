"""
11 — Generate real dual embeddings and fit the frozen PCA basis.

Replaces a version that called two hash-based fakes and printed the shape of the
result. The old `encode_visual_prithvi` took a *string entity ID*, seeded an RNG
with its SHA-256 and returned Gaussian noise; the old text encoder bumped fixed
vector slices when a query contained the substring "building". No model was
loaded and no image was ever seen.

Per entity, two vectors kept separate so the ranker can weight them
independently (PRD section 5.3):

    visual_embedding    Prithvi-EO-2.0-300M   768-d   6-band context crop
    semantic_embedding  RemoteCLIP ViT-B/32   512-d   RGB crop, shared with text

Context-aware cropping (PRD section 5.2): the crop is the entity's bounding box
expanded by 50%, so the embedding sees the object *and* its surroundings. An
embedding of the object alone cannot express "building next to a river", which
is exactly the relationship the retrieval layer needs to rank on.

Also fits the 768 -> 32 PCA basis used by the temporal engine, and writes the
measured variance explained rather than a claimed one.

Usage:
    python scripts/11_generate_embeddings.py
    python scripts/11_generate_embeddings.py --batch-size 4   # tighter VRAM
    python scripts/11_generate_embeddings.py --limit 500
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from typing import Any, Dict, List, Tuple

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.core.grid import get_grid  # noqa: E402
from backend.models.encoders import (  # noqa: E402
    PRITHVI_BANDS,
    SEMANTIC_DIM,
    VISUAL_DIM,
    encode_semantic_image,
    encode_visual,
    pca_basis,
)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ENTITIES_PATH = os.path.join(ROOT, "data", "metadata", "entities.json")
S2_QUALITY = os.path.join(ROOT, "data", "metadata", "s2_quality.json")
OUT_PATH = os.path.join(ROOT, "data", "processed", "embeddings.npz")
META_PATH = os.path.join(ROOT, "data", "metadata", "embeddings.json")

# PRD section 5.2: expand the bounding box so the crop carries context.
CONTEXT_EXPANSION = 0.5
CROP_SIZE = 224
PCA_COMPONENTS = 32
PCA_MAX_SAMPLES = 20000


def crop_window(
    centroid_utm: Tuple[float, float], area_m2: float, grid, expansion: float
) -> Tuple[int, int, int]:
    """
    Pixel window for an entity, centred on its centroid with context.

    Returns (row_off, col_off, size). Clamped so the window stays on the grid;
    an entity at the AOI edge gets an off-centre crop rather than an error.
    """
    side_m = max(np.sqrt(max(area_m2, 1.0)) * (1.0 + 2.0 * expansion), 100.0)
    size = int(np.clip(round(side_m / grid.resolution_m), 32, 512))

    transform = grid.transform
    col = int((centroid_utm[0] - transform.c) / transform.a)
    row = int((centroid_utm[1] - transform.f) / transform.e)

    col_off = int(np.clip(col - size // 2, 0, max(grid.width - size, 0)))
    row_off = int(np.clip(row - size // 2, 0, max(grid.height - size, 0)))
    return row_off, col_off, size


def to_rgb_crop(window: np.ndarray, percentile: float = 2.0) -> np.ndarray:
    """8-bit RGB view of a 6-band crop for the RemoteCLIP image tower."""
    rgb = np.stack([window[2], window[1], window[0]], axis=-1).astype(np.float32)
    out = np.zeros(rgb.shape, dtype=np.uint8)
    for band in range(3):
        channel = rgb[..., band]
        finite = channel[np.isfinite(channel) & (channel > 0)]
        if finite.size == 0:
            continue
        lo, hi = np.percentile(finite, [percentile, 100 - percentile])
        if hi <= lo:
            continue
        out[..., band] = np.clip((channel - lo) / (hi - lo) * 255.0, 0, 255).astype(np.uint8)
    return out


def describe(entity: Dict[str, Any]) -> str:
    """
    Deterministic natural-language description (PRD section 5.4).

    Template-generated from database fields, not LLM-generated: reproducible,
    offline-safe, and free of hallucination. Indexed for keyword fallback and
    supplied to the VLM as grounding context.
    """
    attrs = entity.get("attributes", {}) or {}
    area = entity.get("area_m2", 0)
    size = "large" if area > 5000 else "medium-sized" if area > 1000 else "small"
    etype = entity["entity_type"].replace("_", " ")

    parts = ["A %s %s of approximately %d square metres" % (size, etype, int(area))]

    ndvi = attrs.get("ndvi")
    if ndvi is not None:
        if ndvi > 0.4:
            parts.append("surrounded by dense vegetation")
        elif ndvi < 0.1:
            parts.append("on bare or built-up ground")

    ndwi = attrs.get("ndwi")
    if ndwi is not None and ndwi > 0.1:
        parts.append("close to water")

    parts.append("observed in Sentinel-2 optical imagery on %s" % entity.get("observed_date"))
    return ", ".join(parts) + "."


def main() -> int:
    ap = argparse.ArgumentParser(description="Generate dual embeddings")
    ap.add_argument("--batch-size", type=int, default=8)
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--pca-components", type=int, default=PCA_COMPONENTS)
    ap.add_argument("--out", default=OUT_PATH)
    args = ap.parse_args()

    for path, hint in ((ENTITIES_PATH, "10_extract_entities.py"),
                       (S2_QUALITY, "07_preprocess_s2.py")):
        if not os.path.exists(path):
            print("FAIL: run scripts/%s first." % hint, file=sys.stderr)
            return 1

    import rasterio
    import torch
    from rasterio.windows import Window

    with open(ENTITIES_PATH, "r", encoding="utf-8") as fh:
        entity_doc = json.load(fh)
    with open(S2_QUALITY, "r", encoding="utf-8") as fh:
        s2_quality = json.load(fh)

    scene_paths = {s["stac_id"]: os.path.join(ROOT, s["output"]) for s in s2_quality["scenes"]}
    entities = entity_doc["entities"]
    if args.limit:
        entities = entities[: args.limit]

    grid = get_grid()
    device = "cuda" if torch.cuda.is_available() else "cpu"

    print("TRINETRA — dual embeddings")
    print("  entities    : %d" % len(entities))
    print("  device      : %s" % device)
    if device == "cuda":
        total = torch.cuda.get_device_properties(0).total_memory / 1e9
        print("  vram        : %.1f GB on %s" % (total, torch.cuda.get_device_name(0)))
    print("  visual      : Prithvi-EO-2.0-300M -> %d-d (%s)"
          % (VISUAL_DIM, " ".join(PRITHVI_BANDS)))
    print("  semantic    : RemoteCLIP ViT-B/32 -> %d-d (RGB)" % SEMANTIC_DIM)
    print("  context     : bbox expanded %.0f%%" % (CONTEXT_EXPANSION * 100))
    print("  batch       : %d" % args.batch_size)
    print()

    # ---- gather crops, grouped by scene so each COG opens once -------------
    by_scene: Dict[str, List[int]] = {}
    for idx, ent in enumerate(entities):
        by_scene.setdefault(ent["scene_id"], []).append(idx)

    multispectral: List[np.ndarray] = [None] * len(entities)  # type: ignore[list-item]
    rgb_crops: List[np.ndarray] = [None] * len(entities)  # type: ignore[list-item]
    skipped = 0

    t_read = time.perf_counter()
    for scene_id, idxs in by_scene.items():
        path = scene_paths.get(scene_id)
        if not path or not os.path.exists(path):
            skipped += len(idxs)
            continue

        with rasterio.open(path) as src:
            for idx in idxs:
                ent = entities[idx]
                row_off, col_off, size = crop_window(
                    tuple(ent["centroid_utm"]), ent["area_m2"], grid, CONTEXT_EXPANSION
                )
                window = Window(col_off, row_off, size, size)
                data = src.read(indexes=[1, 2, 3, 4, 5, 6], window=window)

                if data.shape[1] < 8 or data.shape[2] < 8:
                    skipped += 1
                    continue

                multispectral[idx] = data.astype(np.float32)
                rgb_crops[idx] = to_rgb_crop(data)

    keep = [i for i in range(len(entities)) if multispectral[i] is not None]
    print("  read        : %d crops in %.1f s (%d skipped)"
          % (len(keep), time.perf_counter() - t_read, skipped))

    if not keep:
        print("FAIL: no usable crops.", file=sys.stderr)
        return 1

    # ---- Prithvi -----------------------------------------------------------
    print("  encoding visual (Prithvi)...")
    t0 = time.perf_counter()
    visual = encode_visual([multispectral[i] for i in keep], batch_size=args.batch_size)
    visual_sec = time.perf_counter() - t0
    print("    %d x %d in %.1f s (%.1f/s)"
          % (visual.shape[0], visual.shape[1], visual_sec, len(keep) / max(visual_sec, 1e-6)))

    # Free the multispectral crops before loading the second model; on a 4 GB
    # card the two encoders plus their inputs do not comfortably coexist.
    multispectral = None  # type: ignore[assignment]
    if device == "cuda":
        torch.cuda.empty_cache()

    # ---- RemoteCLIP --------------------------------------------------------
    print("  encoding semantic (RemoteCLIP)...")
    t0 = time.perf_counter()
    semantic = encode_semantic_image(
        [rgb_crops[i] for i in keep], batch_size=max(args.batch_size * 2, 16)
    )
    semantic_sec = time.perf_counter() - t0
    print("    %d x %d in %.1f s (%.1f/s)"
          % (semantic.shape[0], semantic.shape[1], semantic_sec,
             len(keep) / max(semantic_sec, 1e-6)))

    # ---- PCA ---------------------------------------------------------------
    print("  fitting PCA %d -> %d..." % (VISUAL_DIM, args.pca_components))
    sample = visual
    if len(sample) > PCA_MAX_SAMPLES:
        rng = np.random.default_rng(0)
        sample = visual[rng.choice(len(visual), PCA_MAX_SAMPLES, replace=False)]
    variance = pca_basis.fit(sample, n_components=args.pca_components)
    print("    variance explained: %.4f (measured, %d samples)" % (variance, len(sample)))

    projected = pca_basis.transform(visual)

    # ---- write -------------------------------------------------------------
    entity_ids = [entities[i]["entity_id"] for i in keep]
    descriptions = [describe(entities[i]) for i in keep]

    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    np.savez_compressed(
        args.out,
        entity_ids=np.array(entity_ids),
        visual=visual.astype(np.float32),
        semantic=semantic.astype(np.float32),
        visual_pca=projected.astype(np.float32),
        descriptions=np.array(descriptions),
    )

    # Sanity: the old implementation would have passed any shape check, so the
    # useful assertion is that distinct entities produce distinct vectors.
    unique_visual = len(np.unique(np.round(visual[:, :8], 5), axis=0))
    unique_semantic = len(np.unique(np.round(semantic[:, :8], 5), axis=0))

    meta = {
        "entities_encoded": len(keep),
        "entities_skipped": skipped,
        "visual": {
            "model": "Prithvi-EO-2.0-300M",
            "dim": int(visual.shape[1]),
            "bands": PRITHVI_BANDS,
            "seconds": round(visual_sec, 2),
            "rate_per_sec": round(len(keep) / max(visual_sec, 1e-6), 2),
            "distinct_prefixes": unique_visual,
        },
        "semantic": {
            "model": "RemoteCLIP-ViT-B-32",
            "dim": int(semantic.shape[1]),
            "seconds": round(semantic_sec, 2),
            "rate_per_sec": round(len(keep) / max(semantic_sec, 1e-6), 2),
            "distinct_prefixes": unique_semantic,
        },
        "pca": {
            "components": args.pca_components,
            "variance_explained": round(variance, 4),
            "fitted_on_samples": len(sample),
            "path": "models/pca_basis.npz",
        },
        "context_expansion": CONTEXT_EXPANSION,
        "device": device,
        "output": os.path.relpath(args.out, ROOT),
    }
    with open(META_PATH, "w", encoding="utf-8") as fh:
        json.dump(meta, fh, indent=2)

    print()
    print("  distinct    : %d visual, %d semantic (of %d entities)"
          % (unique_visual, unique_semantic, len(keep)))
    print("  wrote       : %s (%.1f MB)"
          % (os.path.relpath(args.out, ROOT), os.path.getsize(args.out) / 1e6))
    print("  wrote       : %s" % os.path.relpath(META_PATH, ROOT))

    if unique_visual < len(keep) * 0.5:
        print("WARNING: more than half the visual embeddings are duplicates.",
              file=sys.stderr)
        print("         That suggests the crops are degenerate, not the model.",
              file=sys.stderr)

    print("OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
