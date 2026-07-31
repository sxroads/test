# Project Memory

This file is the short memory for future sessions. Read this first, then `guide/HANDOFF.md`
and `README.md` if more context is needed.

Never move private data into tracked files. `credentials/` is ignored and must remain the
place for local-only card, merchant, SX, OTP, hash, and provider artifacts.

## Final State - July 31, 2026

The project is considered feature-complete and presentation-ready.

It provides a tester-facing FastAPI web UI for:

- single Paynkolay payment tests,
- MoTo and 3D Secure flows,
- card selection and form-fill,
- parallel test runs,
- real UAT installment option lookup for single and parallel runs,
- PaymentList verification,
- report and evidence review,
- runtime settings overview and safe merchant/payment SX editing.

The current UI polish scope is also complete:

- Payment screen was left untouched because it already works well.
- Settings keeps its existing overview and now includes an approved merchant credential
  editor for new payment runs.
- Parallel screen now uses the available page width instead of staying narrow.
- Parallel result table is presentation-oriented and shows only:
  `Card`, `Installment`, `Status`, `Class`, `PaymentList`, `3DS Auto`, and `Duration`.
- Parallel result rows use light green for completed classifications and light red for
  attention/failure classifications.
- Parallel summary shows a success rate calculated from `classification == "completed"`
  results, e.g. `19/20 (95.0%)`.
- Parallel runs always use automatic 3DS completion from the UI. Manual 3DS mode remains
  available on the single Payment screen only.
- Reports screen now uses wider, more readable panels and tables.
- Long strings in Parallel and Reports are less cramped for business analyst review.

## Current Card Automation Policy

Random/default automatic 3D Secure success runs must use only explicit success candidates.

Current automatic success pool:

- `nkolay_dynamic_otp_visa_6111`
- `akbank_visa_7068`

Current diagnostic pool:

- `garanti_bankasi_mastercard_6017`
- `akbank_visa_5232`

Current manual-only / quarantined behavior should stay excluded from random success runs
unless fresh UAT evidence proves otherwise.

Important live UAT observations:

- `nkolay_dynamic_otp_visa_6111` is the baseline card. It completed a 50/50 parallel UAT run.
- `akbank_visa_7068` performed strongly across repeated 10-item parallel runs, but had
  intermittent failures in larger repeated observations.
- Garanti can show required-field validation issues or provider finalization failures under
  parallel automation. Keep it diagnostic unless deliberately retesting it.
- The framework should distinguish provider/ACS behavior from framework errors.

## Headless 3DS Resolution

The latest important fix was headless 3D Secure automation.

Root cause:

- QNB ACS/simulator rejected headless Chromium when the browser identified itself with a
  `HeadlessChrome` user-agent.
- The page returned `_404 / 404-QPG97-STATUS`.
- Earlier diagnostics could misleadingly appear as `otp_selector_not_found`.

Implemented behavior:

- Headless browser contexts now use a normal Chrome-like user-agent.
- Headed mode remains unchanged.
- QNB client rejection is classified as `acs_browser_client_rejected`.
- Dynamic OTP cards can use the visible page OTP even when no static `expected_otp` is
  configured.
- ACS frame evidence is sanitized before being stored.

Confirmed after the fix:

- Web UI headless 3DS completed without opening a visible tab.
- Payment status was `completed`.
- PaymentList status was `captured`.
- 3DS automation showed `completed submitted source=visible_page reason=otp_submitted`.

Current resilience tuning:

- Parallel 3DS PaymentList verification uses the longer retry window
  `2s, 5s, 10s, 20s` after OTP submit. This is meant to reduce transient
  `payment_list_missing` / `provider payment status verification failed` results.
- ACS initial HTML rendering timeout was raised to 60 seconds to reduce transient
  `Page.set_content: Timeout 30000ms exceeded` failures under parallel UAT load.
- These changes do not convert provider declines to success; they only give submitted
  3DS flows more time to finalize and render.

## Parallel Run Limits

The old 10-item cap was raised to 150.

Current intended UI/API behavior:

- Manual selections cannot exceed 150 total test items.
- Random count cannot exceed 150.
- Concurrency input cannot exceed 150.
- Evidence is written under `reports/parallel-runs/`.

Stable UI runs still use fixed payment concurrency 10 and adaptive ACS scheduling. Higher
limits exist for deliberate API/CLI capacity runs.

## Installment Integration

- UAT installment options come from `Payment/PaymentInstallments`.
- The runtime model supports a dedicated installment key, but credential selection must stay
  merchant-scoped. The active 273 config uses the 273 Payment SX for installment lookup
  rather than mixing in the private 1470 SX.
- Each selected option has an opaque card-and-amount-specific `EncodedValue`.
- Parallel runs use one run-level installment count and fetch a fresh quote per item.
- Parallel quote lookups have a separate maximum concurrency of five.
- Single-payment parallel runs do not call the installment service.
- Encoded quote values are never written to UI responses, logs, or parallel evidence.
- A live UAT baseline completed one N Kolay Visa payment for `1000.00 TRY` with three
  installments. PaymentList returned `captured`, OTP automation returned to the callback,
  and the saved evidence contained no full PAN or opaque encoded quote.

### Runtime Merchant and Payment SX Settings

The latest supervisor direction supersedes the earlier service-backed SX design assumption
for the current project scope.

- Settings edits the active merchant number and primary Payment/Sales SX.
- Initial values still come from ignored runtime credential inputs; no real merchant or SX
  value belongs in tracked files.
- The merchant number is visible and editable. The current SX is never returned to the
  browser; an empty field preserves it and a new value replaces it.
- Changes are validated and atomically written to `PAYNKOLAY_CONFIG_FILE`.
- New single and parallel runs load the updated values. Existing runs keep their credential
  snapshot.
- The same payment SX is used in both the outbound `sx` field and `hashDatav2`.
- PaymentList uses its dedicated private `list_api_key` when configured and falls back to
  Payment/Sales SX only when no listing SX is available. Its request hash is calculated
  with the same SX that is sent in the PaymentList request.
- Editing Payment SX from Settings does not overwrite a dedicated PaymentList SX.
- Settings is an editor for the visible merchant number and Payment SX, not a complete
  credential-profile switcher. Changing to another merchant may also require the matching
  hidden merchant secret, PaymentList SX, and installment SX; use ignored credential inputs
  plus config regeneration for that operation.
- Installment keeps its private runtime SX; cancel/refund is outside the current delivery
  scope.
- Re-running `make uat-web` regenerates the runtime config from ignored inputs and restores
  their defaults.
- A service-backed SX resolver remains optional future work only if an official service
  contract is supplied.

### Active UAT Merchant and Credential Selection

The active UAT default is now merchant `400000273`.

- `make uat-config`, `make uat-inputs`, and `make uat-web` default to `400000273`.
- For `400000273`, Payment SX, PaymentList SX, and merchant secret are selected together
  from the ignored Postman credential artifact.
- Its installment request credential is also kept within the 273 set; the ignored 1470 SX
  is not injected into 273 requests.
- The generated runtime config was checked to contain the 273 merchant and a dedicated
  PaymentList SX without printing any secret values.
- A live read-only PaymentList query for an existing 273 transaction successfully returned
  a provider row. The historical row itself had status `failed`; this proves the listing
  credential/hash/request path works, not that the old payment was successful.

Merchant `400001470` was investigated before restoring 273:

- Payment initialization, 3D Secure OTP submission, and return to the success callback
  worked with the supplied 1470 Payment SX and merchant secret.
- Reusing the Payment SX for PaymentList was rejected by the provider as an invalid listing
  token.
- A later short PaymentList token was not a complete SX. Used alone, the provider could not
  parse it; combined with the supplied client ID, the provider reported that the client ID
  or token was invalid.
- Therefore 1470 must not be the presentation default unless Paynkolay supplies or activates
  a valid full PaymentList credential pair.
- All real credential values remain only in ignored local artifacts and generated `/tmp`
  runtime configuration files.

Relevant commits:

- `44a15da feat(settings): add editable merchant credentials`
- `692c8f8 fix(uat): align merchant payment credentials`
- `c42b8a7 fix(uat): restore merchant 273 credentials`

## Validation Snapshot

Latest known local validation after restoring merchant 273:

```text
targeted merchant/client/API tests  113 passed
poetry run pytest -q               379 passed, 5 skipped
poetry run ruff check src tests tools
poetry run mypy src tools
node --check src/paynkolay_pos/web/static/js/i18n.js
git diff --check
```

All listed quality checks passed. Re-run the full gate before any release commit.

## Important Commands

Start local web UI:

```bash
make web
```

Start UAT web UI:

```bash
make uat-web WEB_PORT=8001 WEB_RELOAD=--reload
```

Use visible browser tabs only for debugging:

```bash
make uat-web WEB_PORT=8001 WEB_RELOAD=--reload WEB_3DS_HEADED=1 WEB_3DS_CLOSE_DELAY=5
```

Run guarded UAT smoke checks:

```bash
make uat-3ds-smoke
make uat-parallel-3ds-smoke
```

Cancel/refund tooling may still exist in the repository, but it is not part of the current
delivery scope.

Run local validation:

```bash
poetry run ruff check .
poetry run mypy src tests tools
poetry run pytest -q
git diff --check
```

## Files To Know

- `src/paynkolay_pos/api/routes/parallel_runs.py`: parallel run API and item execution.
- `src/paynkolay_pos/api/payment_list_retry.py`: PaymentList retry/backoff.
- `src/paynkolay_pos/testing/card_behaviors.py`: safe card automation metadata.
- `src/paynkolay_pos/three_ds/acs_browser.py`: Playwright ACS automation.
- `src/paynkolay_pos/three_ds/acs_profile.py`: ACS screen classification.
- `src/paynkolay_pos/three_ds/otp_resolver.py`: OTP source decisioning.
- `src/paynkolay_pos/web/templates/parallel.html`: Parallel page layout.
- `src/paynkolay_pos/web/templates/report.html`: Reports page layout.
- `src/paynkolay_pos/web/static/css/app.css`: shared UI styling.
- `tools/run_uat_parallel_3ds_smoke.py`: guarded parallel UAT smoke CLI.
- `tools/run_uat_3ds_smoke.py`: guarded single 3DS UAT smoke CLI.

## Future Work

Only provider-dependent or optional work remains:

- get official negative UAT card/CVV/OTP data,
- obtain or activate a valid complete PaymentList credential for merchant `400001470`
  before attempting to make 1470 the default again,
- optionally revisit service-backed SX resolution only if an official contract is supplied,
- design a controlled 100-150 item parallel execution mode with capacity limits, telemetry,
  and provider-safe throttling.
