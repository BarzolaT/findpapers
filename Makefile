.PHONY: help clean setup test test_report lint format

VENV ?= venv
VENV_BIN = $(VENV)/bin
PYTHON = $(VENV_BIN)/python
PIP = $(VENV_BIN)/pip
POETRY = $(VENV_BIN)/poetry
PYTEST_ARGS ?=
TARGET ?= .

-include .env
export $(shell [ -f .env ] && sed 's/=.*//' .env)

help:
	@echo "make clean"
	@echo "       clean project removing unnecessary files"
	@echo "make setup"
	@echo "       prepare environment"
	@echo "make lint [TARGET='path']"
	@echo "       run lint and formatting checks (optional: specify target path)"
	@echo "       examples: make lint TARGET='findpapers/models'"
	@echo "                 make lint TARGET='findpapers/models/query.py'"
	@echo "make format [TARGET='path']"
	@echo "       auto-fix formatting and lint issues (optional: specify target path)"
	@echo "       examples: make format TARGET='findpapers/models'"
	@echo "                 make format TARGET='tests/unit/test_query.py'"
	@echo "make test [PYTEST_ARGS='args']"
	@echo "       run tests (optional: pass additional pytest arguments)"
	@echo "       examples: make test PYTEST_ARGS='-k test_name'"
	@echo "                 make test PYTEST_ARGS='tests/unit/test_query.py::TestClass -v'"
	@echo "make test_report"
	@echo "       run tests and save tests and coverag reports"

setup:
	@python -m venv $(VENV)
	@$(PIP) install --upgrade pip poetry
	@POETRY_VIRTUALENVS_CREATE=false $(POETRY) install --with dev --no-interaction --no-ansi -vvv
	@touch poetry.lock

clean:
	@rm -rf build dist .eggs *.egg-info
	@rm -rf .benchmarks .coverage reports htmlcov .tox
	@find . -type d -name '.mypy_cache' -exec rm -rf {} +
	@find . -type d -name '__pycache__' -exec rm -rf {} +
	@find . -type d -name '*pytest_cache*' -exec rm -rf {} +
	@find . -type f -name "*.py[co]" -exec rm -rf {} +

test:
	@POETRY_VIRTUALENVS_CREATE=false $(POETRY) run pytest --durations=3 -v --cov=${PWD}/findpapers $(PYTEST_ARGS)

test_report:
	@POETRY_VIRTUALENVS_CREATE=false $(POETRY) run pytest --durations=3 -v --cov=${PWD}/findpapers --cov-report xml:reports/coverage.xml --junitxml=reports/tests.xml $(PYTEST_ARGS)

lint:
	@POETRY_VIRTUALENVS_CREATE=false $(POETRY) run ruff check $(TARGET)
	@POETRY_VIRTUALENVS_CREATE=false $(POETRY) run isort --check-only $(TARGET)
	@POETRY_VIRTUALENVS_CREATE=false $(POETRY) run black --check $(TARGET)
	@if [ "$(TARGET)" = "." ]; then \
		MYPYPATH=typings POETRY_VIRTUALENVS_CREATE=false $(POETRY) run mypy findpapers tests/unit; \
	else \
		MYPYPATH=typings POETRY_VIRTUALENVS_CREATE=false $(POETRY) run mypy $(TARGET); \
	fi

format:
	@POETRY_VIRTUALENVS_CREATE=false $(POETRY) run ruff check $(TARGET) --fix
	@POETRY_VIRTUALENVS_CREATE=false $(POETRY) run isort $(TARGET)
	@POETRY_VIRTUALENVS_CREATE=false $(POETRY) run black $(TARGET)
