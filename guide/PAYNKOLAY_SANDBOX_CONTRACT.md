# Paynkolay Sandbox Contract Notes

This file records the current public Paynkolay integration contract findings and the
remaining inputs needed before changing provider-boundary code.

`guide/` is ignored by Git. Keep this file local unless the owner explicitly asks to
publish it.

## Source Pages Checked

- Integration overview: https://paynkolay.com.tr/entegrasyon/
- Payment integration services: https://paynkolay.com.tr/entegrasyon/01-payment-integration-services.php
- API payment documentation: https://paynkolay.com.tr/entegrasyon/03-api-documentation.php
- Request hash: https://paynkolay.com.tr/entegrasyon/04-hash-request.php
- Response hash: https://paynkolay.com.tr/entegrasyon/05-hash-response.php
- Payment result: https://paynkolay.com.tr/entegrasyon/06-payment-result.php
- Test cards: https://paynkolay.com.tr/entegrasyon/07-test-cards.php
- Cancel/refund: https://paynkolay.com.tr/entegrasyon/09-cancel-refund-payment.php
- Transaction verification: https://paynkolay.com.tr/entegrasyon/10-verification-service.php

Do not copy public test tokens, merchant secret keys, full PAN values, CVVs, or OTP
values into this repository. Pull them from the official docs or the merchant panel when
creating a private local config file.

## Public Contract Findings

### Environment

The public docs describe these VPOS endpoints:

```text
test base: https://paynkolaytest.nkolayislem.com.tr/Vpos
prod base: https://paynkolay.nkolayislem.com.tr/Vpos
```

Payment API v1:

```text
POST /v1/Payment
content type: multipart/form-data
```

Transaction verification:

```text
POST /Payment/PaymentList
content type: multipart/form-data
```

Cancel/refund:

```text
POST /v1/CancelRefundPayment
content type: multipart/form-data
```

The current framework placeholders are different:

```text
POST /payments/initialize
GET  /payments/{order_id}/status
content type: application/json
```

So the next implementation step should introduce a Paynkolay-specific adapter instead
of only renaming the existing placeholder paths.

### Payment Request Shape

The public API v1 payment request is form-data, not JSON.

Observed provider field names:

```text
sx
clientRefCode
successUrl
failUrl
amount
installmentNo
cardHolderName
month
year
cvv
cardNumber
use3D
transactionType
cardHolderIP
rnd
hashDatav2
environment
currencyNumber
MerchantCustomerNo
```

Important mapping from current internal model:

```text
order_id              -> clientRefCode
amount canonical      -> amount
callback/success URL  -> successUrl
callback/failure URL  -> failUrl
installment_count     -> installmentNo
card.card_holder      -> cardHolderName
card.expiry_month     -> month
card.expiry_year      -> year
card.cvv              -> cvv
card.pan              -> cardNumber
requires_3ds          -> use3D
currency TRY          -> currencyNumber=949
payment channel       -> environment=API for API integration
merchant api token    -> sx
```

Current gaps:

- `successUrl` and `failUrl` are separate in Paynkolay docs; our model has one
  `callback_url`.
- `cardHolderIP` is mandatory in the public request docs; our model does not carry it.
- `rnd` is mandatory and participates in signing; our model does not carry it.
- `sx` replaces the current placeholder `merchant_id/terminal_id/api_key` style boundary.
- Paynkolay uses numeric currency codes in the provider payload.
- Paynkolay's `hashDatav2` spelling should be handled carefully. Docs show both
  `hashDatav2` and `hashDataV2` in different contexts.

### Request Hash

For common payment/API requests, public docs define a SHA-512 Base64 hash over this
pipe-separated string:

```text
sx|clientRefCode|amount|successUrl|failUrl|rnd|customerKey|merchantSecretKey
```

Notes:

- This is plain SHA-512 over UTF-8 bytes, then Base64.
- It is not HMAC.
- `customerKey` is empty when card storage is not used.
- The secret is appended to the canonical string.
- Our current `security.signatures` module only supports hex HMAC signatures, so it needs
  a separate SHA-512/Base64 hash helper rather than reusing HMAC behavior.

### Payment Response / Result

The docs say a successful redirect to `successUrl` alone is not enough to treat payment as
successful.

Payment success requires:

```text
hashDataV2 is valid
RESPONSE_CODE == 2
AUTH_CODE is present and not "0" or "00"
```

Relevant response/result fields:

```text
RESPONSE_CODE
RESPONSE_DATA
USE_3D
RND
MERCHANT_NO
AUTH_CODE
REFERENCE_CODE
CLIENT_REFERENCE_CODE
TIMESTAMP
TRANSACTION_AMOUNT
AUTHORIZATION_AMOUNT
COMMISION
COMMISION_RATE
INSTALLMENT
CURRENCY_CODE
hashData
hashDataV2
```

Provider status mapping likely starts as:

```text
RESPONSE_CODE=2 + valid AUTH_CODE -> authorized/captured
STATUS=SUCCESS                   -> captured or authorized, depending on flow semantics
STATUS=ERROR                     -> failed
STATUS=NEW                       -> created/pending/incomplete
cancel/refund type               -> cancelled/refunded
```

The exact internal status mapping should be confirmed with real sandbox responses before
locking it into production code.

### Response Hash

The response hash uses SHA-512/Base64 over this field order:

```text
MERCHANT_NO|REFERENCE_CODE|AUTH_CODE|RESPONSE_CODE|USE_3D|RND|INSTALLMENT|AUTHORIZATION_AMOUNT|CURRENCY_CODE|MERCHANT_SECRET_KEY
```

This should become a separate verifier for payment result payloads. It is not the same as
the current callback HMAC verifier.

### Transaction Verification / Status Query

The public verification service is form-data:

```text
POST /Payment/PaymentList
```

Fields:

```text
sx
startDate
endDate
clientRefCode
hashDatav2
```

Hash formula:

```text
sx|startDate|endDate|clientRefCode|merchantSecretKey
```

Status values documented:

```text
SUCCESS
ERROR
NEW
```

The docs recommend using a unique `clientRefCode` per transaction. This matches our
existing design rule for unique order IDs/correlation keys.

### Cancel / Refund

Cancel and refund both use:

```text
POST /v1/CancelRefundPayment
```

Fields:

```text
sx
referenceCode
type
amount
trxDate
hashDatav2
```

Hash formula:

```text
sx|referenceCode|type|amount|trxDate|merchantSecretKey
```

Rules from public docs:

- `type=cancel` for same-day cancellation.
- `type=refund` for refund.
- cancel/refund `sx` differs from sales `sx`.
- success is indicated by `responseCode == 2`.

### Test Cards

The official docs publish test cards with expiry, CVV, and sometimes OTP values. Do not
store those full values in tracked files or local guide notes. When we need real sandbox
runs, create a private config JSON outside Git and point `PAYNKOLAY_CONFIG_FILE` to it.

## Implementation Implications

### Recommended Next Code Step

Add Paynkolay-specific hash helpers first, before changing the HTTP client.

Reason:

- The provider contract uses SHA-512/Base64 hashes, while the framework currently uses
  HMAC hex signatures.
- Hash behavior is small, deterministic, and easy to unit test.
- Once hash helpers are correct, the client adapter can reuse them.

Likely new module:

```text
src/paynkolay_pos/security/paynkolay_hashes.py
```

Likely tests:

```text
tests/security/test_paynkolay_hashes.py
```

Expected helpers:

```text
generate_sha512_base64_hash(canonical_payload: str) -> str
generate_payment_request_hash(...)
generate_payment_response_hash(...)
generate_payment_list_hash(...)
generate_cancel_refund_hash(...)
verify_sha512_base64_hash(...)
```

These helpers should:

- preserve exact field order
- preserve empty optional values such as empty `customerKey`
- use UTF-8
- return Base64 text
- avoid logging or returning raw secrets

### Then Adapt Client Boundary

After hash helpers:

- Add form-data POST support.
- Add a provider adapter for `/v1/Payment`.
- Keep internal typed models where useful, but add a conversion layer to Paynkolay field
  names.
- Replace JSON placeholder tests with provider-contract tests using `httpx.MockTransport`.
- Preserve the existing business-facing `PaymentFlow` where possible.

### Then Add Result Verification

Add a typed provider result model or parser for:

- 3D form response containing `BANK_REQUEST_MESSAGE`
- result posts to success/fail URL
- `PaymentList` status query response

The framework should only consider payment success after response hash verification and
business-state checks.

## Inputs Still Needed From User / Merchant Panel

For real sandbox execution, still collect privately:

- whether we should use API v1 "Taksit Bilgisi Size Ait" or the Paynkolay-owned
  installment API version
- real sandbox/prod `sx` values for sales, list, and cancel/refund if different from
  public examples
- real merchant secret key
- success URL and fail URL reachable from Paynkolay during sandbox tests
- callback/webhook behavior, if separate from success/fail redirects
- exact expected 3DS OTP selectors/flow for the chosen test card/bank
- which public test cards are approved for our testing, stored only in a private config
- whether capture is immediate or whether `RESPONSE_CODE=2` should map to `authorized`
  before a later capture step

## Do Not Change Yet

Do not call real Paynkolay endpoints until:

- private config is available
- the user confirms live network calls are allowed
- test amount/card/3DS behavior is agreed
- result verification is implemented
