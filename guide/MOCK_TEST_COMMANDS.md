# Mocked/Local Test Commands

This guide explains how to validate the current project with mock data. These commands
do not require real Paynkolay sandbox credentials.

The current framework tests prove that the automation code behaves correctly against
mocked Paynkolay-like contracts. They do not prove that a real Paynkolay merchant account,
real test card, real 3DS bank page, or real callback endpoint works.

## Full Validation

```bash
make check
```

Use this as the main project health check.

What it runs:

- `poetry check`
- `poetry run ruff check .`
- `poetry run mypy src tests`
- `poetry run pytest`

What it proves:

- Poetry project metadata is valid.
- Code style passes.
- Strict typing passes.
- The full mocked/local test suite passes.
- Payment models, hash helpers, client mapping, callback logic, 3DS helpers, scenario
  catalogues, and mocked E2E flows still work together.

Expected current result:

```text
117 passed, 2 skipped
```

The skipped tests are browser-backed 3DS tests in this terminal environment.

## Full Pytest Suite Only

```bash
make test
```

Use this when dependencies, linting, and typing were already checked and you only want to
run the test suite.

What it proves:

- All unit, integration-style, and mocked E2E tests pass.
- The framework remains behaviorally valid with mock data.

Use `make check` instead when you want the strongest local validation.

## Data-Driven Scenario Tests

```bash
make scenarios
```

Use this to check business-style payment scenarios from the scenario catalogue.

What it runs:

- Tests marked with `scenario`.
- Scenario data from `examples/scenarios/payment_scenarios.json`.

Current mocked scenarios include:

- 3DS captured payment.
- Installment captured payment.
- 3DS declined payment.
- MoTo authorized payment.

What it proves:

- Scenario JSON can be loaded and validated.
- Scenario card aliases match configured card data.
- The same test logic can run different payment cases from data.
- Expected initialize and final statuses are respected.

This is the closest Makefile command for checking catalog-driven payment behavior with
mock data.

## API / Client Contract Tests

```bash
make api
```

Use this to check the Paynkolay client boundary.

What it proves:

- JSON placeholder calls are still handled for existing mocked tests.
- Paynkolay form-data payloads are built correctly.
- Internal fields are mapped to Paynkolay fields such as `clientRefCode`, `amount`,
  `successUrl`, `failUrl`, `installmentNo`, `cardNumber`, `use3D`, and `hashDatav2`.
- `/v1/Payment` mocked responses are parsed.
- `/Payment/PaymentList` mocked responses are mapped to internal transaction statuses.
- `/v1/CancelRefundPayment` mocked responses are mapped to cancelled/refunded or failed
  states.
- Provider HTTP errors and malformed responses fail clearly.

This command checks whether the framework can correctly prepare and interpret provider
boundary data before real sandbox calls are allowed.

## Callback Tests

```bash
make callback
```

Use this to check callback/webhook verification and matching logic.

What it proves:

- Callback payloads validate amount, status, timestamps, and required evidence fields.
- Callback signatures are verified.
- Invalid callback signatures are rejected.
- Callback records are stored by order ID.
- The framework can wait for a matching callback asynchronously.
- Callback data is cross-checked against request and final transaction status evidence.

This is still mocked/local because the real Paynkolay callback payload and signature rule
must be confirmed from sandbox documentation or real samples.

## 3D Secure Tests

```bash
make three-ds
```

Use this to check 3DS helper behavior.

What it proves:

- The 3DS helper can open a challenge target.
- It can support provider-specific selectors.
- It can enter an OTP into a challenge form.
- It can submit the challenge.
- It can process inline HTML from `BANK_REQUEST_MESSAGE`.
- Returned evidence is sanitized and does not expose OTP values.

Important note:

Some browser-backed Playwright tests may skip or fail to launch in restricted terminal
environments. That does not mean the mocked payment framework is broken. It means the
local browser runtime is not available or cannot launch correctly.

## Negative Tests

```bash
make negative
```

Use this to check failure paths.

What it proves:

- Invalid payment data is rejected.
- Invalid signatures or hashes are rejected.
- Declined provider results map to failed internal statuses.
- Missing provider rows or service failures do not look like successful payments.
- Bad 3DS inputs fail clearly.
- Invalid scenario definitions are rejected.

This command is important because payment automation must prove both approval and
rejection behavior.

## Parallel Test Run

```bash
make parallel
```

Use this to check whether the suite is safe under concurrent execution.

What it proves:

- Tests do not depend on a shared execution order.
- Order IDs, callback matching, temporary data, and scenario execution are isolated well
  enough for parallel pytest workers.
- The suite is closer to CI-style behavior.

If a test passes with `make test` but fails with `make parallel`, investigate shared
state, reused order IDs, shared files, or timing assumptions.

## Synthetic Scenario Generation

```bash
make synthetic-cards
```

Generates a synthetic card JSON array.

Default output:

```text
/tmp/paynkolay-synthetic-cards.json
```

What it is for:

- Building mock card datasets without storing real PAN, CVV, or OTP values.
- Testing catalogue scale locally.

```bash
make synthetic-scenarios
```

Generates a synthetic scenario catalogue.

Default output:

```text
/tmp/paynkolay-synthetic-scenarios.json
```

What it is for:

- Creating a large mocked scenario file.
- Checking that data-driven tests can handle many payment cases.

## Run A Custom Scenario File

```bash
make scenarios-file SCENARIO_FILE=/tmp/paynkolay-synthetic-scenarios.json
```

Use this after generating or preparing a scenario catalogue.

What it proves:

- The framework can load a scenario catalogue from `PAYNKOLAY_SCENARIO_CATALOG`.
- The scenario runner is not tied only to the checked-in example file.
- Large or private scenario files can drive the same mocked test logic.

The scenario file must contain mock/synthetic data unless real sandbox values have been
approved for private local use.

## Scale Demo

```bash
make scale-demo
```

Use this for a larger mocked data-driven run.

What it does:

1. Generates synthetic cards.
2. Generates synthetic scenarios.
3. Runs scenario tests against the generated scenario file.

What it proves:

- The scenario model can handle larger catalogues.
- The scenario runner can execute generated data.
- The framework remains data-driven instead of depending on hardcoded test cases.

```bash
make scale-demo-parallel
```

Use this to run the scale demo with pytest-xdist parallel workers.

What it proves:

- Larger scenario sets can run concurrently.
- Scenario execution remains isolated under parallel load.

## Allure Results

```bash
make allure-results
```

Use this to generate raw Allure result files.

What it does:

- Removes existing `allure-results`.
- Runs pytest with `--alluredir=allure-results`.

What it proves:

- The suite can produce reportable test output.
- Sanitized evidence helpers can be used by report attachments.

## Allure HTML Report

```bash
make report
```

Use this to generate an HTML Allure report.

Requirements:

- Allure CLI must be installed locally.

On macOS:

```bash
brew install allure
```

What it does:

- Runs `make allure-results`.
- Generates `allure-report/`.

What it is for:

- Reviewing test results in a browser-friendly report format.
- Checking that evidence remains useful without exposing secrets.

## Cleanup

```bash
make clean
```

Use this to remove generated local artifacts.

What it removes:

- Python cache directories.
- Pytest cache.
- Mypy cache.
- Ruff cache.
- Allure result/report folders.
- Local `reports/` folder.

It does not remove source files, tests, guide notes, or private config files outside the
repository.

## Practical Command Order

For normal mocked/local validation:

```bash
make check
```

For a payment-scenario-focused check:

```bash
make scenarios
make negative
make callback
make three-ds
```

For CI-style confidence:

```bash
make check
make parallel
```

For larger mocked data validation:

```bash
make scale-demo
make scale-demo-parallel
```

## Boundary

These commands stay inside mocked/local project scope. Do not use them to call real
Paynkolay endpoints unless:

- a private config with real sandbox values exists,
- the user confirms live network calls are allowed,
- test amount, card, and 3DS behavior are agreed,
- result verification remains enabled,
- no full PAN, CVV, OTP, secret, token, or signature is written to tracked files.
