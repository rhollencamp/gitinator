.PHONY: help setup format lint test dev clean pr

help:
	@echo "Available commands:"
	@echo "  make setup    - Set up venv, update pip, install dev dependencies"
	@echo "  make format   - Format code with ruff"
	@echo "  make lint     - Lint code with ruff"
	@echo "  make test     - Run Django tests"
	@echo "  make dev      - Run Django development server"
	@echo "  make clean    - Remove cache files and directories"
	@echo "  make pr       - Run all PR checks (format, lint, test) without auto-fixing"

setup:
	python3.11 -m venv venv
	. venv/bin/activate && pip install --upgrade pip
	. venv/bin/activate && pip install -e ".[dev]"

format:
	. venv/bin/activate && ruff format .

lint:
	. venv/bin/activate && ruff check --fix .

test:
	. venv/bin/activate && python manage.py test

pr:
	. venv/bin/activate && ruff format --check .
	. venv/bin/activate && ruff check .
	. venv/bin/activate && python manage.py test

dev:
	. venv/bin/activate && python manage.py runserver

clean:
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name "*.pyc" -delete
	rm -rf .ruff_cache
