"""Paynkolay provider result models and verification helpers."""

from __future__ import annotations

import json
from datetime import UTC, datetime, tzinfo
from decimal import Decimal
from enum import StrEnum

from pydantic import AliasChoices, Field, SecretStr
from pydantic.functional_validators import field_validator, model_validator

from paynkolay_pos.models.payments import (
    Currency,
    PaymentStatus,
    StrictPaymentModel,
    TransactionStatusResponse,
)
from paynkolay_pos.security import generate_payment_response_hash


class PaynkolayProviderModel(StrictPaymentModel):
    """Base model for provider payloads that may include undocumented extra fields."""

    model_config = {
        "extra": "ignore",
        "str_strip_whitespace": True,
        "use_enum_values": False,
    }


class PaynkolayProviderStatus(StrEnum):
    """Transaction status values returned by Paynkolay verification responses."""

    SUCCESS = "SUCCESS"
    ERROR = "ERROR"
    NEW = "NEW"


class PaynkolayCancelRefundType(StrEnum):
    """Operation types accepted by Paynkolay's cancel/refund service."""

    CANCEL = "cancel"
    REFUND = "refund"


class PaynkolayThreeDSInitializeResult(PaynkolayProviderModel):
    """Provider response containing an HTML form for a 3DS challenge."""

    bank_request_message: str = Field(alias="BANK_REQUEST_MESSAGE", min_length=1)

    @property
    def status(self) -> PaymentStatus:
        """3DS HTML means the payment is waiting for browser authentication."""

        return PaymentStatus.PENDING_3DS


class PaynkolayPaymentResult(PaynkolayProviderModel):
    """Success/fail URL payment result payload sent by Paynkolay."""

    response_code: str = Field(alias="RESPONSE_CODE", min_length=1)
    response_data: str | None = Field(default=None, alias="RESPONSE_DATA")
    use_3d: str = Field(default="", alias="USE_3D")
    rnd: str = Field(default="", alias="RND")
    merchant_no: str = Field(default="", alias="MERCHANT_NO")
    auth_code: str = Field(default="", alias="AUTH_CODE")
    reference_code: str = Field(default="", alias="REFERENCE_CODE")
    client_reference_code: str = Field(default="", alias="CLIENT_REFERENCE_CODE")
    timestamp: str | None = Field(
        default=None,
        validation_alias=AliasChoices("TIMESTAMP", "TimeStamp"),
    )
    transaction_amount: Decimal | None = Field(default=None, alias="TRANSACTION_AMOUNT")
    authorization_amount: Decimal | None = Field(default=None, alias="AUTHORIZATION_AMOUNT")
    commission: Decimal | None = Field(default=None, alias="COMMISION")
    commission_rate: Decimal | None = Field(default=None, alias="COMMISION_RATE")
    installment: int = Field(default=1, alias="INSTALLMENT", ge=1)
    currency_code: Currency = Field(default=Currency.TRY, alias="CURRENCY_CODE")
    hash_data: str | None = Field(default=None, alias="hashData")
    hash_data_v2: str = Field(
        default="",
        validation_alias=AliasChoices("hashDataV2", "hashDatav2"),
    )

    @field_validator(
        "use_3d",
        "rnd",
        "merchant_no",
        "auth_code",
        "reference_code",
        "client_reference_code",
        "hash_data_v2",
        mode="before",
    )
    @classmethod
    def default_nullable_text_fields(cls, value: object) -> object:
        """Accept provider failure payloads that explicitly send null optional text."""

        if value is None:
            return ""
        return value

    @field_validator("installment", mode="before")
    @classmethod
    def default_nullable_installment(cls, value: object) -> object:
        """Accept provider failure payloads that omit installment details."""

        if value is None:
            return 1
        return value

    @field_validator("currency_code", mode="before")
    @classmethod
    def default_nullable_currency(cls, value: object) -> object:
        """Accept provider failure payloads that omit currency details."""

        if value is None:
            return Currency.TRY
        return value

    @field_validator("transaction_amount", "authorization_amount", mode="before")
    @classmethod
    def normalize_amount(cls, amount: object) -> Decimal | None:
        """Keep provider amount strings comparable with internal models."""

        if amount is None:
            return None
        normalized = str(amount).replace(",", ".")
        return Decimal(normalized).quantize(Decimal("0.01"))

    @field_validator("response_code", mode="before")
    @classmethod
    def normalize_response_code(cls, response_code: object) -> str:
        """Accept provider response codes whether they arrive as text or numbers."""

        return str(response_code)

    @model_validator(mode="after")
    def validate_success_hash(self) -> PaynkolayPaymentResult:
        """Require response hash evidence for successful provider approvals."""

        if self.successful and not self.hash_data_v2.strip():
            raise ValueError("successful Paynkolay results must include hashDataV2")
        return self

    @property
    def successful(self) -> bool:
        """Apply Paynkolay's documented payment success rule."""

        normalized_auth_code = self.auth_code.strip()
        return (
            self.response_code == "2"
            and normalized_auth_code not in {"", "0", "00"}
        )

    @property
    def status(self) -> PaymentStatus:
        """Map Paynkolay result fields to the internal payment status enum."""

        if self.successful:
            return PaymentStatus.CAPTURED
        return PaymentStatus.FAILED

    def expected_hash(self, merchant_secret_key: SecretStr | str) -> str:
        """Recalculate the documented response ``hashDataV2`` value."""

        return generate_payment_response_hash(
            merchant_no=self.merchant_no,
            reference_code=self.reference_code,
            auth_code=self.auth_code,
            response_code=self.response_code,
            use_3d=self.use_3d,
            rnd=self.rnd,
            installment=self.installment,
            authorization_amount=self.canonical_authorization_amount,
            currency_code=self.currency_code.value,
            merchant_secret_key=merchant_secret_key,
        )

    def verify_hash(self, merchant_secret_key: SecretStr | str) -> bool:
        """Return whether the provider result hash matches the payload."""

        return self.hash_data_v2 == self.expected_hash(merchant_secret_key)

    @property
    def canonical_authorization_amount(self) -> str:
        """Return the exact authorization amount string used in response hash checks."""

        amount = self.authorization_amount or self.transaction_amount or Decimal("0.00")
        return f"{amount:.2f}"

    def to_transaction_status_response(
        self,
        *,
        source_timezone: tzinfo = UTC,
    ) -> TransactionStatusResponse:
        """Convert a success/fail URL result into the framework status model."""

        payment_status = self.status
        authorization_code = self.auth_code.strip() or None
        amount = self.authorization_amount or self.transaction_amount or Decimal("0.00")
        return TransactionStatusResponse(
            order_id=self.client_reference_code,
            provider_transaction_id=self.reference_code,
            status=payment_status,
            amount=amount,
            currency=self.currency_code,
            updated_at=self._parsed_timestamp(source_timezone),
            authorization_code=(
                authorization_code
                if payment_status in {PaymentStatus.AUTHORIZED, PaymentStatus.CAPTURED}
                else None
            ),
            failure_code=self.response_code if payment_status is PaymentStatus.FAILED else None,
        )

    def _parsed_timestamp(self, source_timezone: tzinfo) -> datetime:
        if self.timestamp is None:
            return datetime.now(UTC)
        try:
            parsed = datetime.fromisoformat(self.timestamp)
        except ValueError:
            parsed = datetime.strptime(self.timestamp, "%m/%d/%Y %I:%M:%S %p")
            return parsed.replace(tzinfo=source_timezone)
        if parsed.tzinfo is None:
            return parsed.replace(tzinfo=source_timezone)
        return parsed


def parse_paynkolay_payment_result(
    payload: dict[str, object],
) -> PaynkolayThreeDSInitializeResult | PaynkolayPaymentResult:
    """Parse a Paynkolay payment response/result into a typed provider model."""

    bank_request_message = payload.get("BANK_REQUEST_MESSAGE")
    if isinstance(bank_request_message, str) and bank_request_message.strip():
        return PaynkolayThreeDSInitializeResult.model_validate(payload)
    normalized_payload = _normalize_payment_result_payload(payload)
    return PaynkolayPaymentResult.model_validate(normalized_payload)


def _normalize_payment_result_payload(payload: dict[str, object]) -> dict[str, object]:
    normalized = dict(payload)
    hash_data_v2 = normalized.get("hashDataV2")
    provider_hash_data_v2 = normalized.get("hashDatav2")
    if hash_data_v2 is None and provider_hash_data_v2 is not None:
        normalized["hashDataV2"] = provider_hash_data_v2
    return normalized


class PaynkolayPaymentListRow(PaynkolayProviderModel):
    """One transaction row returned by Paynkolay's PaymentList service."""

    reference_code: str = Field(alias="REFERENCE_CODE", min_length=1)
    auth_code: str = Field(default="", alias="AUTH_CODE")
    authorization_amount: Decimal = Field(alias="AUTHORIZATION_AMOUNT", gt=Decimal("0"))
    transaction_amount: Decimal | None = Field(default=None, alias="TRANSACTION_AMOUNT")
    client_reference_code: str = Field(alias="CLIENT_REFERENCE_CODE", min_length=1)
    status: PaynkolayProviderStatus = Field(alias="STATUS")
    transaction_type: str | None = Field(default=None, alias="TRANSACTION_TYPE")
    trx_date: str = Field(alias="TRX_DATE", min_length=1)
    card_holder_name: str | None = Field(default=None, alias="CARD_HOLDER_NAME")
    is_3d: bool | None = Field(default=None, alias="IS_3D")
    installment_count: int | None = Field(default=None, alias="INSTALLMENT_COUNT")
    description: str | None = Field(default=None, alias="DESCRIPTION")

    @field_validator("authorization_amount", "transaction_amount")
    @classmethod
    def normalize_optional_amount(cls, amount: Decimal | None) -> Decimal | None:
        """Keep provider amount strings comparable with internal models."""

        if amount is None:
            return None
        return amount.quantize(Decimal("0.01"))

    @property
    def payment_status(self) -> PaymentStatus:
        """Map Paynkolay list status values to internal payment states."""

        if self.status is PaynkolayProviderStatus.SUCCESS:
            return PaymentStatus.CAPTURED
        if self.status is PaynkolayProviderStatus.ERROR:
            return PaymentStatus.FAILED
        return PaymentStatus.CREATED

    def to_transaction_status_response(
        self,
        *,
        currency: Currency = Currency.TRY,
        source_timezone: tzinfo = UTC,
    ) -> TransactionStatusResponse:
        """Convert a provider list row into the framework status model."""

        payment_status = self.payment_status
        failure_code = None
        if payment_status is PaymentStatus.FAILED:
            failure_code = self.description or self.status.value
        return TransactionStatusResponse(
            order_id=self.client_reference_code,
            provider_transaction_id=self.reference_code,
            status=payment_status,
            amount=self.authorization_amount,
            currency=currency,
            updated_at=self._parsed_trx_date(source_timezone),
            authorization_code=self.auth_code.strip() or None,
            failure_code=failure_code,
        )

    def _parsed_trx_date(self, source_timezone: tzinfo) -> datetime:
        try:
            parsed = datetime.strptime(self.trx_date, "%d.%m.%Y %H:%M:%S")
        except ValueError:
            parsed = datetime.fromisoformat(self.trx_date)
        if parsed.tzinfo is not None:
            return parsed
        return parsed.replace(tzinfo=source_timezone)


class PaynkolayPaymentListResult(PaynkolayProviderModel):
    """Inner ``result`` object returned by Paynkolay's PaymentList service."""

    response_code: str = Field(alias="RESPONSE_CODE", min_length=1)
    response_data: str | None = Field(default=None, alias="RESPONSE_DATA")
    rows: tuple[PaynkolayPaymentListRow, ...] = Field(default=(), alias="LIST")

    @field_validator("response_code", mode="before")
    @classmethod
    def normalize_response_code(cls, response_code: object) -> str:
        """Accept provider response codes whether they arrive as text or numbers."""

        return str(response_code)

    @property
    def successful(self) -> bool:
        """Return whether the list service itself succeeded."""

        return self.response_code == "2"


class PaynkolayPaymentListResponse(PaynkolayProviderModel):
    """Typed response returned by Paynkolay's PaymentList verification service."""

    id: str | None = None
    result: PaynkolayPaymentListResult

    @model_validator(mode="before")
    @classmethod
    def normalize_flat_provider_response(cls, payload: object) -> object:
        """Accept documented, flat, and JSON-string live result envelopes."""

        if not isinstance(payload, dict):
            return payload
        result = payload.get("result")
        if isinstance(result, str):
            try:
                decoded_result = json.loads(result)
            except json.JSONDecodeError:
                return payload
            if isinstance(decoded_result, dict):
                return {**payload, "result": decoded_result}
        if "result" not in payload and "RESPONSE_CODE" in payload:
            return {**payload, "result": payload}
        return payload

    def rows_for_client_ref(self, client_ref_code: str) -> tuple[PaynkolayPaymentListRow, ...]:
        """Return all transaction rows matching a merchant client reference code."""

        return tuple(
            row for row in self.result.rows if row.client_reference_code == client_ref_code
        )


class PaynkolayCancelRefundResult(PaynkolayProviderModel):
    """Typed response returned by Paynkolay's cancel/refund service."""

    response_code: str = Field(
        validation_alias=AliasChoices("responseCode", "RESPONSE_CODE"),
        min_length=1,
    )
    response_data: str | None = Field(
        default=None,
        validation_alias=AliasChoices("responseData", "RESPONSE_DATA"),
    )
    transaction_type: PaynkolayCancelRefundType = Field(alias="type")

    @field_validator("response_code", mode="before")
    @classmethod
    def normalize_response_code(cls, response_code: object) -> str:
        """Accept provider response codes whether they arrive as text or numbers."""

        return str(response_code)

    @property
    def successful(self) -> bool:
        """Return whether the cancel/refund service reports success."""

        return self.response_code == "2"

    @property
    def status(self) -> PaymentStatus:
        """Map a successful operation to the internal final payment state."""

        if not self.successful:
            return PaymentStatus.FAILED
        if self.transaction_type is PaynkolayCancelRefundType.CANCEL:
            return PaymentStatus.CANCELLED
        return PaymentStatus.REFUNDED
