.PHONY: install test run migrate docker-up docker-down

install:
	python -m pip install -r requirements.txt

test:
	pytest -q

run:
	uvicorn app.main:app --reload

migrate:
	alembic upgrade head

docker-up:
	docker compose up --build

docker-down:
	docker compose down
