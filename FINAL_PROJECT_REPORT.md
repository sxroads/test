# Paynkolay Sanal POS Test Automation Framework - Final Report

## 1. Project Goal

This project delivers a test automation framework for Paynkolay Sanal POS payment
flows. The framework is designed to validate payment initialization, 3D Secure
handling, transaction verification, cancel/refund operations, negative test modelling,
data-driven execution, and reporting without exposing sensitive payment data.

The project is not a production payment gateway. It is an automation and validation
framework for DEV/UAT/TEST integration work.

## 2. Implemented Scope

- Externalized runtime configuration for DEV, UAT, and TEST.
- Data-driven scenario catalogue with 100+ cards and hundreds of generated scenarios.
- Paynkolay form endpoint integration:
  - `POST /v1/Payment`
  - `POST /Payment/PaymentList`
  - `POST /v1/CancelRefundPayment`
- Paynkolay hash generation and response hash verification.
- MoTo and 3D Secure payment modelling.
- Browser-based FastAPI tester UI.
- 3D Secure form rendering and Playwright-based challenge automation.
- PaymentList final status verification.
- Same-day cancel request support.
- Negative test families for mock/local validation.
- Sanitized evidence logging and Allure-compatible reporting.
- Makefile-based one-command validation and UAT demo flows.

## 3. Architecture Summary

```text
src/paynkolay_pos/
  api/         FastAPI web/API routes, sessions, 3DS/result pages
  clients/     Paynkolay HTTP client and form endpoint payloads
  config/      Runtime environment, merchant, and card configuration
  models/      Payment, Paynkolay result, callback, and status models
  security/    Paynkolay SHA-512/Base64 hash helpers
  scenarios/   Data-driven payment scenario definitions
  testing/     Credential matrix and synthetic data generation
  three_ds/    3D Secure form rendering and browser challenge helpers
  reporting/   Sanitized JSON evidence helpers
```

## 4. Confirmed Live UAT Results

### MoTo Happy Path

Confirmed end to end in UAT:

- Payment request sent to TEST-AUTOMATION environment.
- Bank response returned `Approved`.
- Paynkolay response returned `RESPONSE_CODE=2`.
- PaymentList returned final `captured` status.
- Web UI displays order ID, provider reference, PaymentList status, and auth code.

### 3D Secure

Confirmed UAT behavior:

- Paynkolay returns `BANK_REQUEST_MESSAGE`.
- The framework renders the provider 3DS form in the browser.
- Manual web UI 3DS flow works with the provided UAT 3DS test card.
- Terminal/headless 3DS smoke collects sanitized browser evidence.

Known limitation:

- UAT ACS/simulator behavior can differ between manual browser, headed Chromium, and
  headless Chromium. For presentation, manual `make uat-web` is the most reliable 3DS
  demo path.

### Cancel

Confirmed same-day UAT cancel flow:

- A new MoTo UAT payment was created.
- PaymentList confirmed the sale transaction.
- `/v1/CancelRefundPayment` returned `response_code=2`.

Note:

- PaymentList may continue to show the original sale row as `captured` after cancel.
  Until Paynkolay confirms separate cancelled-row reporting semantics, the cancel endpoint
  response is the primary cancellation evidence.

## 5. Main Demo Commands

Local quality gate:

```bash
make check
```

Manual UAT demo UI:

```bash
make uat-web
```

Open:

```text
http://127.0.0.1:8000
```

If port 8000 is busy:

```bash
make uat-web WEB_PORT=8001
```

Terminal UAT smoke checks:

```bash
make uat-3ds-smoke UAT_3DS_BROWSER=--headed
make uat-cancel-smoke
```

## 6. Validation Status

Latest local validation:

```text
ruff check .     passed
mypy .           passed
pytest           242 passed, 5 skipped
```

Expected skips are sandbox/live-gated tests when private UAT environment variables or
live execution gates are not enabled.

## 7. Security And Data Handling

- `credentials/` is ignored by Git.
- PAN, CVV, OTP, API keys, merchant secrets, hashes, and raw 3DS HTML are not logged in
  full.
- Evidence output is sanitized before terminal/report usage.
- UAT card override data remains local and untracked.

## 8. Current Limitations

- Reliable real negative UAT tests require official invalid card/CVV/OTP test data from
  Paynkolay.
- Random card values may be accepted by the UAT simulator and should not be treated as
  reliable negative evidence.
- Cancel reporting through PaymentList needs Paynkolay clarification if a separate
  cancelled transaction row is expected.
- Fully automated headless 3DS completion depends on ACS simulator behavior.

## 9. Final Assessment

The framework is presentation-ready for:

- local/mock quality validation,
- manual UAT payment demo,
- MoTo payment and PaymentList verification,
- 3D Secure initialization and manual browser completion,
- same-day cancel endpoint verification,
- data-driven scenario and negative test coverage.

The remaining items are external UAT refinements, not core framework blockers.
