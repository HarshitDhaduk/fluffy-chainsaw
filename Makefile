.PHONY: install demo dev test lint dashboard evals evals-live

# Override when the virtualenv isn't activated, e.g.
#   make evals PYTHON=backend/.venv/bin/python PYTEST=backend/.venv/bin/pytest
PYTHON ?= python
PYTEST ?= pytest

install:
	cd backend && pip install -e ".[dev]"

demo: ## Run Meera's journey end-to-end in the terminal (offline)
	cd backend && python scripts/run_demo.py

dev: ## Serve the local walking skeleton on :8080
	cd backend && uvicorn lalfita.local:app --port 8080 --reload

test:
	cd backend && pytest -q

lint:
	cd backend && ruff check .

evals: ## Run the self-healing eval matrix (offline, deterministic) and refresh docs/EVALS.md
	cd backend && LALFITA_OFFLINE=1 $(abspath $(PYTHON)) -m evals.runner
	cp backend/evals/report/EVALS.md docs/EVALS.md

evals-live: ## Run live-model quality evals (spends Gemini quota)
	cd backend && LIVE_EVALS=1 $(abspath $(PYTEST)) -q -m live evals/live -s

evals-durable: ## Kill a real process mid-journey and prove the work survives
	cd backend && $(abspath $(PYTEST)) -q -m durable tests/test_durability.py

evals-soak: ## 50 journeys with random fault cocktails (opt-in, ~5 min)
	cd backend && LALFITA_OFFLINE=1 $(abspath $(PYTHON)) -m evals.soak --iterations 50

dashboard: ## Run the Next.js dashboard on :3000 (expects `make dev` on :8080)
	cd dashboard && npm install && npm run dev
