.PHONY: setup test-deps test lint

PYTHON ?= python3
VENV_PYTHON = .venv/bin/python

setup:
	$(PYTHON) -m venv .venv
	$(VENV_PYTHON) -m pip install -e '.[dev]'

test-deps: setup
	$(VENV_PYTHON) -m pip install -c config/evaluator-constraints.txt -r config/test-dependencies.txt

test:
	$(VENV_PYTHON) -m pytest -q
	$(VENV_PYTHON) -m ruff check .

lint:
	$(VENV_PYTHON) -m ruff check .

native-eval:
	$(VENV_PYTHON) -m scripts.prepare_native_evaluation
	$(VENV_PYTHON) -m scripts.run_native_evaluation

receipt-workflow:
	$(VENV_PYTHON) -m scripts.receipt_workflow

receipt-agent-workflow:
	$(VENV_PYTHON) -m scripts.receipt_agent_workflow

review:
	$(VENV_PYTHON) -m skillguard.ui.core_server

core-check:
	$(VENV_PYTHON) -m scripts.core_workflow

core-app-check:
	$(VENV_PYTHON) -m scripts.core_app_workflow

security-product-check:
	$(VENV_PYTHON) -m scripts.security_product_workflow

demo-bundle:
	$(VENV_PYTHON) -m scripts.build_demo

demo: demo-bundle
	$(VENV_PYTHON) -m http.server 8769 --bind 127.0.0.1 --directory dist/skillguard-demo

public-live:
	$(VENV_PYTHON) -m scripts.serve_public_backend

review-history:
	$(VENV_PYTHON) -m skillguard.ui.server --store results/integration/local-parser-8fc64684/reviews --review 38277c97edea21841daf6446ad2394af178b29cb538f584c909cd991228e1a01

evaluator-setup:
	$(VENV_PYTHON) -c "import subprocess; assert subprocess.check_output(['git', '-C', '../work/SkillEvaluator', 'rev-parse', 'HEAD'], text=True).strip() == '33eb9dc74a09280bebf6fb4c921d290a0f874713', 'Wrong native evaluator source pin'"
	$(VENV_PYTHON) -m pip install -c config/evaluator-constraints.txt -e '../work/SkillEvaluator[tier3,security]'
