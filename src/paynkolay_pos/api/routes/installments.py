"""Installment option routes for the browser payment form."""

from __future__ import annotations

from decimal import Decimal
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status

from paynkolay_pos.api.dependencies import get_installment_provider
from paynkolay_pos.api.installment_provider import (
    InstallmentProviderLookupError,
    SupportsInstallmentProvider,
    local_stub_installment_counts,
)
from paynkolay_pos.api.schemas import (
    InstallmentOption,
    InstallmentOptionsRequest,
    InstallmentOptionsResponse,
)
from paynkolay_pos.models import Currency

router = APIRouter(prefix="/api/installments", tags=["installments"])
InstallmentProviderDependency = Annotated[
    SupportsInstallmentProvider | None,
    Depends(get_installment_provider),
]


@router.post("/options", response_model=InstallmentOptionsResponse)
async def installment_options(
    request: InstallmentOptionsRequest,
    provider: InstallmentProviderDependency,
) -> InstallmentOptionsResponse:
    """Return real UAT quotes or deterministic local/mock installment options."""

    if provider is not None and request.currency is Currency.TRY:
        return await _provider_installment_options(request, provider)
    return _stub_installment_options(request)


def _stub_installment_options(request: InstallmentOptionsRequest) -> InstallmentOptionsResponse:
    counts = _stub_installment_counts(request)
    return InstallmentOptionsResponse(
        default_installment=1,
        source="local_stub",
        options=[
            InstallmentOption(
                installment_count=count,
                label=_installment_label(count),
                total_amount=request.canonical_amount,
                monthly_amount=_monthly_amount(request.amount, count),
            )
            for count in counts
        ],
    )


async def _provider_installment_options(
    request: InstallmentOptionsRequest,
    provider: SupportsInstallmentProvider,
) -> InstallmentOptionsResponse:
    try:
        response = await provider.get_options(
            amount=request.amount,
            card_number=request.card_number,
        )
    except InstallmentProviderLookupError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=str(exc),
        ) from exc

    options = [
        InstallmentOption(
            installment_count=quote.installment_count,
            label=_installment_label(quote.installment_count),
            total_amount=f"{quote.authorization_amount:.2f}",
            monthly_amount=f"{quote.installment_amount:.2f}",
            commission_amount=f"{quote.commission_amount:.2f}",
            commission_rate=f"{quote.commission_rate:.2f}",
            encoded_value=quote.encoded_value.get_secret_value(),
        )
        for quote in response.quotes
        if quote.currency_code.upper() == request.currency.value
        and 1 <= quote.installment_count <= 12
    ]
    if not options:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="provider installment lookup returned no supported options",
        )
    default_installment = (
        1
        if any(option.installment_count == 1 for option in options)
        else options[0].installment_count
    )
    return InstallmentOptionsResponse(
        default_installment=default_installment,
        source="paynkolay_uat",
        options=options,
    )


def _stub_installment_counts(request: InstallmentOptionsRequest) -> tuple[int, ...]:
    return local_stub_installment_counts(
        amount=request.amount,
        currency=request.currency.value,
    )


def _installment_label(count: int) -> str:
    if count == 1:
        return "Tek cekim"
    return f"{count} taksit"


def _monthly_amount(amount: Decimal, count: int) -> str:
    return f"{(amount / Decimal(count)).quantize(Decimal('0.01')):.2f}"
