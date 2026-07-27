"""Typed Paynkolay installment quote response models."""

from __future__ import annotations

from decimal import Decimal

from pydantic import BaseModel, Field, SecretStr, field_validator


class PaynkolayInstallmentModel(BaseModel):
    """Provider-facing model that tolerates undocumented response additions."""

    model_config = {
        "extra": "ignore",
        "populate_by_name": True,
        "str_strip_whitespace": True,
    }


class PaynkolayInstallmentQuote(PaynkolayInstallmentModel):
    """One card/amount-specific installment quote returned by Paynkolay."""

    installment_count: int = Field(alias="INSTALLMENT", ge=1)
    installment_amount: Decimal = Field(alias="INSTALLMENT_AMOUNT", gt=Decimal("0"))
    transaction_amount: Decimal = Field(alias="TRANSACTION_AMOUNT", gt=Decimal("0"))
    authorization_amount: Decimal = Field(alias="AUTHORIZATION_AMOUNT", gt=Decimal("0"))
    commission_amount: Decimal = Field(
        default=Decimal("0"),
        alias="COMMISION_AMOUNT",
        ge=Decimal("0"),
    )
    commission_rate: Decimal = Field(
        default=Decimal("0"),
        alias="COMMISION",
        ge=Decimal("0"),
    )
    currency_code: str = Field(default="TRY", alias="CURRENCY_CODE")
    encoded_value: SecretStr = Field(alias="EncodedValue", min_length=1, repr=False)

    @field_validator(
        "installment_amount",
        "transaction_amount",
        "authorization_amount",
        "commission_amount",
        "commission_rate",
    )
    @classmethod
    def normalize_decimal(cls, value: Decimal) -> Decimal:
        """Keep provider decimal values stable for UI formatting and comparisons."""

        return value.quantize(Decimal("0.01"))


class PaynkolayInstallmentResponse(PaynkolayInstallmentModel):
    """Paynkolay installment lookup response."""

    quotes: list[PaynkolayInstallmentQuote] = Field(
        default_factory=list,
        alias="PAYMENT_BANK_LIST",
    )
    response_code: int = Field(alias="RESPONSE_CODE")
    response_data: str = Field(default="", alias="RESPONSE_DATA")
    card_scope: str | None = Field(default=None, alias="CARD_SCOPE")

    @property
    def successful(self) -> bool:
        """Return whether Paynkolay accepted the installment lookup."""

        return self.response_code == 2
