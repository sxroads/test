"""Provider payment initialization adapter for the web API."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Protocol

import httpx

from paynkolay_pos.api.schemas import PaymentFormRequest
from paynkolay_pos.clients import PaynkolayClient
from paynkolay_pos.config import EnvironmentName, PaymentEnvironment
from paynkolay_pos.models import (
    Currency,
    PaymentCardInput,
    PaymentInitializeRequest,
    PaynkolayPaymentResult,
    PaynkolayThreeDSInitializeResult,
    TransactionStatusResponse,
    parse_paynkolay_payment_result,
)


class PaymentProviderInitializationError(RuntimeError):
    """Raised when provider payment initialization cannot be completed."""


class PaymentProviderStatusVerificationError(RuntimeError):
    """Raised when provider transaction status verification cannot be completed."""


@dataclass(frozen=True)
class PaymentInitializationOutcome:
    """Typed result returned after a provider initialization attempt."""

    payment_request: PaymentInitializeRequest
    provider_result: PaynkolayThreeDSInitializeResult | PaynkolayPaymentResult
    success_url: str
    fail_url: str


class SupportsPaymentInitializer(Protocol):
    """Behavior required by payment routes to initialize provider payments."""

    async def initialize(
        self,
        request: PaymentFormRequest,
        *,
        order_id: str,
        card_holder_ip: str,
    ) -> PaymentInitializationOutcome:
        """Initialize a payment through the configured provider."""

    async def verify_transaction_status(
        self,
        order_id: str,
        *,
        currency: Currency,
    ) -> TransactionStatusResponse:
        """Verify a transaction through Paynkolay PaymentList."""


class PaynkolayPaymentInitializer:
    """Build Paynkolay form requests and parse provider initialization results."""

    def __init__(
        self,
        *,
        environment: PaymentEnvironment,
        client: PaynkolayClient,
    ) -> None:
        self._environment = environment
        self._client = client

    async def initialize(
        self,
        request: PaymentFormRequest,
        *,
        order_id: str,
        card_holder_ip: str,
    ) -> PaymentInitializationOutcome:
        """Initialize a Paynkolay form payment using the existing provider client."""

        payment_request = self._payment_request(request, order_id=order_id)
        success_url, fail_url = self._result_urls()
        try:
            provider_payload = await self._client.initialize_payment_form(
                payment_request,
                success_url=success_url,
                fail_url=fail_url,
                card_holder_ip=card_holder_ip,
            )
            provider_result = parse_paynkolay_payment_result(provider_payload)
        except (httpx.HTTPError, RuntimeError, TypeError, ValueError) as exc:
            raise PaymentProviderInitializationError(
                "provider payment initialization failed"
            ) from exc

        return PaymentInitializationOutcome(
            payment_request=payment_request,
            provider_result=provider_result,
            success_url=success_url,
            fail_url=fail_url,
        )

    async def verify_transaction_status(
        self,
        order_id: str,
        *,
        currency: Currency,
    ) -> TransactionStatusResponse:
        """Verify a Paynkolay transaction through PaymentList."""

        today = datetime.now()
        start_date = (today - timedelta(days=1)).strftime("%d.%m.%Y")
        end_date = (today + timedelta(days=1)).strftime("%d.%m.%Y")
        try:
            return await self._client.get_transaction_status_from_payment_list(
                order_id,
                start_date=start_date,
                end_date=end_date,
                currency=currency,
            )
        except (httpx.HTTPError, LookupError, RuntimeError, TypeError, ValueError) as exc:
            raise PaymentProviderStatusVerificationError(
                "provider payment status verification failed"
            ) from exc

    def _payment_request(
        self,
        request: PaymentFormRequest,
        *,
        order_id: str,
    ) -> PaymentInitializeRequest:
        callback_url = self._callback_url()
        return PaymentInitializeRequest(
            merchant_id=self._environment.merchant.merchant_id,
            terminal_id=self._environment.merchant.terminal_id,
            order_id=order_id,
            amount=request.amount,
            currency=request.currency,
            callback_url=callback_url,
            card=PaymentCardInput(
                brand=request.card_brand,
                pan=request.card_number,
                expiry_month=request.expiry_month,
                expiry_year=request.expiry_year,
                cvv=request.cvv,
                card_holder=request.card_holder,
            ),
            requires_3ds=request.requires_3ds,
            installment_count=request.installment_count,
            installment_encoded_value=request.installment_encoded_value,
            correlation_id=f"web-{order_id}",
        )

    def _result_urls(self) -> tuple[str, str]:
        if self._environment.name is EnvironmentName.UAT:
            final_url = self._environment.callback_base_url
            return final_url, final_url
        base_url = self._environment.callback_base_url.rstrip("/")
        return (
            f"{base_url}/payments/result/success",
            f"{base_url}/payments/result/fail",
        )

    def _callback_url(self) -> str:
        if self._environment.name is EnvironmentName.UAT:
            return self._environment.callback_base_url
        return f"{self._environment.callback_base_url.rstrip('/')}/callbacks/paynkolay"
