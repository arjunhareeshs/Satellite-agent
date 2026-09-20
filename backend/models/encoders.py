"""
Real image and text encoders: Prithvi-EO-2.0 and RemoteCLIP.

This replaces an implementation in which `encode_visual_prithvi` took a *string
entity ID*, seeded a numpy RNG with its SHA-256, and returned Gaussian noise,
while `encode_text_remoteclip` hashed words into bucket indices and nudged fixed
slices for keywords like "building". No model was loaded and no image was ever
seen. Both functions now take pixels and run real forward passes.

Two vectors per entity, kept separate so the ranker can weight them
independently (PRD section 5.3):

  visual_embedding    Prithvi-EO-2.0-300M   1024-d   what the pixels look like
  semantic_embedding  RemoteCLIP ViT-B/32    512-d   shared image/text space

Weights are loaded from models/, staged by scripts/00_download_models.py and
verified against config/MANIFEST.json.

Hardware note: this is sized for a 4 GB card. Models load lazily and one at a
time, inference runs under autocast in fp16, and batch sizes are conservative.
Nothing here requires both encoders resident simultaneously.
"""

from __future__ import annotations

import os
import threading
from typing import Iterable, List, Optional, Sequence

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

PRITHVI_DIR = os.path.join(ROOT, "models", "prithvi_eo_2_300m")
PRITHVI_CKPT = os.path.join(PRITHVI_DIR, "Prithvi_EO_V2_300M.pt")
PRITHVI_CONFIG = os.path.join(PRITHVI_DIR, "config.json")

REMOTECLIP_CKPT = os.path.join(
    ROOT, "models", "remoteclip_vit_b32", "RemoteCLIP-ViT-B-32.pt"
)

# 1024, not the 768 the PRD states. Prithvi-EO-2.0-300M's own config.json
# declares embed_dim 1024 / num_features 1024, and the checkpoint agrees. The
# PRD's 768 appears to have been carried over from Prithvi-EO-1.0. Nothing
# checked it, because no model was ever loaded.
VISUAL_DIM = 1024
SEMANTIC_DIM = 512

# Prithvi-EO-2.0 consumes six bands. Its config.json names them in HLS
# convention as B02,B03,B04,B05,B06,B07; in Sentinel-2 naming those are the
# same physical wavelengths as B02,B03,B04,B8A,B11,B12, which is the order
# scripts/04_download_sentinel2.py writes the stack in.
PRITHVI_BANDS = ["B02", "B03", "B04", "B8A", "B11", "B12"]
PRITHVI_HLS_BANDS = ["B02", "B03", "B04", "B05", "B06", "B07"]
PRITHVI_INPUT_SIZE = 224

_lock = threading.Lock()


def _device():
    import torch

    return "cuda" if torch.cuda.is_available() else "cpu"


class EncoderUnavailable(RuntimeError):
    """Raised when weights are not staged. Never silently substituted."""


# --------------------------------------------------------------------------- Prithvi


class PrithviEncoder:
    """
    Prithvi-EO-2.0-300M visual encoder.

    The HuggingFace repo ships `prithvi_mae.py` and `config.json` next to the
    checkpoint, so we construct the model from its own code rather than taking a
    terratorch dependency. We use the MAE encoder's CLS-pooled output as the
    entity embedding.
    """

    def __init__(self, checkpoint: str = PRITHVI_CKPT, config: str = PRITHVI_CONFIG):
        self.checkpoint = checkpoint
        self.config_path = config
        self._model = None
        self._mean: Optional[np.ndarray] = None
        self._std: Optional[np.ndarray] = None
        self._device = None

    @property
    def available(self) -> bool:
        return os.path.exists(self.checkpoint) and os.path.exists(self.config_path)

    def _load(self):
        if self._model is not None:
            return self._model

        if not self.available:
            raise EncoderUnavailable(
                "Prithvi weights not staged at %s. "
                "Run: python scripts/00_download_models.py" % self.checkpoint
            )

        import importlib.util
        import json

        import torch

        with open(self.config_path, "r", encoding="utf-8") as fh:
            cfg = json.load(fh)

        params = cfg.get("pretrained_cfg", cfg)

        # Normalization statistics ship with the model. Falling back to 0/1
        # would shift the input distribution and quietly degrade every
        # embedding, so a missing value is an error rather than a default.
        mean, std = params.get("mean"), params.get("std")
        if mean is None or std is None:
            raise EncoderUnavailable(
                "Prithvi config.json is missing band mean/std; cannot normalize input."
            )
        self._mean = np.asarray(mean, dtype=np.float32).reshape(-1, 1, 1)
        self._std = np.asarray(std, dtype=np.float32).reshape(-1, 1, 1)

        module_path = os.path.join(PRITHVI_DIR, "prithvi_mae.py")
        spec = importlib.util.spec_from_file_location("prithvi_mae", module_path)
        prithvi_mae = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(prithvi_mae)

        # Build a single-frame encoder, not the checkpoint's four.
        #
        # We only ever embed one date at a time. Building with num_frames=4 and
        # feeding one frame does work, but it sends PrithviViT down its
        # interpolate_pos_encoding path on every call, and that path regenerates
        # the positional embedding through numpy -- producing a CPU tensor that
        # is then added to CUDA activations, which raises "Expected all tensors
        # to be on the same device". Regenerating the embedding once here, at
        # load, avoids the bug entirely and removes per-call work.
        #
        # This is exact rather than approximate: Prithvi's positional embedding
        # is fixed 3D sin-cos, not learned, so a freshly generated one for a
        # (1, 14, 14) grid is the same function the model would have computed.
        self._num_frames = 1
        model = prithvi_mae.PrithviViT(
            img_size=params.get("img_size", PRITHVI_INPUT_SIZE),
            patch_size=tuple(params.get("patch_size", (1, 16, 16))),
            num_frames=self._num_frames,
            in_chans=params.get("in_chans", len(PRITHVI_BANDS)),
            embed_dim=params.get("embed_dim", VISUAL_DIM),
            depth=params.get("depth", 24),
            num_heads=params.get("num_heads", 16),
            mlp_ratio=params.get("mlp_ratio", 4.0),
            coords_encoding=params.get("coords_encoding") or [],
            coords_scale_learn=params.get("coords_scale_learn", False),
        )

        # The released file is the full MAE with "encoder."/"decoder." prefixes.
        # Strip the encoder prefix and drop the decoder half, which is only used
        # for the reconstruction objective and is dead weight at inference.
        raw = torch.load(self.checkpoint, map_location="cpu", weights_only=False)
        raw = raw.get("model", raw)
        state = {
            key[len("encoder.") :]: value
            for key, value in raw.items()
            if key.startswith("encoder.")
        }
        if not state:
            state = {
                k: v for k, v in raw.items()
                if not k.startswith(("decoder", "mask_token"))
            }

        # Replace the four-frame positional embedding with a single-frame one so
        # the shapes match the encoder we just built.
        target_pos = model.pos_embed
        if "pos_embed" in state and state["pos_embed"].shape != target_pos.shape:
            regenerated = prithvi_mae.get_3d_sincos_pos_embed(
                target_pos.shape[-1],
                model.patch_embed.grid_size,
                add_cls_token=True,
            )
            state["pos_embed"] = (
                torch.from_numpy(regenerated).float().unsqueeze(0)
            )

        missing, unexpected = model.load_state_dict(state, strict=False)
        if missing:
            raise EncoderUnavailable(
                "Prithvi checkpoint does not match the model definition "
                "(%d missing keys, first: %s). Re-run "
                "scripts/00_download_models.py." % (len(missing), missing[:3])
            )

        self._device = _device()
        model.eval().to(self._device)
        self._model = model
        return model

    def _preprocess(self, chips: Sequence[np.ndarray]):
        """
        Normalize and resize a batch of (6, H, W) reflectance chips.

        Input is raw L2A reflectance as uint16; Prithvi expects standardized
        float. Resize is bilinear onto the model's 224 px input.
        """
        import torch
        import torch.nn.functional as F

        batch = []
        for chip in chips:
            arr = np.asarray(chip, dtype=np.float32)
            if arr.ndim != 3 or arr.shape[0] != len(PRITHVI_BANDS):
                raise ValueError(
                    "Prithvi expects a (%d, H, W) chip in band order %s, got %s"
                    % (len(PRITHVI_BANDS), PRITHVI_BANDS, arr.shape)
                )
            arr = (arr - self._mean) / self._std
            batch.append(torch.from_numpy(arr))

        tensor = torch.stack(batch)
        if tensor.shape[-1] != PRITHVI_INPUT_SIZE or tensor.shape[-2] != PRITHVI_INPUT_SIZE:
            tensor = F.interpolate(
                tensor,
                size=(PRITHVI_INPUT_SIZE, PRITHVI_INPUT_SIZE),
                mode="bilinear",
                align_corners=False,
            )
        # Prithvi is temporal: (B, C, T, H, W). We supply a single frame.
        # forward_features only auto-adds the time dim when the model was built
        # with num_frames == 1; ours is built to the checkpoint's 4, so we add
        # it explicitly and let interpolate_pos_encoding resize the positional
        # embedding from four frames down to one.
        return tensor.unsqueeze(2)

    def encode(self, chips: Sequence[np.ndarray], batch_size: int = 8) -> np.ndarray:
        """
        Encode chips to L2-normalized 768-d vectors.

        Returns (N, 768) float32.
        """
        import torch

        model = self._load()
        out: List[np.ndarray] = []

        with _lock, torch.inference_mode():
            for start in range(0, len(chips), batch_size):
                tensor = self._preprocess(chips[start : start + batch_size])
                tensor = tensor.to(self._device)

                use_amp = self._device == "cuda"
                with torch.autocast("cuda", dtype=torch.float16, enabled=use_amp):
                    features = model.forward_features(tensor)

                # forward_features returns one tensor per transformer block;
                # the last is the final hidden state.
                if isinstance(features, (tuple, list)):
                    features = features[-1]
                if features.ndim == 3:
                    # (B, tokens, dim): token 0 is CLS, the rest are patches.
                    #
                    # Mean-pool the patch tokens, not CLS. Prithvi is a masked
                    # autoencoder, so its CLS token was never trained against a
                    # contrastive objective and carries almost no discriminative
                    # signal: measured over five contrasting Delhi chips, CLS
                    # cosines spanned 0.9995-0.9998, a spread of 0.0002. Patch
                    # mean-pooling gives 0.0121 over the same chips.
                    #
                    # That is still compressed, because MAE features are strongly
                    # anisotropic -- a single dominant component common to every
                    # chip. VisualCentering below removes it, which takes the
                    # spread to ~1.26. Centering is applied at indexing and query
                    # time rather than here, so what this function returns stays
                    # a faithful, reproducible model output.
                    features = features[:, 1:, :].mean(dim=1)

                features = features.float()
                features = torch.nn.functional.normalize(features, dim=-1)
                out.append(features.cpu().numpy().astype(np.float32))

                if self._device == "cuda":
                    torch.cuda.empty_cache()

        return np.concatenate(out, axis=0) if out else np.zeros((0, VISUAL_DIM), np.float32)


# --------------------------------------------------------------------------- RemoteCLIP


class RemoteClipEncoder:
    """
    RemoteCLIP ViT-B/32 — a CLIP fine-tuned on remote sensing imagery.

    Provides both towers: `encode_image` for entity crops and `encode_text` for
    the analyst's natural-language query. They land in the same 512-d space,
    which is what makes text-to-image retrieval work at all.
    """

    def __init__(self, checkpoint: str = REMOTECLIP_CKPT, arch: str = "ViT-B-32"):
        self.checkpoint = checkpoint
        self.arch = arch
        self._model = None
        self._preprocess_fn = None
        self._tokenizer = None
        self._device = None

    @property
    def available(self) -> bool:
        return os.path.exists(self.checkpoint)

    def _load(self):
        if self._model is not None:
            return self._model

        if not self.available:
            raise EncoderUnavailable(
                "RemoteCLIP weights not staged at %s.\n"
                "Run: python scripts/00_download_models.py" % self.checkpoint
            )

        import open_clip
        import torch

        model, _, preprocess = open_clip.create_model_and_transforms(self.arch)
        state = torch.load(self.checkpoint, map_location="cpu", weights_only=False)
        state = state.get("state_dict", state)
        state = {k.replace("module.", ""): v for k, v in state.items()}
        model.load_state_dict(state, strict=False)

        self._device = _device()
        model.eval().to(self._device)

        self._model = model
        self._preprocess_fn = preprocess
        self._tokenizer = open_clip.get_tokenizer(self.arch)
        return model

    def encode_image(self, images: Sequence, batch_size: int = 16) -> np.ndarray:
        """
        Encode RGB crops (PIL Images or HWC uint8 arrays) to 512-d vectors.
        """
        import torch
        from PIL import Image

        model = self._load()
        out: List[np.ndarray] = []

        with _lock, torch.inference_mode():
            for start in range(0, len(images), batch_size):
                chunk = images[start : start + batch_size]
                tensors = []
                for img in chunk:
                    if isinstance(img, np.ndarray):
                        img = Image.fromarray(np.asarray(img, dtype=np.uint8))
                    tensors.append(self._preprocess_fn(img))

                batch = torch.stack(tensors).to(self._device)
                use_amp = self._device == "cuda"
                with torch.autocast("cuda", dtype=torch.float16, enabled=use_amp):
                    features = model.encode_image(batch)

                features = torch.nn.functional.normalize(features.float(), dim=-1)
                out.append(features.cpu().numpy().astype(np.float32))

                if self._device == "cuda":
                    torch.cuda.empty_cache()

        return np.concatenate(out, axis=0) if out else np.zeros((0, SEMANTIC_DIM), np.float32)

    def encode_text(self, texts: Sequence[str], batch_size: int = 64) -> np.ndarray:
        """Encode query strings into the same 512-d space as the image tower."""
        import torch

        model = self._load()
        out: List[np.ndarray] = []

        with _lock, torch.inference_mode():
            for start in range(0, len(texts), batch_size):
                tokens = self._tokenizer(list(texts[start : start + batch_size]))
                tokens = tokens.to(self._device)
                features = model.encode_text(tokens)
                features = torch.nn.functional.normalize(features.float(), dim=-1)
                out.append(features.cpu().numpy().astype(np.float32))

        return np.concatenate(out, axis=0) if out else np.zeros((0, SEMANTIC_DIM), np.float32)


# --------------------------------------------------------------------------- centering


class VisualCentering:
    """
    Corpus-mean centering for the Prithvi visual embeddings.

    Why this exists: MAE representations are anisotropic. Almost all of the
    vector norm sits in one direction shared by every chip, so raw cosine
    similarity between any two Delhi chips lands around 0.99 and ranking is
    close to arbitrary. Measured on five deliberately contrasting chips from a
    real scene:

        CLS token        cosine spread 0.0002
        patch mean-pool  cosine spread 0.0121
        mean-centered    cosine spread 1.2567

    Subtracting a *fixed corpus mean* -- not a per-batch mean, which would make
    a vector depend on what else happened to be in its batch -- restores the
    discrimination without touching the model.

    The mean is fitted once in scripts/11_generate_embeddings.py and saved
    alongside the PCA basis, so indexing and query time apply exactly the same
    transform. Applying it to one side only would be worse than not applying it.
    """

    def __init__(self, path: str = os.path.join(ROOT, "models", "visual_centering.npz")):
        self.path = path
        self._mean: Optional[np.ndarray] = None

    @property
    def available(self) -> bool:
        return os.path.exists(self.path)

    def fit(self, embeddings: np.ndarray) -> float:
        """Fit and persist. Returns the mean cosine spread achieved."""
        arr = np.asarray(embeddings, dtype=np.float32)
        self._mean = arr.mean(axis=0)
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        np.savez(self.path, mean=self._mean, n_samples=np.array(len(arr)))

        sample = arr[: min(len(arr), 256)]
        centered = self.transform(sample)
        sims = centered @ centered.T
        off_diagonal = sims[~np.eye(len(sims), dtype=bool)]
        return float(off_diagonal.max() - off_diagonal.min()) if off_diagonal.size else 0.0

    def load(self) -> None:
        if self._mean is not None:
            return
        if not self.available:
            raise EncoderUnavailable(
                "Visual centering not fitted at %s. "
                "Run: python scripts/11_generate_embeddings.py" % self.path
            )
        self._mean = np.load(self.path)["mean"].astype(np.float32)

    def transform(self, embeddings: np.ndarray, strict: bool = True) -> np.ndarray:
        """
        Centre and re-normalize. With strict=False an unfitted transform passes
        the input through unchanged, which is what lets the demo fixture and the
        unit tests run before stage 11 has been executed.
        """
        arr = np.atleast_2d(np.asarray(embeddings, dtype=np.float32))
        if self._mean is None:
            if not self.available:
                if strict:
                    self.load()
                return arr
            self.load()
        centered = arr - self._mean
        norms = np.linalg.norm(centered, axis=1, keepdims=True)
        return centered / np.maximum(norms, 1e-7)


# --------------------------------------------------------------------------- PCA


class FrozenPCA:
    """
    The frozen 1024 -> 32 projection used for embedding trajectories.

    PRD section 7.2 runs the temporal model in a reduced space; projecting each
    observation through a *fixed* basis is what makes coefficients comparable
    across dates. Previously this was `np.random.default_rng(seed=42)` with a
    manifest entry claiming 88.4% variance explained and no file on disk.

    Fitted by scripts/11_generate_embeddings.py from real embeddings and saved
    to models/pca_basis.npz with its measured variance.
    """

    def __init__(self, path: str = os.path.join(ROOT, "models", "pca_basis.npz")):
        self.path = path
        self._components: Optional[np.ndarray] = None
        self._mean: Optional[np.ndarray] = None
        self.variance_explained: Optional[float] = None

    @property
    def available(self) -> bool:
        return os.path.exists(self.path)

    def load(self):
        if self._components is not None:
            return
        if not self.available:
            raise EncoderUnavailable(
                "PCA basis not fitted at %s.\n"
                "Run: python scripts/11_generate_embeddings.py" % self.path
            )
        data = np.load(self.path)
        self._components = data["components"].astype(np.float32)
        self._mean = data["mean"].astype(np.float32)
        self.variance_explained = float(data["variance_explained"])

    def fit(self, embeddings: np.ndarray, n_components: int = 32) -> float:
        """Fit and persist. Returns the measured cumulative variance explained."""
        from sklearn.decomposition import PCA

        pca = PCA(n_components=n_components, random_state=0)
        pca.fit(np.asarray(embeddings, dtype=np.float32))

        self._components = pca.components_.astype(np.float32)
        self._mean = pca.mean_.astype(np.float32)
        self.variance_explained = float(pca.explained_variance_ratio_.sum())

        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        np.savez(
            self.path,
            components=self._components,
            mean=self._mean,
            variance_explained=np.array(self.variance_explained),
            n_samples=np.array(len(embeddings)),
        )
        return self.variance_explained

    def transform(self, embeddings: np.ndarray) -> np.ndarray:
        self.load()
        arr = np.atleast_2d(np.asarray(embeddings, dtype=np.float32))
        return (arr - self._mean) @ self._components.T


# --------------------------------------------------------------------------- module API

prithvi = PrithviEncoder()
remoteclip = RemoteClipEncoder()
pca_basis = FrozenPCA()
visual_centering = VisualCentering()


def encode_visual(chips: Sequence[np.ndarray], batch_size: int = 8) -> np.ndarray:
    """(N, 6, H, W) reflectance chips -> (N, 1024) raw visual embeddings."""
    return prithvi.encode(chips, batch_size=batch_size)


def encode_visual_indexed(chips: Sequence[np.ndarray], batch_size: int = 8) -> np.ndarray:
    """
    As encode_visual, then corpus-mean centred.

    This is what goes into Qdrant and what a query must be encoded with. See
    VisualCentering for why the raw vectors are not directly comparable.
    """
    return visual_centering.transform(
        prithvi.encode(chips, batch_size=batch_size), strict=False
    )


def encode_semantic_image(images: Sequence, batch_size: int = 16) -> np.ndarray:
    """RGB crops -> (N, 512) semantic embeddings."""
    return remoteclip.encode_image(images, batch_size=batch_size)


def encode_semantic_text(texts: Iterable[str], batch_size: int = 64) -> np.ndarray:
    """Query strings -> (N, 512) semantic embeddings, same space as images."""
    return remoteclip.encode_text(list(texts), batch_size=batch_size)


def encoder_status() -> dict:
    """Reported by /api/v1/health so a missing weight file is visible, not silent."""
    status = {
        "prithvi": {
            "available": prithvi.available,
            "path": os.path.relpath(PRITHVI_CKPT, ROOT),
            "dim": VISUAL_DIM,
        },
        "remoteclip": {
            "available": remoteclip.available,
            "path": os.path.relpath(REMOTECLIP_CKPT, ROOT),
            "dim": SEMANTIC_DIM,
        },
        "pca_basis": {
            "available": pca_basis.available,
            "path": os.path.relpath(pca_basis.path, ROOT),
        },
        "visual_centering": {
            "available": visual_centering.available,
            "path": os.path.relpath(visual_centering.path, ROOT),
        },
    }
    if pca_basis.available:
        try:
            pca_basis.load()
            status["pca_basis"]["variance_explained"] = pca_basis.variance_explained
        except Exception:  # noqa: BLE001
            pass
    return status
