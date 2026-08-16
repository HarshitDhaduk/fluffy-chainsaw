.PHONY: install demo dev test lint dashboard

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

dashboard: ## Run the Next.js dashboard on :3000 (expects `make dev` on :8080)
	cd dashboard && npm install && npm run dev
