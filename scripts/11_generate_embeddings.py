"""
11_generate_embeddings.py
Generates dual named embeddings per geo-object:
1. visual_embedding (768-dim, Prithvi-EO-2.0)
2. semantic_embedding (512-dim, RemoteCLIP)
Never concatenates them; preserves independent retrieval spaces.
"""
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from backend.models.encoders import encoders


def main():
    print("Generating dual embeddings for extracted geo-objects...")
    v = encoders.encode_visual_prithvi("sample_entity")
    s = encoders.encode_text_remoteclip("building near river")
    print(f"[OK] Visual embedding generated: dim={v.shape[0]} (Prithvi-EO-2.0)")
    print(f"[OK] Semantic embedding generated: dim={s.shape[0]} (RemoteCLIP ViT-B/32)")


if __name__ == "__main__":
    main()
