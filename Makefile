PY ?= /usr/local/bin/python3.12
VENV := backend/.venv
BIN := $(VENV)/bin

.PHONY: setup backend frontend test smoke apply ingest-tier0 bench secret-scan

setup: $(VENV)/.ok frontend/node_modules

$(VENV)/.ok: backend/pyproject.toml
	$(PY) -m venv $(VENV)
	$(BIN)/pip install -q --upgrade pip
	$(BIN)/pip install -q -e "backend[dev]"
	touch $@

frontend/node_modules: frontend/package.json
	cd frontend && pnpm install

backend: $(VENV)/.ok
	cd backend && ../$(BIN)/uvicorn app.main:app --reload --port $${BACKEND_PORT:-8000}

frontend: frontend/node_modules
	cd frontend && pnpm dev

test: $(VENV)/.ok
	cd backend && ../$(BIN)/pytest -q

smoke:
	bash scripts/smoke_all.sh

apply: $(VENV)/.ok
	$(BIN)/python elastic/apply.py

ingest-tier0: $(VENV)/.ok
	$(BIN)/python -m ingest.load_yc
	$(BIN)/python -m ingest.load_devpost_recent
	$(BIN)/python -m ingest.seed_known_prior_art

bench: $(VENV)/.ok
	$(BIN)/python scripts/bench_ideas.py

secret-scan:
	bash scripts/secret_scan.sh
