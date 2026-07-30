# Paynkolay Virtual POS Test Automation

Paynkolay Virtual POS Test Automation is a quality and validation platform for testing
Paynkolay payment flows in a controlled, repeatable, and reportable way.

The project gives testers a browser-based workspace where they can start payments, complete
3D Secure flows, run many card tests in parallel, inspect results, and review sanitized
evidence without reading logs or touching application code.

It is designed for QA teams, business analysts, and engineers who need to understand whether
Paynkolay payment scenarios work as expected across cards, banks, and payment flows.

## What It Does

- Runs MoTo and 3D Secure payment tests against local/mock or UAT environments.
- Lets users select saved test cards from a UI and execute payment checks.
- Supports parallel card testing for larger validation runs.
- Completes supported 3D Secure simulator flows automatically in the background.
- Verifies payment outcomes through PaymentList.
- Captures cancel/refund smoke evidence.
- Produces sanitized reports and evidence files.
- Keeps card data, OTPs, merchant secrets, hashes, and raw 3DS HTML out of committed files.

## Who Uses It

Business analysts can use the web UI to run repeatable payment checks and read the result
status in plain terms.

QA teams can run baseline regression checks such as 10, 50, or larger parallel batches and
compare pass/fail evidence.

Developers can use the API, CLI tools, and test suite to diagnose provider responses, 3D
Secure behavior, and PaymentList timing issues.

## Main Screens

The web UI is split into four practical areas:

- **Payment**: single payment testing, card selection, MoTo/3DS flow, provider result,
  PaymentList result, and authorization evidence.
- **Parallel**: multi-card parallel test execution with manual or random card selection and
  one run-level installment count.
- **Settings**: runtime environment, editable merchant/payment SX settings, and configured
  card overview.
- **Reports**: Allure status, latest test run summary, credential report execution, and
  saved parallel evidence.

The Payment and Settings screens are intentionally kept operational and compact. Parallel
and Reports are wider and easier to scan for business-facing review sessions.

### Runtime Merchant Settings

The Settings screen can update the active environment's merchant number and primary
Payment/Sales `sx` without changing tracked source files. The merchant number is visible;
the current SX is never returned to the browser. Leaving the password field empty preserves
the configured SX, while entering a value replaces it for new payment runs.

Updates are serialized, validated against the complete runtime settings model, and written
atomically to the private file selected by `PAYNKOLAY_CONFIG_FILE`. Existing parallel runs
keep their credential snapshot. Running `make uat-web` again rebuilds that generated file
from ignored credential inputs and restores their defaults.

The dedicated installment, PaymentList, and cancel/refund SX values are not changed by this
form. Keep the merchant secret and operation-specific SX values aligned with the selected
merchant. Do not expose this unauthenticated local tester UI on a public network.

## 3D Secure Automation

The project supports browser-based 3D Secure automation through Playwright. For normal UI
and parallel testing, automation runs headless by default, so large runs do not open one
visible browser tab per payment.

Supported automatic 3DS behavior includes:

- visible OTP codes rendered on simulator pages,
- configured static OTP values for known test cards,
- controlled form submission after the OTP source is verified,
- safe failure classification when the page requires manual approval or cannot be automated.

The automation does not invent OTPs. If no safe OTP source is available, the payment is left
with a clear diagnostic reason.

## Installment Options

The Payment screen uses deterministic local options in local/mock environments and the real
Paynkolay `Payment/PaymentInstallments` service in UAT. The UAT lookup sends the configured
dedicated installment `sx`, amount, and test card as multipart form data; it does not create
a payment.

Each provider option includes its own opaque `EncodedValue`. When a tester selects an
installment, the UI returns that value to the payment API and the provider form request sends
it together with `installmentNo`. Installment payments above one installment are rejected
before the provider call when no matching encoded quote is present.

The dedicated installment key is loaded from ignored credential input into
`merchant.installment_api_key`. `make uat-inputs` reads the local-only
`credentials/installment/servisler.md` file when it builds the private runtime config.

Parallel runs also accept one run-level installment count. Counts above one resolve a fresh
card-and-amount-specific quote for every item before payment initialization; quote lookups
use a separate concurrency limit of five and opaque encoded values are never persisted in
parallel evidence. Single-payment runs keep the existing path and do not call the installment
service. The CLI equivalent is `--installment-count`, or
`UAT_PARALLEL_INSTALLMENT_COUNT` with `make uat-parallel-3ds-smoke`.

To test installments from the UI:

```bash
make uat-web WEB_PORT=8001 WEB_RELOAD=--reload
```

Open `http://127.0.0.1:8001`. The Payment screen loads provider-supported options for the
selected card and amount. The Parallel screen applies its installment selection to every
item; selecting a count above one creates real UAT payments after the run is started.

## Parallel Testing

Parallel testing is intended for confidence runs and UAT regression checks. The UI supports
manual card selection and random selection from cards that are marked safe for automatic
success testing.

Two execution profiles separate a reliable demo from an intentional capacity test:

- `Stable Demo` reuses one Chromium process, isolates every challenge in its own browser
  context, and adapts ACS concurrency per card/provider lane.
- `Load Test` treats the requested ACS concurrency as a global ceiling. Card/provider lanes
  still start from their measured baseline, ramp after successful challenges, and back off
  on transient browser or provider failures.

Current practical baseline:

- `nkolay_dynamic_otp_visa_6111` is the primary baseline card.
- This card has completed a 50/50 parallel UAT validation successfully.
- `akbank_visa_7068` is also in the automatic success pool, with strong but not perfect
  observed stability across repeated 10-item parallel runs.
- Diagnostic cards remain selectable for investigation, but are not used by random success
  runs unless their behavior is explicitly promoted.

Each parallel item records its own result, so one provider or ACS failure does not hide the
outcome of the rest of the batch. Run evidence also includes actual peak ACS concurrency,
throughput, P50/P95 duration, and initialization/ACS/PaymentList stage timings.

The guarded CLI exposes the same profiles:

```bash
make uat-parallel-3ds-smoke UAT_PARALLEL_3DS_ARGS="--profile stable"
make uat-parallel-3ds-smoke UAT_PARALLEL_3DS_ARGS="--profile load --acs-concurrency 20"
make uat-parallel-3ds-smoke UAT_PARALLEL_INSTALLMENT_COUNT=3 UAT_PARALLEL_3DS_AMOUNT=1000.00
```

## Result Language

The system separates framework failures from provider or bank-side behavior. This matters
because not every failed payment is an application bug.

Common result meanings:

- `completed`: payment completed and PaymentList confirmed the expected state.
- `provider_failed`: Paynkolay or the bank returned a failed payment outcome.
- `pending_3ds`: payment initialized and is waiting for 3D Secure completion.
- `acs_manual_required`: the 3D Secure page requires human approval or SMS handling.
- `acs_browser_client_rejected`: the bank simulator rejected the browser client.
- `payment_list_missing`: provider flow completed, but PaymentList did not confirm the row.
- `installment_option_unavailable`: the selected count is not offered for that card/amount.
- `installment_lookup_failed`: the installment service did not return a usable response.
- `network_error`: request failed before a reliable provider response was available.
- `framework_error`: application-side unexpected error.

## Evidence And Reports

The project writes human-readable evidence for test runs and supports Allure reports for
formal review.

Evidence includes:

- order IDs and request references,
- card aliases and masked card information,
- provider status and response summaries,
- PaymentList status,
- 3DS automation status and reason,
- diagnostic classifications,
- installment count and quote source without the opaque encoded value,
- initialization/installment/ACS/PaymentList timing information.

Sensitive values are redacted before evidence is printed or saved.

## Current Completion State

As of July 27, 2026, active feature work is complete and the project is ready for
presentation and handoff.

Confirmed capabilities:

- local/mock payment validation,
- UAT MoTo payment validation,
- UAT 3D Secure initialization,
- headless automatic 3D Secure completion for supported simulator cards,
- parallel 3D Secure test runs,
- real UAT installment option lookup and encoded quote forwarding,
- parallel installment runs with fresh per-item quotes and bounded lookup concurrency,
- PaymentList verification with retry/backoff,
- same-day cancel smoke checks,
- sanitized JSON evidence,
- Allure report integration,
- tester-friendly web UI for Payment, Parallel, Settings, and Reports.

Latest local validation:

```text
ruff check        passed
mypy             passed
pytest           371 passed, 5 skipped
git diff check   passed
```

Latest live UAT highlights:

- N Kolay Visa baseline: 50/50 parallel run passed.
- N Kolay Visa installment lookup returned supported counts from 1 through 12 without
  creating a payment.
- Headless web 3DS test: completed, PaymentList captured, OTP source read from visible page.
- Parallel evidence is persisted under `reports/parallel-runs/`.

## Safe Data Policy

This repository must not contain private card or merchant data.

Kept outside Git:

- PAN,
- CVV,
- OTP,
- merchant secrets,
- Paynkolay SX values,
- raw 3D Secure HTML,
- provider hashes and signatures.

Private runtime files are expected under ignored locations such as `credentials/` or `/tmp`.

## Technology

- Python 3.11
- FastAPI
- Pydantic v2
- HTTPX
- Playwright
- Pytest
- Allure
- Ruff
- Mypy
- Poetry

## Repository Map

- `src/paynkolay_pos/api/`: web app, API routes, session state, and parallel run handling.
- `src/paynkolay_pos/clients/`: Paynkolay HTTP/form boundary.
- `src/paynkolay_pos/config/`: runtime settings and card configuration.
- `src/paynkolay_pos/models/`: typed payment, callback, and provider result models.
- `src/paynkolay_pos/security/`: Paynkolay hash and signature helpers.
- `src/paynkolay_pos/three_ds/`: 3D Secure rendering, profiling, OTP resolution, and automation.
- `src/paynkolay_pos/testing/`: card behavior metadata and generated test data helpers.
- `src/paynkolay_pos/web/`: tester-facing HTML, CSS, and JavaScript.
- `tools/`: guarded UAT smoke tools and config/scenario builders.
- `tests/`: unit, API, mocked E2E, reporting, and 3D Secure coverage.
- `reports/parallel-runs/`: sanitized parallel run evidence.

## Operating Note

The project is a test automation and validation framework. It is not a production payment
gateway and should only be used with approved test/UAT credentials and cards.
