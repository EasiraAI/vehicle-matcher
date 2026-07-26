# One-word operations; `make ci` runs the exact sequence CI runs.
PY ?= .venv/Scripts/python
ifeq ($(OS),)
PY = .venv/bin/python
endif

.PHONY: setup db test test-unit lint typecheck run ci scale

setup:
	python -m venv .venv
	$(PY) -m pip install -e ".[dev]"

db:
	docker compose up -d --wait
	$(PY) scripts/setup_db.py

test-unit:
	$(PY) -m pytest tests/unit -q

test:
	$(PY) -m pytest tests -q

lint:
	$(PY) -m ruff check src tests scripts
	$(PY) -m ruff format --check src tests scripts

typecheck:
	$(PY) -m mypy src

run:
	$(PY) -m vehicle_matcher.cli data/inputs.txt

scale:
	$(PY) scripts/synth_scale.py

ci: lint typecheck test
