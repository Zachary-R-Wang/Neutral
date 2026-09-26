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
.PHONY: help dev test eval lint dataset clean deploy email

help:
	@echo ""
	@echo "  Neutral"
	@echo ""
	@echo "    make dev      Start Neutral in your browser."
	@echo "    make check    Check the setup and that the API key works."
	@echo "    make test     Run the tests, including the safety invariants."
	@echo "    make eval     Measure divergence and write a report."
	@echo "    make dataset  Print the matched prompt pairs to check them by eye."
	@echo "    make lint     Check code style."
	@echo "    make deploy   Test, then put the current version on neutralai.app."
	@echo "    make email    Connect Resend, so password reset emails can be sent."
	@echo ""

.venv:
	@echo "Setting up the Python environment (this happens once)..."
	@$(UV) sync --extra dev

dev: .venv
	@$(UV) sync --extra dev --quiet
	@$(RUN) -m neutral.eval.cli doctor --offline --web
	@echo ""
	@echo "  Starting Neutral at http://127.0.0.1:8000  (press Ctrl-C to stop)"
	@echo ""
	@$(RUN) -m uvicorn neutral.web.app:app --host 127.0.0.1 --port 8000 --log-level warning --reload --reload-dir src

check: .venv
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

# Nothing reaches the live site unless the tests and the linter pass first.
#
# --depot-scope=app builds on a builder belonging to this app rather than the one shared
# across the account. On 2026-09-25 the shared one wedged - every deploy hung at
# "Waiting for depot builder" or failed with a 500 - and an app-scoped one worked first
# time. Each step is
# its own line, so a failure stops make outright - piping a check into something else
# would report the last command's success and carry on past it.
deploy: .venv
	@command -v flyctl >/dev/null 2>&1 || { \
		echo ""; \
		echo "  flyctl is not installed. Install it with:  brew install flyctl"; \
		echo "  then sign in with:                         flyctl auth login"; \
		echo ""; exit 1; }
	@echo "Checking code style..."
	@$(PY) -m ruff check src tests tools
	@$(PY) -m ruff format --check src tests tools
	@echo "Running the tests..."
	@$(RUN) tools/run_tests.py
	@echo ""
	@echo "Deploying to neutralai.app. This takes a few minutes."
	@flyctl deploy --remote-only --depot-scope=app --now || { \
		echo ""; \
		echo "  The deploy failed on Fly's side, not in this code - the tests passed."; \
		echo "  Usually temporary. Wait a few minutes and run make deploy again."; \
		echo "  Their status page: https://status.flyio.net"; \
		echo ""; exit 1; }
	@echo ""
	@echo "  Live at https://neutralai.app"

# Turns on password reset. Asks for the Resend key with typing hidden, so it never
# appears on screen, in shell history, or anywhere it could be copied from - and hands
# it straight to Fly as a secret. It is never written to a file in this repository.
email:
	@command -v flyctl >/dev/null 2>&1 || { echo "  flyctl is not installed: brew install flyctl"; exit 1; }
	@echo ""
	@echo "  This needs a Resend account with neutralai.app verified as a sending domain."
	@echo "  If you have not done that yet, stop here (Ctrl-C) - see the steps in LIMITATIONS.md."
	@echo ""
	@printf "  Paste your Resend API key (nothing will show as you paste): "; \
	stty -echo; read key; stty echo; echo ""; \
	case "$$key" in re_*) ;; *) echo ""; echo "  That does not look like a Resend key - they start with re_. Nothing was changed."; exit 1;; esac; \
	flyctl secrets set -a neutralai RESEND_API_KEY="$$key" NEUTRAL_MAIL_FROM="Neutral <noreply@neutralai.app>" \
	  && { echo ""; echo "  Done. Neutral restarts to pick this up, which signs everyone out once."; \
	       echo "  Try it: https://neutralai.app/forgot"; echo ""; }

clean:
	@rm -rf .pytest_cache .ruff_cache reports/*.json reports/*.html
	@find . -name __pycache__ -type d -prune -exec rm -rf {} +
	@echo "Removed caches and generated reports. The dataset and results are untouched."
