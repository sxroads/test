"""Payment request and response models for Sanal POS API automation."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field, SecretStr
from pydantic.functional_validators import field_validator, model_validator

from paynkolay_pos.config import CardBrand


class StrictPaymentModel(BaseModel):
    """Base model that rejects unexpected payment payload fields."""

    model_config = {
        "extra": "forbid",
        "str_strip_whitespace": True,
        "use_enum_values": False,
    }


class Currency(StrEnum):
    """Currencies supported by the initial Sanal POS test catalogue."""

    TRY = "TRY"
    USD = "USD"
    EUR = "EUR"


class PaymentStatus(StrEnum):
    """Business states a payment can move through during tests."""

    CREATED = "created"
    PENDING_3DS = "pending_3ds"
    AUTHENTICATED = "authenticated"
    AUTHORIZED = "authorized"
    CAPTURED = "captured"
    FAILED = "failed"
    CANCELLED = "cancelled"
    REFUNDED = "refunded"


class PaymentChannel(StrEnum):
    """Payment channel metadata used by scenario coverage and provider payloads."""

    E_COMMERCE = "e_commerce"
    MOTO = "moto"


class PaymentCardInput(StrictPaymentModel):
    """Card details submitted when initializing a payment in test environments."""

    brand: CardBrand
    pan: SecretStr = Field(min_length=12, max_length=19)
    expiry_month: int = Field(ge=1, le=12)
    expiry_year: int = Field(ge=2026, le=2100)
    cvv: SecretStr = Field(min_length=3, max_length=4)
    card_holder: str = Field(default="PAYNKOLAY TEST", min_length=1, max_length=64)

    def model_post_init(self, __context: Any) -> None:
        """Validate sensitive numeric fields after SecretStr parsing."""

        pan = self.pan.get_secret_value()
        if not pan.isdigit():
            raise ValueError("card PAN must contain digits only")

        cvv = self.cvv.get_secret_value()
        if not cvv.isdigit():
            raise ValueError("card CVV must contain digits only")


class PaymentInitializeRequest(StrictPaymentModel):
    """Validated request body for payment initialization."""

    merchant_id: str = Field(min_length=1)
    terminal_id: str = Field(min_length=1)
    order_id: str = Field(min_length=1, max_length=64)
    amount: Decimal = Field(gt=Decimal("0"), max_digits=12, decimal_places=2)
    currency: Currency
    callback_url: str = Field(pattern=r"^https://", min_length=12)
    card: PaymentCardInput
    requires_3ds: bool
    installment_count: int = Field(default=1, ge=1, le=12)
    installment_encoded_value: SecretStr | None = Field(default=None, min_length=1, repr=False)
    payment_channel: PaymentChannel = PaymentChannel.E_COMMERCE
    moto: bool = False
    correlation_id: str = Field(min_length=1, max_length=128)
    signature: str | None = Field(default=None, min_length=64, max_length=128)

    @field_validator("amount")
    @classmethod
    def normalize_amount(cls, amount: Decimal) -> Decimal:
        """Keep payment amounts in provider-friendly two-decimal format."""

        return amount.quantize(Decimal("0.01"))

    @property
    def canonical_amount(self) -> str:
        """Return the exact amount string used in signatures and assertions."""

        return f"{self.amount:.2f}"

    @model_validator(mode="after")
    def validate_payment_channel_metadata(self) -> PaymentInitializeRequest:
        """Keep MoTo flag and payment channel consistent for scenario data."""

        if self.moto and self.payment_channel is not PaymentChannel.MOTO:
            raise ValueError("moto payments must use payment_channel=moto")
        if not self.moto and self.payment_channel is PaymentChannel.MOTO:
            raise ValueError("payment_channel=moto requires moto=true")
        return self

    def signature_payload(self) -> dict[str, object]:
        """Return non-sensitive fields that participate in request signing."""

        return {
            "merchant_id": self.merchant_id,
            "terminal_id": self.terminal_id,
            "order_id": self.order_id,
            "amount": self.canonical_amount,
            "currency": self.currency,
            "callback_url": self.callback_url,
            "requires_3ds": self.requires_3ds,
            "installment_count": self.installment_count,
            "payment_channel": self.payment_channel,
            "moto": self.moto,
            "correlation_id": self.correlation_id,
        }


class PaymentInitializeResponse(StrictPaymentModel):
    """Provider response returned after initializing a payment."""

    order_id: str = Field(min_length=1)
    provider_transaction_id: str | None = Field(default=None, min_length=1)
    status: PaymentStatus
    amount: Decimal = Field(gt=Decimal("0"), max_digits=12, decimal_places=2)
    currency: Currency
    redirect_url: str | None = Field(default=None, pattern=r"^https://")
    failure_code: str | None = Field(default=None, min_length=1)
    failure_reason: str | None = Field(default=None, min_length=1)

    @field_validator("amount")
    @classmethod
    def normalize_amount(cls, amount: Decimal) -> Decimal:
        """Keep response amounts comparable with request amounts."""

        return amount.quantize(Decimal("0.01"))

    @model_validator(mode="after")
    def validate_status_specific_fields(self) -> PaymentInitializeResponse:
        """Ensure state-specific response fields are internally consistent."""

        if self.status is PaymentStatus.PENDING_3DS and self.redirect_url is None:
            raise ValueError("pending_3ds responses must include redirect_url")
        if self.status is PaymentStatus.FAILED and self.failure_code is None:
            raise ValueError("failed responses must include failure_code")
        return self


class TransactionStatusResponse(StrictPaymentModel):
    """Provider status query response used for final payment assertions."""

    order_id: str = Field(min_length=1)
    provider_transaction_id: str = Field(min_length=1)
    status: PaymentStatus
    amount: Decimal = Field(gt=Decimal("0"), max_digits=12, decimal_places=2)
    currency: Currency
    updated_at: datetime
    authorization_code: str | None = Field(default=None, min_length=1)
    failure_code: str | None = Field(default=None, min_length=1)

    @field_validator("amount")
    @classmethod
    def normalize_amount(cls, amount: Decimal) -> Decimal:
        """Keep status amounts comparable with initialization payloads."""

        return amount.quantize(Decimal("0.01"))

    @field_validator("updated_at")
    @classmethod
    def require_timezone(cls, updated_at: datetime) -> datetime:
        """Reject naive timestamps because callback/status ordering depends on timezones."""

        if updated_at.tzinfo is None:
            raise ValueError("updated_at must include timezone information")
        return updated_at.astimezone(UTC)

    @model_validator(mode="after")
    def validate_terminal_state_fields(self) -> TransactionStatusResponse:
        """Require clear evidence fields for approved and failed final states."""

        if (
            self.status in {PaymentStatus.AUTHORIZED, PaymentStatus.CAPTURED}
            and self.authorization_code is None
        ):
            raise ValueError("approved transactions must include authorization_code")
        if self.status is PaymentStatus.FAILED and self.failure_code is None:
            raise ValueError("failed transactions must include failure_code")
        return self
