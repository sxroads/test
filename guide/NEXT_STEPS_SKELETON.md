# Paynkolay Sanal POS - Next Steps Project Skeleton

This skeleton defines the remaining work needed to move the project from a strong
mocked/local framework to a tester-ready and sandbox-proven delivery.

## Current Baseline

The project already has:

- Python automation framework with strict config, typed models, Paynkolay client, flows,
  callbacks, 3DS helpers, scenario catalogues, reporting sanitization, and tests.
- FastAPI web UI for browser-based payment submission.
- Web payment session state.
- Paynkolay form initialization through `/v1/Payment`.
- 3DS provider form rendering from raw/base64 `BANK_REQUEST_MESSAGE`.
- Success/fail return URL handling with `hashDataV2` verification.
- Optional external sanitized event logging.
- Makefile commands for local validation, scale demo, sandbox readiness, web UI, and reports.

Latest known focused validation:

```text
poetry run pytest tests/api
33 passed
```

## Completion Roadmap

### Phase 7 - Tester Reports UI

Goal:

- Turn `/reports` into a useful tester screen instead of a static page.

Code areas:

- `src/paynkolay_pos/api/routes/reports.py`
- `src/paynkolay_pos/api/schemas.py`
- `src/paynkolay_pos/web/templates/report.html`
- `src/paynkolay_pos/web/static/js/api-client.js`
- optional: `src/paynkolay_pos/web/static/js/reports.js`
- `src/paynkolay_pos/web/static/css/app.css`
- `tests/api/test_web_app.py`

Tasks:

- Show `GET /api/reports/latest` status on the page.
- Show report path and entrypoint when available.
- Show clear unavailable state when report has not been generated.
- Add a tester action/link for opening or generating the report if the chosen approach is safe.
- Keep report paths local and do not expose sensitive raw evidence.

Acceptance criteria:

- `/reports` loads without private config.
- Report status updates dynamically from `/api/reports/latest`.
- If `allure-report/index.html` exists, the UI shows it as available.
- If it does not exist, the UI gives a clear not-generated state.
- API and web tests pass.

Validation:

```bash
make web-test
poetry run pytest tests/api
```

### Phase 8 - Tester Result And Payment Lookup UI

Goal:

- Make the tester workflow complete after payment submission.

Code areas:

- `src/paynkolay_pos/web/templates/result.html`
- `src/paynkolay_pos/web/static/js/api-client.js`
- optional: `src/paynkolay_pos/web/static/js/result.js`
- `src/paynkolay_pos/api/routes/payments.py`
- `src/paynkolay_pos/web/static/css/app.css`
- `tests/api/test_web_app.py`

Tasks:

- Load `order_id` from the result page query string.
- Fetch `/api/payments/{order_id}` and render sanitized session state.
- Show final state, amount, masked PAN, provider reference, failure reason, and 3DS link when relevant.
- Add an order lookup input for testers.
- Keep full PAN, CVV, OTP, secrets, hashes, and raw 3DS HTML out of the UI.

Acceptance criteria:

- Tester can submit a payment, follow result link, and see sanitized state.
- Tester can manually look up an order ID.
- Unknown order IDs show a clean error state.
- No sensitive values appear in rendered HTML or JSON responses.

Validation:

```bash
make web-test
poetry run pytest tests/api
```

### Phase 9 - Private Sandbox Input Preparation

Goal:

- Prepare real sandbox execution inputs outside Git.

Private files:

- `/path/outside/git/paynkolay-settings.json`
- `/path/outside/git/sandbox-scenarios.json`
- optional private 100+ card catalogue file if separated from runtime config.

Required private inputs:

- Sandbox/UAT base URL.
- Sales `sx`.
- PaymentList `sx`, if different.
- Cancel/refund `sx`, if different.
- Merchant secret/hash key.
- Merchant ID and terminal ID, if required by the selected flow.
- HTTPS success URL reachable by Paynkolay.
- HTTPS fail URL reachable by Paynkolay.
- Callback URL, if callback delivery is separate from success/fail redirects.
- Real callback payload sample.
- Callback signature algorithm and field order.
- Approved sandbox cards and expected OTP values.
- 3DS selector/flow details.
- MoTo and installment rules.
- Cancel/refund timing and amount rules.

Acceptance criteria:

- Private config is schema-valid.
- Config includes at least 100 cards when final delivery requires that proof.
- Scenario aliases match configured card aliases.
- Placeholder values are removed.
- No private credentials or full card data are committed.

Validation:

```bash
export PAYNKOLAY_CONFIG_FILE=/path/outside/git/paynkolay-settings.json
export PAYNKOLAY_SCENARIO_CATALOG=/path/outside/git/sandbox-scenarios.json
make sandbox-ready
```

### Phase 10 - Guarded Real Sandbox E2E

Goal:

- Prove the framework against real Paynkolay sandbox/UAT flows.

Code areas:

- `tests/sandbox/test_sandbox_e2e_skeleton.py`
- `src/paynkolay_pos/clients/paynkolay_client.py`
- `src/paynkolay_pos/three_ds/challenge.py`
- `src/paynkolay_pos/callbacks/receiver.py`
- `src/paynkolay_pos/models/paynkolay_results.py`
- `src/paynkolay_pos/reporting/evidence.py`

First smoke flow:

1. Build one payment request from private config and scenario data.
2. Send `/v1/Payment`.
3. Complete 3DS if required.
4. Parse success/fail return.
5. Verify `hashDataV2`.
6. Query `/Payment/PaymentList`.
7. Cross-check order ID, amount, currency, reference code, and final status.
8. Capture callback if callback contract is available.
9. Attach sanitized evidence only.

Required real scenarios:

- Successful 3DS payment.
- Failed or declined 3DS payment.
- Successful MoTo payment.
- Successful installment payment.
- PaymentList status verification.
- Cancel/refund.

Safety gate:

```bash
export PAYNKOLAY_ENABLE_LIVE_E2E=1
```

Acceptance criteria:

- Real sandbox tests remain skipped unless explicitly enabled.
- Real calls never run from default `make test`.
- Sanitized evidence is attached for requests, responses, status checks, and callbacks.
- Sensitive fields are masked or redacted.
- Provider assumptions are updated based on real response samples.

Validation:

```bash
export PAYNKOLAY_CONFIG_FILE=/path/outside/git/paynkolay-settings.json
export PAYNKOLAY_SCENARIO_CATALOG=/path/outside/git/sandbox-scenarios.json
export PAYNKOLAY_ENABLE_LIVE_E2E=1
make sandbox
```

### Phase 11 - Final Reporting Evidence

Goal:

- Produce delivery-ready HTML report evidence.

Code areas:

- `src/paynkolay_pos/reporting/evidence.py`
- `tests/reporting/`
- `README.md`
- `guide/PROJECT_REPORT.md`
- `guide/TEST_AND_REPORT_COMMANDS.md`

Tasks:

- Generate local/mock Allure report.
- Generate sandbox Allure report after private sandbox execution.
- Verify report does not expose full PAN, CVV, OTP, `sx`, API keys, secrets, hashes, or raw 3DS HTML.
- Document report generation and opening steps.
- Add final sandbox run results to the project report.

Acceptance criteria:

- `make report` produces `allure-report/`.
- `make sandbox-report` works with private sandbox inputs.
- Report includes positive, negative, 3DS, MoTo, installment, status, and cancel/refund evidence.
- Sensitive data masking is proven by tests and manual inspection.

Validation:

```bash
make report

export PAYNKOLAY_CONFIG_FILE=/path/outside/git/paynkolay-settings.json
export PAYNKOLAY_SCENARIO_CATALOG=/path/outside/git/sandbox-scenarios.json
export PAYNKOLAY_ENABLE_LIVE_E2E=1
make sandbox-report
```

### Phase 12 - Final Documentation And Handoff

Goal:

- Make the project understandable and runnable by a tester or reviewer.

Docs to finalize:

- `README.md`
- `guide/PROJECT_REPORT.md`
- `guide/TEST_AND_REPORT_COMMANDS.md`
- `guide/REAL_SANDBOX_HANDOFF.md`
- optional screenshots or sanitized report references.

Tasks:

- Separate local/mock commands from real sandbox commands.
- Document tester UI workflow.
- Document required private environment variables.
- Document one-click commands.
- Document known limitations and external dependencies.
- Record final validation output.

Acceptance criteria:

- A reviewer can run local tests without private credentials.
- A tester can start the web UI and submit a payment with private sandbox config.
- Sandbox execution remains guarded and explicit.
- Final report explains what is implemented, what was proven locally, and what was proven against sandbox.

Validation:

```bash
make check
make web-test
make report
```

## Recommended Immediate Next Task

Start with Phase 7:

```text
Implement dynamic Reports UI using the existing GET /api/reports/latest endpoint.
```

Reason:

- It is not blocked by Paynkolay credentials.
- It improves tester handoff immediately.
- It closes one of the clearly documented local gaps.
- It is small enough to finish and verify before real sandbox work.

## Definition Of Done For The Whole Project

The project can be considered complete when:

- Local/mock framework checks pass.
- Tester UI supports payment submission, result lookup, 3DS handoff, and reports status.
- Private sandbox readiness passes with real inputs.
- Required real sandbox payment families have been executed.
- PaymentList verification and cancel/refund are proven.
- Callback behavior is verified or explicitly documented as unavailable.
- Allure report evidence is generated.
- Sensitive data masking is verified.
- README and project report contain final runnable instructions and validation results.
