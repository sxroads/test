"""Provider adapter for real Paynkolay installment option lookups."""

from __future__ import annotations

from decimal import Decimal
from typing import Protocol

import httpx
from pydantic import SecretStr, ValidationError

from paynkolay_pos.clients import PaynkolayClient
from paynkolay_pos.models import (
    PaynkolayInstallmentQuote,
    PaynkolayInstallmentResponse,
)


class InstallmentProviderLookupError(RuntimeError):
    """Raised when provider installment options cannot be retrieved safely."""


class InstallmentOptionUnavailableError(RuntimeError):
    """Raised when a requested installment count is absent from provider quotes."""


class SupportsInstallmentProvider(Protocol):
    """Behavior required by the installment options API."""

    async def get_options(
        self,
        *,
        amount: Decimal,
        card_number: SecretStr,
    ) -> PaynkolayInstallmentResponse:
        """Return provider installment quotes for one card and amount."""


class PaynkolayInstallmentProvider:
    """Fetch and validate Paynkolay installment quotes."""

    def __init__(self, client: PaynkolayClient) -> None:
        self._client = client

    async def get_options(
        self,
        *,
        amount: Decimal,
        card_number: SecretStr,
    ) -> PaynkolayInstallmentResponse:
        """Return successful Paynkolay quotes or a sanitized lookup error."""

        try:
            response = await self._client.get_installment_options(
                amount=amount,
                card_number=card_number,
                is_card_valid=True,
            )
        except (httpx.HTTPError, RuntimeError, TypeError, ValueError, ValidationError) as exc:
            raise InstallmentProviderLookupError(
                "provider installment lookup failed"
            ) from exc

        if not response.successful:
            raise InstallmentProviderLookupError(
                "provider installment lookup was not accepted"
            )
        if not response.quotes:
            raise InstallmentProviderLookupError(
                "provider installment lookup returned no options"
            )
        return response


def select_installment_quote(
    response: PaynkolayInstallmentResponse,
    *,
    installment_count: int,
    currency: str,
) -> PaynkolayInstallmentQuote:
    """Select one currency/count-specific quote without exposing its encoded value."""

    for quote in response.quotes:
        if (
            quote.installment_count == installment_count
            and quote.currency_code.upper() == currency.upper()
        ):
            return quote
    raise InstallmentOptionUnavailableError(
        f"installment count {installment_count} is unavailable for this card and amount"
    )


def local_stub_installment_counts(
    *,
    amount: Decimal,
    currency: str,
) -> tuple[int, ...]:
    """Return deterministic local installment counts shared by UI and parallel runs."""

    if currency.upper() != "TRY" or amount < Decimal("100.00"):
        return (1,)
    return (1, 2, 3, 6, 9, 12)
