# TRINETRA backend — FastAPI + the ML/geospatial stack.
#
# This did not exist before; the backend was only ever run with a bare
# `uvicorn backend.main:app` on the host. Building this image is what makes
# "containerized deployment" an actual option rather than an implication of
# docker-compose.yml existing.
FROM python:3.11-slim AS base

# GDAL/rasterio's wheels bundle their own GDAL, so no system libgdal is
# needed; a C toolchain is still required for the packages that don't ship
# manylinux wheels (a handful of transitive geospatial deps do).
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
# CPU-only torch in the image by default -- a GPU deployment mounts its own
# CUDA base image and reinstalls torch, rather than shipping a multi-GB CUDA
# runtime into an image most deployments of this service will run on CPU.
RUN pip install --no-cache-dir torch==2.5.1 torchvision==0.20.1 --index-url https://download.pytorch.org/whl/cpu \
    && pip install --no-cache-dir -r requirements.txt

COPY backend/ backend/
COPY config/ config/
COPY scripts/ scripts/
# models/ and data/ are mounted as volumes at runtime (see docker-compose.yml)
# rather than baked in -- staged weights and a built archive are gigabytes,
# and rebuilding the image on every re-stage would be wasteful.

EXPOSE 8000

HEALTHCHECK --interval=15s --timeout=5s --start-period=30s --retries=3 \
    CMD curl -f http://localhost:8000/api/v1/health || exit 1

CMD ["uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "8000"]
