# Handoff

This project is ready for handoff as of July 31, 2026.

It is a Paynkolay Virtual POS test automation platform with a browser UI, API routes,
parallel execution, headless 3D Secure automation, PaymentList verification, real UAT
installment quotes, and sanitized reporting. Cancel/refund is outside the current delivery
scope.

## What Is Ready

- Single payment testing through the Payment screen.
- Real UAT installment options and encoded quote forwarding through the Payment screen.
- MoTo and 3D Secure payment initialization.
- Headless 3D Secure completion for supported simulator cards.
- Parallel single-payment and installment 3D Secure runs through the Parallel screen.
- Parallel UI is auto-3DS only and shows a simplified results table:
  `Card`, `Installment`, `Status`, `Class`, `PaymentList`, `3DS Auto`, `Duration`.
- Parallel UI shows success rate from completed classifications, e.g. `19/20 (95.0%)`.
- Runtime card/environment visibility and safe merchant/payment SX editing through Settings.
- Allure/report/evidence review through Reports.
- Sanitized parallel evidence under `reports/parallel-runs/`.
- Local/mock and guarded UAT validation paths.

## Do Not Change Without A Reason

- Payment screen: current behavior is validated and should remain stable.
- Settings screen: preserve the existing overview and the approved merchant credential
  editor. Never return the current SX to the browser.
- Card secret handling: never commit PAN, CVV, OTP, merchant secret, SX, hashes, signatures,
  or raw ACS HTML.
- Random automatic success selection: keep it restricted to explicit success candidates.

## Current UAT Environment Contract

Provider base URL:

```text
https://paynkolaytest.nkolayislem.com.tr/Vpos
```

Default callback/final return endpoint:

```text
https://paynkolay.com.tr/test/callback
```

For UAT, the callback is treated as the final endpoint. Do not append local callback/result
paths to it.

`make uat-inputs` builds runtime config and scenario catalog from ignored credential
artifacts.

The current UAT default merchant is `400000273`. Its Payment SX, dedicated PaymentList SX,
and merchant secret are loaded as one consistent set from the ignored Postman artifact.
Do not mix these with 1470 credentials. `make uat-web` regenerates the `/tmp` runtime
configuration, so restart the UI after changing the default merchant or private credentials.

The runtime supports a dedicated installment SX. Credential selection is merchant-scoped:
the current 273 configuration keeps installment lookup on the 273 credential set instead
of mixing in the ignored 1470 SX. Parallel installment runs resolve a fresh quote per item,
use a separate lookup concurrency limit of five, and never persist the opaque
`EncodedValue`.

Settings exposes editable Merchant No and Payment/Sales SX fields:

- the current SX is never returned to the browser,
- leaving SX blank preserves the current value,
- updates are validated and atomically written to the active private runtime config,
- new payment runs use the updated merchant and SX snapshot,
- a dedicated PaymentList SX remains separate and is not overwritten by a Payment SX edit.

The Settings editor is not a full merchant-profile selector. Changing Merchant No and
Payment SX there does not replace hidden merchant secret, PaymentList, or installment
credentials. Use ignored credential artifacts and regenerate the runtime config when
switching between complete merchant credential sets.

## Current Card Status

Automatic success candidates:

- `nkolay_dynamic_otp_visa_6111`
- `akbank_visa_7068`

Diagnostic cards:

- `garanti_bankasi_mastercard_6017`
- `akbank_visa_5232`

Manual-only and quarantined cards are still useful for diagnostics, but they should not be
used in random success runs.

## Important Recent Evidence

- Merchant `400000273` is the active presentation default.
- A live read-only PaymentList query with the 273 credential set successfully returned an
  existing provider transaction row. The old row had `failed` transaction status, but the
  listing request, token, hash, secret, parser, and row mapping all worked.
- Merchant `400001470` Payment/3DS reached the success callback, but its PaymentList
  credentials were not usable:
  - Payment SX reuse was rejected as an invalid listing token.
  - The supplied short listing token could not be parsed as a complete SX.
  - Combining it with the supplied client ID was rejected as an invalid client ID/token
    pair.
- Keep 1470 out of the default UAT configuration until Paynkolay provides or activates a
  valid complete PaymentList credential.
- N Kolay Visa baseline completed 50/50 in parallel UAT.
- The live installment lookup was verified with the N Kolay Visa card and returned supported
  counts from 1 through 12. This lookup created no payment.
- Headless web 3DS completed successfully without opening a visible tab:
  - status: `completed`
  - PaymentList: `captured`
  - automation: `completed submitted source=visible_page reason=otp_submitted`
- Earlier Garanti parallel behavior showed required-field validation and provider
  finalization instability. Treat Garanti as diagnostic unless deliberately retesting it.

## Headless 3DS Notes

The key fix is in `src/paynkolay_pos/three_ds/acs_browser.py`.

The QNB ACS simulator rejected pure headless Chromium because of the `HeadlessChrome`
user-agent. Headless contexts now use a normal Chrome-like user-agent while still running
in the background.

If this regresses, look for:

- `_404`
- `404-QPG97-STATUS`
- `acs_browser_client_rejected`
- `otp_selector_not_found`
- `failed not-submitted source=no-source`
- `provider payment status verification failed`
- `otp_submitted_callback_not_reached`
- `Page.set_content: Timeout 30000ms exceeded`

`acs_browser_client_rejected` means the browser identity was rejected. `no-source` means no
safe OTP source was found.

Recent resilience tuning:

- Submitted parallel 3DS flows now use PaymentList retry delays of `2s, 5s, 10s, 20s`.
- ACS initial content rendering now allows 60 seconds before classifying a Playwright
  content-load timeout.
- `payment_list_missing` after `otp_submitted` usually means provider/PaymentList timing,
  credential rejection, or provider finalization—not automatically a card decline.
- The four retry delays add 37 seconds. A deterministic credential error therefore produces
  roughly 42-second rows even when OTP submission and callback return finish in a few
  seconds. Inspect the direct provider response before treating this as timing.
- `framework_error` with `Page.set_content` means the ACS browser automation timed out
  before OTP processing.

## How To Start The UI

Local/mock:

```bash
make web
```

UAT, normal headless 3DS:

```bash
make uat-web WEB_PORT=8001 WEB_RELOAD=--reload
```

UAT with visible browser tabs for debugging:

```bash
make uat-web WEB_PORT=8001 WEB_RELOAD=--reload WEB_3DS_HEADED=1 WEB_3DS_CLOSE_DELAY=5
```

## Useful Smoke Commands

```bash
make uat-3ds-smoke
make uat-parallel-3ds-smoke
make credential-scenario-report
make report
```

Cancel/refund commands are legacy/diagnostic only and are not required for this handoff.

## Validation Before Shipping Changes

Run:

```bash
poetry run ruff check .
poetry run mypy src tests tools
poetry run pytest -q
git diff --check
```

Latest known status:

```text
targeted merchant/client/API tests  113 passed
pytest                             379 passed, 5 skipped
ruff check                         passed
mypy                               passed
JavaScript syntax check            passed
git diff check                     passed
```

## Current Unfinished Business

There is no required implementation work left for the current project scope.

Possible future work:

- obtain/activate a valid complete PaymentList credential for merchant `400001470`,
- validate 100-150 item execution under a deliberate load-test profile,
- add official negative UAT tests when Paynkolay provides stable negative card data,
- collect a guarded live parallel installment payment baseline,
- expand cancel reporting if provider semantics are clarified.

## Safe Handoff Rule

When investigating a failed payment, first decide whether the failure belongs to:

- the framework,
- Paynkolay/provider response,
- ACS/bank simulator behavior,
- PaymentList timing,
- network/environment.

The project already records enough sanitized metadata to make that distinction in most
cases.
