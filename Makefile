.PHONY: help clean setup test test_integration test_report lint format

VENV ?= .venv
VENV_BIN = $(VENV)/bin
PYTHON = $(VENV_BIN)/python
PIP = $(VENV_BIN)/pip
POETRY = $(VENV_BIN)/poetry
PYTEST_ARGS ?=
TARGET ?= .

# Ensure poetry run uses our local venv even when the shell has not
# been activated with ``source .venv/bin/activate``.
export VIRTUAL_ENV := $(abspath $(VENV))
export POETRY_VIRTUALENVS_CREATE := false

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
	@echo "make test_integration [PYTEST_ARGS='args']"
	@echo "       run integration/smoke tests that hit real external APIs"
	@echo "make test_report"
	@echo "       run tests and save tests and coverage reports"

setup:
	@python -m venv $(VENV)
	@$(PIP) install --upgrade pip poetry
	@$(POETRY) install --with dev --no-interaction --no-ansi -vvv
	@touch poetry.lock

clean:
	@rm -rf build dist .eggs *.egg-info
	@rm -rf .benchmarks .coverage reports htmlcov .tox
	@find . -type d -name '.mypy_cache' -exec rm -rf {} +
	@find . -type d -name '__pycache__' -exec rm -rf {} +
	@find . -type d -name '*pytest_cache*' -exec rm -rf {} +
	@find . -type f -name "*.py[co]" -exec rm -rf {} +

test:
	@$(POETRY) run pytest --durations=3 -v --cov=${PWD}/findpapers $(PYTEST_ARGS)

test_integration:
	@$(POETRY) run pytest -v -m integration $(PYTEST_ARGS)

test_report:
	@$(POETRY) run pytest --durations=3 -v --cov=${PWD}/findpapers --cov-report xml:reports/coverage.xml --junitxml=reports/tests.xml $(PYTEST_ARGS)

lint:
	@$(POETRY) run ruff check $(TARGET)
	@$(POETRY) run ruff format --check $(TARGET)
	@if [ "$(TARGET)" = "." ]; then \
		MYPYPATH=typings $(POETRY) run mypy findpapers tests/unit; \
	else \
		MYPYPATH=typings $(POETRY) run mypy $(TARGET); \
	fi

format:
	@$(POETRY) run ruff check $(TARGET) --fix
	@$(POETRY) run ruff format $(TARGET)
