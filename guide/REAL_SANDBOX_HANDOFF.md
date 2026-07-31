# Real Paynkolay Sandbox Handoff

This local note tracks only the inputs needed to move from mocked/local validation to
real Paynkolay sandbox validation. `guide/` is ignored by Git; do not commit this file
unless the owner explicitly asks.

## Current Local Baseline

- `make check` passes locally.
- Latest observed result: `117 passed, 2 skipped`.
- The skipped tests are browser-backed 3DS tests; Chromium launches but exits in the
  sandboxed terminal environment.
- A private synthetic config copy exists at:

```text
/private/tmp/paynkolay-settings.local.json
```

It currently contains placeholder credentials and synthetic cards only.

## Private Inputs Needed

Fill these outside Git before any real endpoint call:

- Sandbox base URL, if different from the public test base.
- Sales `sx`.
- PaymentList `sx`, if different.
- Cancel/refund `sx`, if different.
- Merchant secret/hash key.
- Merchant ID and terminal ID, if required by the selected flow.
- Success URL reachable by Paynkolay.
- Fail URL reachable by Paynkolay.
- Callback/webhook payload sample, if separate from success/fail redirects.
- Callback signature algorithm and field order.
- Approved sandbox test cards.
- Expected OTP values.
- Real 3DS page selectors or documented challenge behavior.
- Confirmation of installment API mode.
- Confirmation of MoTo rules.
- Confirmation of whether `RESPONSE_CODE=2` maps to `captured` or `authorized`.
- Cancel/refund business rules and allowed timing.

## Start Conditions For Real Calls

Do not call real Paynkolay endpoints until all of these are true:

- A private config file contains real sandbox values.
- The user confirms live network calls are allowed.
- Test amount, card, and 3DS behavior are agreed.
- Result verification remains enabled.
- No full PAN, CVV, OTP, secret, token, or signature is written to tracked files.

## First Real Smoke Target

The first real test should stay narrow:

1. Submit one `/v1/Payment` request.
2. Complete 3DS only if the selected card requires it.
3. Parse success/fail result payload.
4. Verify `hashDataV2`.
5. Query `/Payment/PaymentList`.
6. Cross-check order ID, amount, currency, provider reference, and final status.
7. Verify callback only if real callback behavior is confirmed.
8. Attach sanitized evidence only.
