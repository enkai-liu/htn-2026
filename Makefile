PY ?= /usr/local/bin/python3.12
VENV := backend/.venv
BIN := $(VENV)/bin

.PHONY: setup backend frontend test smoke apply ingest-tier0 ingest-tier1 ingest-tier2 measure calibrate search bench secret-scan setup-jiuwen backend-jiuwen test-jiuwen

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

# Tier 0 (~15 MB download): recent Devpost projects + YC + seeded known prior art. Proves the whole path end to end.
ingest-tier0: $(VENV)/.ok
	$(BIN)/python -m ingest.download_hf --only twangodev hackathons --yes
	$(BIN)/python -m ingest.load_yc
	$(BIN)/python -m ingest.load_devpost_recent
	$(BIN)/python -m ingest.seed_known_prior_art

# Measure Elastic Inference Service throughput BEFORE sizing Tier 1.
measure: $(VENV)/.ok
	$(BIN)/python -m ingest.measure_eis

# Tier 1 (372 MB download): up to TIER1 Devpost projects with Jina embeddings, winners first, newest first. Resumable.
TIER1 ?= 40000
ingest-tier1: $(VENV)/.ok
	$(BIN)/python -m ingest.download_hf --only alvanlii --yes
	mkdir -p logs
	caffeinate -i $(BIN)/python -m ingest.load_devpost_hf --tier 1 --limit $(TIER1) --resume 2>&1 | tee -a logs/ingest.log

# Tier 2: everything else, BM25-only (minutes). Pass the SAME limit as Tier 1.
ingest-tier2: $(VENV)/.ok
	$(BIN)/python -m ingest.load_devpost_hf --tier 2 --limit $(TIER1) --resume

calibrate: $(VENV)/.ok
	cd backend && ../$(BIN)/python -m app.search.calibration build --n 300

search: $(VENV)/.ok
	cd backend && ../$(BIN)/python -m app.search.hybrid "$(Q)" --size 10

bench: $(VENV)/.ok
	$(BIN)/python scripts/bench_ideas.py

secret-scan:
	bash scripts/secret_scan.sh

# openJiuwen host lives in its own venv (86 dependencies); ORCHESTRATOR=jiuwen needs the backend started from it.
JW := backend/.venv-jiuwen
setup-jiuwen:
	$(PY) -m venv $(JW)
	$(JW)/bin/pip install -q --upgrade pip
	$(JW)/bin/pip install -q -e "backend[dev,jiuwen]"

backend-jiuwen:
	cd backend && ORCHESTRATOR=jiuwen ../$(JW)/bin/uvicorn app.main:app --port $${BACKEND_PORT:-8000}

test-jiuwen:
	cd backend && ../$(JW)/bin/pytest -q -p no:warnings tests/test_pipeline_offline.py
