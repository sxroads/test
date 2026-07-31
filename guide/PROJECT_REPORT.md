# Paynkolay Sanal POS Otomasyon Proje Raporu


## 1. Proje Amaci

The goal of this project is to build a Python-based test automation framework for
Paynkolay Sanal POS payment flows. The framework focuses on integration correctness,
data-driven scenario execution, 3D Secure handling, callback verification, transaction
status validation, cancel/refund coverage, and sanitized reporting.

The project is not a production payment gateway. It is a controlled automation and test
framework designed to validate Sanal POS integration behavior before and during real
sandbox/UAT execution.

## 2. Kapsam

Implemented scope covers:

- Tek Cekim payment scenarios
- Taksitli payment scenarios
- 3D Secure challenge automation
- Browser-based tester payment UI
- MoTo payment metadata
- Debit/credit card scenario modelling
- Negative test families
- Paynkolay form endpoint payload generation
- Paynkolay hash generation and verification
- PaymentList-based transaction status validation
- Cancel/refund request modelling
- Callback verification and storage
- Data-driven scenario execution
- Scale demo with 100 cards and 1000 scenarios
- Allure HTML reporting
- CI-compatible local validation
- Success/fail return URL hash verification
- External sanitized payment event logging

The project has since been validated against Paynkolay UAT with real guarded smoke tools.
Remaining gaps are provider-dependent or optional polish rather than blockers for the
automation framework hand-off.

## 3. Teknoloji Yigini

The project uses the agreed Python automation stack:

- Python 3.11+
- Poetry
- Pytest
- pytest-asyncio
- pytest-xdist
- HTTPX async client
- Pydantic v2
- Playwright Python
- Allure Pytest
- Ruff
- Mypy strict mode

The original suggested Java stack was intentionally replaced with Python. This is not a
technical risk as long as Python is accepted as the chosen implementation stack.

## 4. Mimari Ozet

The codebase is separated into clear framework layers:

```text
src/paynkolay_pos/
  callbacks/   Callback receiver, signature verification, and callback store
  clients/     Async Paynkolay HTTP client and form endpoint payloads
  config/      Runtime environment, merchant, and card settings
  flows/       Business-level payment flow orchestration
  models/      Payment, callback, and Paynkolay result models
  reporting/   Sanitized evidence helpers for Allure
  api/         FastAPI web/API routes, session state, 3DS/result endpoints
  sandbox/     Sandbox readiness checks
  scenarios/   Data-driven payment scenario catalogue
  security/    HMAC and Paynkolay SHA-512/Base64 hash helpers
  testing/     Test factories and synthetic data generation
  three_ds/    3D Secure browser challenge and provider form rendering
  web/         HTML/CSS/JS tester UI
```

This structure keeps provider IO, domain models, scenario metadata, security logic,
browser automation, and reporting concerns separate.

## 5. Konfigurasyon Yonetimi

Runtime configuration is externalized through JSON and environment variables.

Supported environments:

- `dev`
- `uat`
- `test`

Important environment variables:

```bash
PAYNKOLAY_CONFIG_FILE
PAYNKOLAY_ENV
PAYNKOLAY_SCENARIO_CATALOG
PAYNKOLAY_ENABLE_LIVE_E2E
PAYNKOLAY_EXTERNAL_LOG_URL
PAYNKOLAY_EXTERNAL_LOG_TIMEOUT_SECONDS
```

The framework validates merchant configuration, endpoint URLs, card aliases, PAN/CVV
format, OTP consistency, and active environment selection before tests attempt payment
logic.

Real credentials and real card data must remain outside Git.

## 6. Paynkolay Entegrasyon Katmani

Implemented Paynkolay form endpoint support:

```text
POST /v1/Payment
POST /Payment/PaymentList
POST /v1/CancelRefundPayment
```

The client can:

- build multipart form-data payment requests
- generate Paynkolay `hashDatav2`
- parse 3DS initialization responses
- parse success/fail result payloads
- verify Paynkolay result hashes
- query PaymentList and map provider rows to internal transaction status
- build cancel/refund payloads
- parse cancel/refund responses

Some JSON placeholder endpoints remain in the client only for local mocked framework
tests. The real Paynkolay path is the form endpoint path.

## 7. Senaryo Yonetimi

Scenario execution is data-driven. Scenario files define:

- scenario ID
- card alias
- amount
- currency
- 3DS requirement
- expected initialization status
- expected final status
- installment count
- payment channel
- MoTo flag
- tags

Checked-in examples cover base scenarios and sandbox-ready templates. Synthetic generators
support large-scale local validation.

Validated scale command:

```bash
make scale-demo COUNT=100 SCENARIO_COUNT=1000
```

Observed expected result:

```text
1000 passed, 132 deselected
```

This confirms high-volume data-driven execution works with mocked provider behavior.

## 8. 3D Secure Otomasyonu

3D Secure support includes:

- redirect URL based challenge handling
- inline HTML challenge handling from `BANK_REQUEST_MESSAGE`
- raw/base64 provider 3DS form rendering through `/payments/{order_id}/three-ds`
- transient 3DS form storage
- OTP input fill
- submit action
- provider-specific selector override
- sanitized result object
- fake page tests
- local Playwright browser-backed tests

Chromium tests can be affected by managed terminal sandbox restrictions. When run outside
the restricted terminal, the browser-backed 3DS test passed:

```text
2 passed
```

Real ACS selectors and real 3DS behavior still require sandbox access.

## 8.1 Web UI Odeme Akisi

The FastAPI web UI now supports the main tester-driven virtual POS flow:

- user submits card/payment fields from the browser
- backend builds a typed payment session
- backend calls Paynkolay form initialization
- 3DS provider form is rendered when required
- Paynkolay success/fail return payload is parsed and hash-verified
- payment session reaches final state
- sanitized external log events are emitted when configured

Important web commands:

```bash
make web
make web-test
make web-check
```

Implemented web phases:

- Phase 1: FastAPI + frontend skeleton
- Phase 2: payment session store
- Phase 3: provider initialization
- Phase 4: 3DS form rendering
- Phase 5: success/fail return URL verification
- Phase 6: external event logging

## 9. Callback Mekanizmasi

Callback support includes:

- strict callback payload model
- signature canonicalization
- HMAC verification
- callback store
- async wait-for-callback behavior
- callback/request/status consistency checks
- local HTTP callback receiver skeleton

The callback receiver is intentionally lightweight and based on Python stdlib
`http.server`. It is suitable for sandbox test capture, not production hosting.

Real callback payload shape and exact signature rules must be confirmed with Paynkolay
sandbox documentation or real sample callbacks.

## 10. Raporlama

Allure is used for HTML reporting. The reporting layer sanitizes sensitive data before
attachment.

Sanitized fields include:

- PAN masking
- CVV redaction
- OTP redaction
- API key redaction
- secret key redaction
- signature redaction
- Paynkolay `sx` redaction
- Paynkolay `hashData` and `hashDatav2` redaction
- raw 3DS HTML redaction for external events

External event logging is optional and disabled unless `PAYNKOLAY_EXTERNAL_LOG_URL` is
set. Events are sent with masked/sanitized fields only.

Report generation:

```bash
make report
allure open allure-report
```

The report should be opened through `allure open`, not by directly opening
`allure-report/index.html`, because the report fetches local JSON assets.

Current value of the report is proving the reporting pipeline. Its full business value
will appear after real sandbox runs produce real transaction evidence.

## 11. Test Stratejisi

The framework has multiple test layers:

- unit tests for models and validation
- client tests with mocked HTTP transport
- security tests for HMAC and Paynkolay hashes
- callback verification tests
- 3DS helper tests
- mocked E2E lifecycle tests
- generated scenario scale tests
- sandbox readiness tests
- guarded live E2E placeholder

Main commands:

```bash
make check
make smoke
make test
make parallel
make scale-demo COUNT=100 SCENARIO_COUNT=1000
make report
```

Sandbox commands:

```bash
make sandbox-ready
make sandbox
make sandbox-report
```

Sandbox commands require private runtime inputs.

## 12. Guncel Dogrulama Durumu

Latest full local validation:

```text
make check
128 passed, 8 skipped
```

Latest smoke validation:

```text
make smoke
6 passed, 130 deselected
```

Latest scale validation:

```text
make scale-demo COUNT=100 SCENARIO_COUNT=1000
1000 passed, 132 deselected
```

The skipped tests are expected under local conditions:

- sandbox config is not available
- live E2E gate is disabled
- local socket creation may be restricted in managed terminal sessions
- Chromium may be restricted in managed terminal sessions

These skips are not framework failures.

## 13. Sandbox Readiness

The project includes a readiness checker that validates private inputs before running any
real payment.

Command:

```bash
make sandbox-ready
```

It checks:

- placeholder credential values
- minimum card count
- scenario card aliases vs configured cards
- unused configured cards
- 3DS card OTP consistency
- MoTo metadata consistency
- sandbox scenario tagging

This reduces debugging time once real credentials and card data are provided.

## 14. Bilinen Blokajlar

The following items cannot be completed correctly without external Paynkolay sandbox
details:

- real merchant credentials
- real sandbox card catalogue
- real OTP values
- exact callback payload format
- exact callback signature/hash rules
- real ACS/3DS selectors
- real sandbox business rules for negative cases
- real response samples for all transaction outcomes

These are external dependencies, not implementation gaps.

## 15. Riskler

Current risks:

- Paynkolay sandbox response fields may differ from current assumptions.
- Callback signature format may differ from the generic HMAC implementation.
- ACS 3DS page selectors may differ from current generic defaults.
- Some negative scenarios may require specific bank-side sandbox behavior.
- Real sandbox endpoints may require additional fields not present in public examples.

Mitigation:

- keep real provider calls behind explicit `PAYNKOLAY_ENABLE_LIVE_E2E`
- validate config with `make sandbox-ready`
- attach sanitized evidence to Allure
- update models only after real response samples are available
- keep mocked/local tests stable while adding provider-specific behavior

## 16. Teslim Durumu

The framework foundation is complete for local/mock execution and ready for real sandbox
integration once external details are available.

Completed:

- architecture
- configuration model
- data-driven scenario model
- Paynkolay form payloads
- Paynkolay hash helpers
- PaymentList mapping
- cancel/refund modelling
- callback verification and receiver skeleton
- 3DS helper
- reporting sanitization
- Makefile command surface
- CI-compatible validation
- scale demo
- sandbox readiness checks

Not completed because it is externally blocked:

- real Paynkolay sandbox E2E execution
- real callback verification against provider samples
- real ACS selector verification
- real transaction evidence in Allure

## 17. Sonuc

The project is on track. Without real credentials and sandbox access, the remaining work is
mostly blocked by external provider details. The local framework is already testable,
reportable, and structured for real E2E activation.

The next meaningful engineering milestone is to obtain sandbox credentials and real test
data, run `make sandbox-ready`, then implement the guarded live E2E flow using verified
Paynkolay response samples.
