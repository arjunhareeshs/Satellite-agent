.PHONY: help install install-gpu install-models verify-models up down \
        aoi vectors search-s2 download-s2 search-s1 download-s1 cdse \
        preprocess chips entities embeddings index-vector index-spatial \
        index-temporal relations data-all seed test eval benchmark \
        run-backend run-frontend types clean clean-data

PY := .venv/Scripts/python.exe
PIP := .venv/Scripts/python.exe -m pip

help:
	@echo "TRINETRA — Command Line Operations"
	@echo ""
	@echo "  SETUP"
	@echo "    make install        - Create .venv and install Python dependencies (CPU torch)"
	@echo "    make install-gpu    - Same, but install CUDA 12.1 torch first (RTX 2050)"
	@echo "    make install-models - Download real model weights, write MANIFEST.json"
	@echo "    make verify-models  - Recompute MANIFEST digests against files on disk"
	@echo "    make up             - Start PostGIS, Qdrant and TileServer"
	@echo "    make down           - Stop containers"
	@echo ""
	@echo "  DATA PIPELINE (in order; 'make data-all' runs the lot)"
	@echo "    make aoi            - 01  Validate AOI, derive canonical grid"
	@echo "    make vectors        - 02  Load OSM reference vectors into PostGIS"
	@echo "    make search-s2      - 03  Search Sentinel-2 L2A (Earth Search)"
	@echo "    make cdse           - 03b Cross-reference scenes to Copernicus product IDs"
	@echo "    make download-s2    - 04  Download S2 AOI clips as COGs"
	@echo "    make search-s1      - 05  Search Sentinel-1 RTC (Planetary Computer)"
	@echo "    make download-s1    - 06  Download S1 AOI clips as COGs"
	@echo "    make preprocess     - 07/08  Cloud mask, co-register, harmonize"
	@echo "    make chips          - 09  Georeferenced 256px chips"
	@echo "    make entities       - 10  Segment chips into geo-objects"
	@echo "    make embeddings     - 11  Prithvi + RemoteCLIP embeddings, fit PCA"
	@echo "    make index-vector   - 12  Qdrant HNSW, two named vectors"
	@echo "    make index-spatial  - 13  PostGIS tables + GiST indexes"
	@echo "    make index-temporal - 14  Parquet trajectories"
	@echo "    make relations      - 15  Distance-to-water/road via PostGIS"
	@echo ""
	@echo "  RUN"
	@echo "    make run-backend    - FastAPI on :8000"
	@echo "    make run-frontend   - Next.js on :3000"
	@echo "    make types          - Regenerate frontend types from the OpenAPI schema"
	@echo ""
	@echo "  VERIFY"
	@echo "    make test           - pytest suite"
	@echo "    make eval           - Quantitative evaluation against ground truth"
	@echo "    make benchmark      - Measure and write build_report.json"
	@echo "    make seed           - Load the demo fixture (development only)"

# ------------------------------------------------------------------ setup

install:
	python -m venv .venv
	$(PIP) install --upgrade pip setuptools wheel
	$(PIP) install -r requirements.txt

install-gpu:
	python -m venv .venv
	$(PIP) install --upgrade pip setuptools wheel
	$(PIP) install torch==2.5.1 torchvision==0.20.1 --index-url https://download.pytorch.org/whl/cu121
	$(PIP) install -r requirements.txt

install-models:
	$(PY) scripts/00_download_models.py

verify-models:
	$(PY) scripts/00_download_models.py --verify

up:
	docker compose up -d

down:
	docker compose down

# ------------------------------------------------------------------ data

aoi:
	$(PY) scripts/01_define_aoi.py

vectors:
	$(PY) scripts/02_load_reference_vectors.py

search-s2:
	$(PY) scripts/03_search_sentinel2.py

cdse:
	$(PY) scripts/03b_search_cdse.py

download-s2:
	$(PY) scripts/04_download_sentinel2.py

search-s1:
	$(PY) scripts/05_search_sentinel1.py

download-s1:
	$(PY) scripts/06_download_sentinel1.py

preprocess:
	$(PY) scripts/07_preprocess_s2.py
	$(PY) scripts/08_preprocess_s1.py

chips:
	$(PY) scripts/09_create_chips.py

entities:
	$(PY) scripts/10_extract_entities.py

embeddings:
	$(PY) scripts/11_generate_embeddings.py

index-vector:
	$(PY) scripts/12_build_vector_index.py

index-spatial:
	$(PY) scripts/13_build_spatial_index.py

index-temporal:
	$(PY) scripts/14_build_temporal_index.py

relations:
	$(PY) scripts/15_compute_relations.py

data-all: aoi vectors search-s2 cdse download-s2 search-s1 download-s1 \
          preprocess chips entities embeddings index-vector index-spatial \
          index-temporal relations
	@echo "Archive build complete. Run 'make benchmark' to measure it."

# ------------------------------------------------------------------ run

run-backend:
	.venv/Scripts/uvicorn.exe backend.main:app --host 0.0.0.0 --port 8000 --reload

run-frontend:
	cd frontend && npm run dev

types:
	cd frontend && npm run gen:types

# ------------------------------------------------------------------ verify

seed:
	$(PY) scripts/seed_demo_data.py

test:
	.venv/Scripts/pytest.exe test/ -v

eval:
	$(PY) eval/run_eval.py

benchmark:
	$(PY) scripts/17_run_benchmark.py

# ------------------------------------------------------------------ clean

clean:
	-rm -rf .pytest_cache
	-find . -type d -name __pycache__ -prune -exec rm -rf {} +
	-rm -rf frontend/.next
	@echo "Removed caches and build output. Data and models are untouched."

clean-data:
	@echo "This deletes every downloaded scene and derived product."
	@echo "Models and configuration are untouched. Ctrl-C to abort."
	@sleep 5
	-rm -rf data/raw/sentinel1 data/raw/sentinel2 data/processed
	@echo "Data cleared. Re-run 'make data-all' to rebuild."
