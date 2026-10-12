.PHONY: install data lint test eval build api console up down
install:
	pip install -r requirements-dev.txt
data:      ## regenerate ERP extract, documents, sanctions list and gold annotations
	python -m sckg.data.generator
lint:
	ruff check .
test:
	pytest -q
eval:
	python -m sckg.eval.run --gate
build:
	python -m sckg.cli build
api:
	uvicorn sckg.api:app --reload
console:
	streamlit run streamlit_app.py
up:
	cp -n .env.example .env || true; docker compose up --build -d
down:
	docker compose down
