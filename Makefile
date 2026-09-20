# Neutral - everything you need to run this project.
#
#   make dev     set it up and check it works
#   make test    prove the safety rules are enforced
#   make eval    measure how much answers change with identity
#
# Nothing else is required. If a task needs more steps than one of these, the task
# is not finished.

UV := $(shell command -v uv 2>/dev/null || echo /opt/homebrew/bin/uv)
PY := .venv/bin/python
# src/ is put on the path explicitly rather than relying on an editable install, which
# is fragile when the project folder name contains a space. See DECISIONS.md.
RUN := PYTHONPATH=src $(PY)

.DEFAULT_GOAL := help
.PHONY: help dev test eval lint dataset clean

help:
	@echo ""
	@echo "  Neutral"
	@echo ""
	@echo "    make dev      Set up the project and check it is ready to run."
	@echo "    make test     Run the tests, including the safety invariants."
	@echo "    make eval     Measure divergence and write a report."
	@echo "    make dataset  Print the matched prompt pairs to check them by eye."
	@echo "    make lint     Check code style."
	@echo ""

.venv:
	@echo "Setting up the Python environment (this happens once)..."
	@$(UV) sync --extra dev

dev: .venv
	@$(UV) sync --extra dev --quiet
	@$(RUN) -m neutral.eval.cli doctor

test: .venv
	@$(RUN) tools/run_tests.py

eval: .venv
	@$(RUN) -m neutral.eval.cli run $(ARGS)

dataset: .venv
	@$(RUN) -m neutral.eval.cli dataset $(ARGS)

lint: .venv
	@$(PY) -m ruff check src tests tools
	@$(PY) -m ruff format --check src tests tools

clean:
	@rm -rf .pytest_cache .ruff_cache reports/*.json reports/*.html
	@find . -name __pycache__ -type d -prune -exec rm -rf {} +
	@echo "Removed caches and generated reports. The dataset and results are untouched."
