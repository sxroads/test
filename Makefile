.PHONY: help install check lint type test smoke api three-ds callback scenarios scenarios-file negative sandbox-ready sandbox sandbox-3ds sandbox-moto sandbox-report parallel private-config private-scenarios private-inputs credential-matrix credential-config credential-scenarios uat-scenarios credential-inputs uat-config uat-inputs uat-3ds-smoke uat-parallel-3ds-smoke uat-cancel-smoke credential-scenario-test credential-scenario-report synthetic-cards synthetic-scenarios scale-demo scale-demo-parallel parallel-evidence-summary web uat-web web-test web-check allure-results report clean

PYTEST ?= poetry run pytest
RUFF ?= poetry run ruff check .
MYPY ?= poetry run mypy src tests
UVICORN ?= poetry run uvicorn
ALLURE_RESULTS ?= allure-results
ALLURE_REPORT ?= allure-report
COUNT ?= 100
OUT ?= /tmp/paynkolay-synthetic-cards.json
CONFIG_OUT ?= /tmp/paynkolay-private-settings.json
SCENARIO_COUNT ?= 1000
SCENARIO_OUT ?= /tmp/paynkolay-synthetic-scenarios.json
PRIVATE_SCENARIO_OUT ?= /tmp/paynkolay-private-scenarios.json
MATRIX_OUT ?= /tmp/paynkolay-credential-matrix.json
CREDENTIAL_CONFIG_OUT ?= /tmp/paynkolay-credential-settings.json
CREDENTIAL_SCENARIO_OUT ?= /tmp/paynkolay-credential-scenarios.json
UAT_CONFIG_OUT ?= /tmp/paynkolay-uat-settings.json
PRIVATE_ENV ?= dev
UAT_CARD_COUNT ?= 100
UAT_CALLBACK_BASE_URL ?= https://paynkolay.com.tr/test/callback
UAT_MERCHANT_ID ?= 400001470
UAT_TERMINAL_ID ?= replace-with-uat-terminal-id
UAT_PAYMENT_SX ?= replace-with-uat-payment-sx
UAT_INSTALLMENT_SX ?= replace-with-uat-installment-sx
UAT_LIST_SX ?= replace-with-uat-list-sx
UAT_CANCEL_REFUND_SX ?= replace-with-uat-cancel-refund-sx
UAT_SECRET_KEY ?= replace-with-uat-secret-key
UAT_3DS_SCENARIO_ID ?= credential_yapikredi_visa_9085_3ds_success
UAT_3DS_CARD_FILE ?= credentials/uat_3ds_card.json
UAT_3DS_FORM_BASE_URL ?= https://vpostest.qnb.com.tr/PayforACSSimulator/
UAT_3DS_BROWSER ?=
UAT_PARALLEL_3DS_CARD_ALIAS ?= nkolay_dynamic_otp_visa_6111
UAT_PARALLEL_3DS_COUNT ?= 10
UAT_PARALLEL_3DS_CONCURRENCY ?= 10
UAT_PARALLEL_3DS_AMOUNT ?= 100.00
UAT_PARALLEL_INSTALLMENT_COUNT ?= 1
UAT_PARALLEL_3DS_ARGS ?=
UAT_CANCEL_SCENARIO_ID ?= credential_ziraat_bankas_visa_7894_moto_authorized
SCENARIO_FILE ?=
WEB_HOST ?= 127.0.0.1
WEB_PORT ?= 8000
WEB_RELOAD ?=
WEB_3DS_HEADED ?= 0
WEB_3DS_CLOSE_DELAY ?= 0
PARALLEL_EVIDENCE_DIR ?= reports/parallel-runs
PARALLEL_EVIDENCE_LIMIT ?= 10
PARALLEL_EVIDENCE_RUN_ID ?=

help:
	@echo "Paynkolay Sanal POS automation commands"
	@echo ""
	@echo "Setup:"
	@echo "  make install         Install project dependencies with Poetry"
	@echo ""
	@echo "Validation:"
	@echo "  make check           Run poetry check, ruff, mypy, and pytest"
	@echo "  make lint            Run Ruff"
	@echo "  make type            Run mypy"
	@echo "  make test            Run the full pytest suite"
	@echo "  make parallel        Run the full pytest suite with pytest-xdist"
	@echo ""
	@echo "Focused tests:"
	@echo "  make smoke           Run smoke-marked tests"
	@echo "  make api             Run API-marked tests"
	@echo "  make three-ds        Run 3D Secure-marked tests"
	@echo "  make callback        Run callback-marked tests"
	@echo "  make scenarios       Run data-driven scenario catalogue tests"
	@echo "  make scenarios-file  Run scenario tests from SCENARIO_FILE"
	@echo "  make negative        Run negative-marked tests"
	@echo "  make sandbox-ready   Validate private sandbox config without payments"
	@echo "  make sandbox         Run private Paynkolay sandbox skeleton/live tests"
	@echo "  make sandbox-3ds     Run private sandbox 3DS tests"
	@echo "  make sandbox-moto    Run private sandbox MoTo tests"
	@echo "  make private-config  Create a local-only private config skeleton"
	@echo "  make private-scenarios Create a local-only sandbox scenario catalogue"
	@echo "  make private-inputs  Create matching local-only config and scenarios"
	@echo "  make credential-matrix Build local/mock matrix from ignored credentials"
	@echo "  make credential-config Build local/mock config from ignored credentials"
	@echo "  make credential-scenarios Build scenarios from ignored credentials"
	@echo "  make credential-inputs Build local/mock config and scenarios"
	@echo "  make uat-config      Build UAT config from ignored credentials and provided merchant values"
	@echo "  make uat-inputs      Build UAT config and credential scenario catalogue"
	@echo "  make uat-3ds-smoke   Run one guarded live UAT 3DS browser smoke"
	@echo "  make uat-parallel-3ds-smoke Run guarded live UAT parallel auto-3DS smoke"
	@echo "  make uat-cancel-smoke Run one guarded live UAT MoTo payment and cancel smoke"
	@echo "  make credential-scenario-test Run scenario tests from credential scenarios"
	@echo "  make credential-scenario-report Generate Allure report for credential scenarios"
	@echo "  make synthetic-cards Generate a synthetic cards JSON array"
	@echo "  make synthetic-scenarios Generate a synthetic scenario catalogue"
	@echo "  make scale-demo      Generate 100 cards, 1000 scenarios, then run scenarios"
	@echo "  make scale-demo-parallel Run generated scenarios with pytest-xdist"
	@echo "  make parallel-evidence-summary Summarize persisted parallel run evidence"
	@echo ""
	@echo "Web UI:"
	@echo "  make web             Run the FastAPI web UI"
	@echo "  make uat-web         Build UAT inputs and run the FastAPI web UI against UAT"
	@echo "  make web-test        Run web/API tests"
	@echo "  make web-check       Run lint, type checks, and web/API tests"
	@echo ""
	@echo "Reporting:"
	@echo "  make allure-results  Run tests and write Allure result files"
	@echo "  make report          Generate an Allure HTML report"
	@echo "  make sandbox-report  Generate Allure results for private sandbox tests"
	@echo ""
	@echo "Maintenance:"
	@echo "  make clean           Remove generated local artifacts"

install:
	poetry install --no-interaction

check:
	poetry check
	$(RUFF)
	$(MYPY)
	$(PYTEST)

lint:
	$(RUFF)

type:
	$(MYPY)

test:
	$(PYTEST)

parallel:
	$(PYTEST) -n auto

smoke:
	$(PYTEST) -m smoke

api:
	$(PYTEST) -m api

three-ds:
	$(PYTEST) -m three_ds

callback:
	$(PYTEST) -m callback

scenarios:
	$(PYTEST) -m scenario

scenarios-file:
	@test -n "$(SCENARIO_FILE)" || { echo "SCENARIO_FILE is required. Example: make scenarios-file SCENARIO_FILE=/tmp/scenarios.json"; exit 1; }
	PAYNKOLAY_SCENARIO_CATALOG=$(SCENARIO_FILE) $(PYTEST) -m scenario

negative:
	$(PYTEST) -m negative

sandbox-ready:
	@test -n "$(PAYNKOLAY_CONFIG_FILE)" || { echo "PAYNKOLAY_CONFIG_FILE is required for sandbox readiness checks"; exit 1; }
	poetry run python tools/validate_sandbox_readiness.py

sandbox:
	@test -n "$(PAYNKOLAY_CONFIG_FILE)" || { echo "PAYNKOLAY_CONFIG_FILE is required for sandbox runs"; exit 1; }
	$(PYTEST) -m sandbox

sandbox-3ds:
	@test -n "$(PAYNKOLAY_CONFIG_FILE)" || { echo "PAYNKOLAY_CONFIG_FILE is required for sandbox runs"; exit 1; }
	$(PYTEST) -m "sandbox and three_ds"

sandbox-moto:
	@test -n "$(PAYNKOLAY_CONFIG_FILE)" || { echo "PAYNKOLAY_CONFIG_FILE is required for sandbox runs"; exit 1; }
	$(PYTEST) -m "sandbox and moto"

sandbox-report:
	@test -n "$(PAYNKOLAY_CONFIG_FILE)" || { echo "PAYNKOLAY_CONFIG_FILE is required for sandbox runs"; exit 1; }
	rm -rf $(ALLURE_RESULTS)
	$(PYTEST) -m sandbox --alluredir=$(ALLURE_RESULTS)
	@command -v allure >/dev/null 2>&1 || { echo "Allure CLI is required. Install it with: brew install allure"; exit 1; }
	allure generate $(ALLURE_RESULTS) -o $(ALLURE_REPORT) --clean

private-config:
	poetry run python tools/bootstrap_private_config.py --card-count $(COUNT) --output $(CONFIG_OUT)

private-scenarios:
	poetry run python tools/bootstrap_private_scenarios.py --card-count $(COUNT) --environment $(PRIVATE_ENV) --output $(PRIVATE_SCENARIO_OUT)

private-inputs: private-config private-scenarios
	@echo "Export these before sandbox readiness checks:"
	@echo "  export PAYNKOLAY_CONFIG_FILE=$(CONFIG_OUT)"
	@echo "  export PAYNKOLAY_SCENARIO_CATALOG=$(PRIVATE_SCENARIO_OUT)"
	@echo "  export PAYNKOLAY_ENV=$(PRIVATE_ENV)"

credential-matrix:
	poetry run python tools/build_credential_matrix.py --output $(MATRIX_OUT)

credential-config:
	poetry run python tools/build_credential_config.py --output $(CREDENTIAL_CONFIG_OUT)

uat-config:
	poetry run python tools/build_credential_config.py --environment uat --total-card-count $(UAT_CARD_COUNT) --base-url https://paynkolaytest.nkolayislem.com.tr/Vpos --callback-base-url $(UAT_CALLBACK_BASE_URL) --merchant-id $(UAT_MERCHANT_ID) --terminal-id $(UAT_TERMINAL_ID) --api-key $(UAT_PAYMENT_SX) --installment-api-key $(UAT_INSTALLMENT_SX) --list-api-key $(UAT_LIST_SX) --cancel-refund-api-key $(UAT_CANCEL_REFUND_SX) --secret-key $(UAT_SECRET_KEY) --postman-collection credentials/paynkolay.postman_collection.json --gateway-form credentials/base64.md --installment-service-file credentials/installment/servisler.md --output $(UAT_CONFIG_OUT)

credential-scenarios:
	poetry run python tools/build_credential_scenarios.py --output $(CREDENTIAL_SCENARIO_OUT)

uat-scenarios:
	poetry run python tools/build_credential_scenarios.py --total-card-count $(UAT_CARD_COUNT) --output $(CREDENTIAL_SCENARIO_OUT)

credential-inputs: credential-config credential-scenarios
	@echo "Export these for tester UI local/mock visibility:"
	@echo "  export PAYNKOLAY_CONFIG_FILE=$(CREDENTIAL_CONFIG_OUT)"
	@echo "  export PAYNKOLAY_SCENARIO_CATALOG=$(CREDENTIAL_SCENARIO_OUT)"

uat-inputs: uat-config uat-scenarios
	@echo "Export these for UAT readiness and runs:"
	@echo "  export PAYNKOLAY_CONFIG_FILE=$(UAT_CONFIG_OUT)"
	@echo "  export PAYNKOLAY_SCENARIO_CATALOG=$(CREDENTIAL_SCENARIO_OUT)"
	@echo "  export PAYNKOLAY_ENV=uat"

uat-3ds-smoke: uat-inputs
	PAYNKOLAY_CONFIG_FILE=$(UAT_CONFIG_OUT) PAYNKOLAY_SCENARIO_CATALOG=$(CREDENTIAL_SCENARIO_OUT) PAYNKOLAY_ENV=uat PAYNKOLAY_ENABLE_LIVE_E2E=1 poetry run python tools/run_uat_3ds_smoke.py --scenario-id $(UAT_3DS_SCENARIO_ID) --card-file $(UAT_3DS_CARD_FILE) --form-base-url $(UAT_3DS_FORM_BASE_URL) $(UAT_3DS_BROWSER)

uat-parallel-3ds-smoke: uat-inputs
	PAYNKOLAY_CONFIG_FILE=$(UAT_CONFIG_OUT) PAYNKOLAY_SCENARIO_CATALOG=$(CREDENTIAL_SCENARIO_OUT) PAYNKOLAY_ENV=uat PAYNKOLAY_ENABLE_LIVE_E2E=1 poetry run python tools/run_uat_parallel_3ds_smoke.py --card-alias $(UAT_PARALLEL_3DS_CARD_ALIAS) --count $(UAT_PARALLEL_3DS_COUNT) --concurrency $(UAT_PARALLEL_3DS_CONCURRENCY) --amount $(UAT_PARALLEL_3DS_AMOUNT) --installment-count $(UAT_PARALLEL_INSTALLMENT_COUNT) $(UAT_PARALLEL_3DS_ARGS)

uat-cancel-smoke: uat-inputs
	PAYNKOLAY_CONFIG_FILE=$(UAT_CONFIG_OUT) PAYNKOLAY_SCENARIO_CATALOG=$(CREDENTIAL_SCENARIO_OUT) PAYNKOLAY_ENV=uat PAYNKOLAY_ENABLE_LIVE_E2E=1 poetry run python tools/run_uat_cancel_smoke.py --scenario-id $(UAT_CANCEL_SCENARIO_ID)

credential-scenario-test: credential-config credential-scenarios
	PAYNKOLAY_CONFIG_FILE=$(CREDENTIAL_CONFIG_OUT) PAYNKOLAY_SCENARIO_CATALOG=$(CREDENTIAL_SCENARIO_OUT) $(PYTEST) tests/e2e/test_data_driven_payment_scenarios.py

credential-scenario-report: credential-config credential-scenarios
	rm -rf $(ALLURE_RESULTS)
	PAYNKOLAY_CONFIG_FILE=$(CREDENTIAL_CONFIG_OUT) PAYNKOLAY_SCENARIO_CATALOG=$(CREDENTIAL_SCENARIO_OUT) $(PYTEST) tests/e2e/test_data_driven_payment_scenarios.py --alluredir=$(ALLURE_RESULTS)
	@command -v allure >/dev/null 2>&1 || { echo "Allure CLI is required. Install it with: brew install allure"; exit 1; }
	allure generate $(ALLURE_RESULTS) -o $(ALLURE_REPORT) --clean

synthetic-cards:
	poetry run python tools/generate_synthetic_cards.py --count $(COUNT) --output $(OUT)

synthetic-scenarios:
	poetry run python tools/generate_synthetic_scenarios.py --count $(SCENARIO_COUNT) --output $(SCENARIO_OUT)

scale-demo:
	$(MAKE) synthetic-cards COUNT=$(COUNT) OUT=$(OUT)
	poetry run python tools/generate_synthetic_scenarios.py --count $(SCENARIO_COUNT) --card-count $(COUNT) --output $(SCENARIO_OUT)
	$(MAKE) scenarios-file SCENARIO_FILE=$(SCENARIO_OUT)

scale-demo-parallel:
	$(MAKE) synthetic-cards COUNT=$(COUNT) OUT=$(OUT)
	poetry run python tools/generate_synthetic_scenarios.py --count $(SCENARIO_COUNT) --card-count $(COUNT) --output $(SCENARIO_OUT)
	PAYNKOLAY_SCENARIO_CATALOG=$(SCENARIO_OUT) $(PYTEST) -m scenario -n auto

parallel-evidence-summary:
	@test -z "$(PARALLEL_EVIDENCE_RUN_ID)" || { PAYNKOLAY_PARALLEL_EVIDENCE_DIR=$(PARALLEL_EVIDENCE_DIR) poetry run python tools/summarize_parallel_evidence.py --evidence-dir $(PARALLEL_EVIDENCE_DIR) --run-id $(PARALLEL_EVIDENCE_RUN_ID); exit $$?; }
	PAYNKOLAY_PARALLEL_EVIDENCE_DIR=$(PARALLEL_EVIDENCE_DIR) poetry run python tools/summarize_parallel_evidence.py --evidence-dir $(PARALLEL_EVIDENCE_DIR) --limit $(PARALLEL_EVIDENCE_LIMIT)

web:
	PAYNKOLAY_3DS_AUTOMATION_HEADED=$(WEB_3DS_HEADED) PAYNKOLAY_3DS_AUTOMATION_CLOSE_DELAY=$(WEB_3DS_CLOSE_DELAY) $(UVICORN) paynkolay_pos.api.app:create_app --factory $(WEB_RELOAD) --host $(WEB_HOST) --port $(WEB_PORT)

uat-web: uat-inputs
	PAYNKOLAY_CONFIG_FILE=$(UAT_CONFIG_OUT) PAYNKOLAY_SCENARIO_CATALOG=$(CREDENTIAL_SCENARIO_OUT) PAYNKOLAY_ENV=uat PAYNKOLAY_3DS_AUTOMATION_HEADED=$(WEB_3DS_HEADED) PAYNKOLAY_3DS_AUTOMATION_CLOSE_DELAY=$(WEB_3DS_CLOSE_DELAY) $(UVICORN) paynkolay_pos.api.app:create_app --factory $(WEB_RELOAD) --host $(WEB_HOST) --port $(WEB_PORT)

web-test:
	$(PYTEST) tests/api

web-check:
	$(RUFF)
	$(MYPY)
	$(PYTEST) tests/api

allure-results:
	rm -rf $(ALLURE_RESULTS)
	$(PYTEST) --alluredir=$(ALLURE_RESULTS)

report: allure-results
	@command -v allure >/dev/null 2>&1 || { echo "Allure CLI is required. Install it with: brew install allure"; exit 1; }
	allure generate $(ALLURE_RESULTS) -o $(ALLURE_REPORT) --clean

clean:
	find . -type d \( -name "__pycache__" -o -name ".pytest_cache" -o -name ".mypy_cache" -o -name ".ruff_cache" -o -name "allure-results" -o -name "allure-report" -o -name "reports" \) -prune -exec rm -rf {} +
