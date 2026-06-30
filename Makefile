# Makefile for the Patient Deterioration Detector.
#
# Quick start:
#   make dev      # set up everything (once) + run backend + frontend locally
#
# `make dev` brings up the exact local dev setup:
#   - FastAPI backend (uvicorn --reload)  -> http://localhost:8000  (docs at /docs)
#   - React dashboard (vite dev server)   -> http://localhost:5173  (proxies /api -> :8000)
# Open http://localhost:5173 in your browser.

APP_DIR      := deterioration-detector
VENV         := $(APP_DIR)/.venv
PY           := $(VENV)/bin/python
PIP          := $(VENV)/bin/pip
UVICORN      := $(VENV)/bin/uvicorn
FRONTEND     := $(APP_DIR)/frontend
DB           := $(APP_DIR)/data/processed/labs.duckdb

.DEFAULT_GOAL := dev

.PHONY: dev setup venv deps db frontend-deps backend frontend test clean

## dev: one command — install deps, build the DB if missing, run backend + frontend
dev: setup
	@echo ""
	@echo "==> Starting backend (:8000) and frontend (:5173)..."
	@echo "==> Open http://localhost:5173   (Ctrl-C to stop both)"
	@echo ""
	@trap 'kill 0' INT TERM EXIT; \
	( cd $(APP_DIR) && .venv/bin/uvicorn src.api.main:app --reload --port 8000 ) & \
	( cd $(FRONTEND) && npm run dev ) & \
	wait

## setup: prepare the local environment (venv, python deps, db, node modules)
setup: venv deps db frontend-deps

## venv: create the Python virtualenv if it doesn't exist
venv:
	@test -d $(VENV) || python3 -m venv $(VENV)

## deps: install Python dependencies into the venv
deps: venv
	@$(PIP) install --quiet --upgrade pip
	@$(PIP) install --quiet -r $(APP_DIR)/requirements.txt

## db: build the DuckDB + risk scores if the database is missing
db:
	@if [ ! -f $(DB) ]; then \
		echo "==> Building labs.duckdb (first run)..."; \
		cd $(APP_DIR) && .venv/bin/python scripts/build_db.py && .venv/bin/python scripts/build_risk.py; \
	else \
		echo "==> labs.duckdb already present (skipping build)."; \
	fi

## frontend-deps: install node modules if they're missing
frontend-deps:
	@test -d $(FRONTEND)/node_modules || ( cd $(FRONTEND) && npm install )

## backend: run only the FastAPI backend
backend: deps db
	@cd $(APP_DIR) && .venv/bin/uvicorn src.api.main:app --reload --port 8000

## frontend: run only the Vite dev server
frontend: frontend-deps
	@cd $(FRONTEND) && npm run dev

## test: run the pytest suite
test: deps
	@cd $(APP_DIR) && .venv/bin/pytest -q

## clean: remove the built database (forces a rebuild on next run)
clean:
	@rm -f $(DB)
	@echo "==> Removed $(DB)"
