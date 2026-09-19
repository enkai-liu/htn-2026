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
