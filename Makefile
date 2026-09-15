.PHONY: help up down test eval benchmark seed run-backend run-frontend clean

help:
	@echo "TRINETRA Command Line Operations:"
	@echo "  make up           - Spin up PostGIS, Qdrant, and TileServer in Docker"
	@echo "  make down         - Stop Docker containers"
	@echo "  make seed         - Seed realistic Delhi-NCR Yamuna data & trajectories"
	@echo "  make test         - Run full pytest test suite"
	@echo "  make eval         - Run quantitative evaluation against ground truth"
	@echo "  make benchmark    - Run system benchmark and generate build_report.json"
	@echo "  make run-backend  - Start FastAPI backend server"
	@echo "  make run-frontend - Start Next.js frontend dev server"

up:
	docker-compose up -d

down:
	docker-compose down

seed:
	python scripts/seed_demo_data.py

test:
	pytest test/ -v

eval:
	python eval/run_eval.py

benchmark:
	python scripts/17_run_benchmark.py

run-backend:
	uvicorn backend.main:app --host 0.0.0.0 --port 8000 --reload

run-frontend:
	cd frontend && npm run dev
