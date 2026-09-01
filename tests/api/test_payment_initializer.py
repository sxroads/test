from __future__ import annotations

from typing import Any, cast

import httpx
import pytest

from paynkolay_pos.api.payment_initializer import (
    PaymentProviderInitializationError,
    PaymentProviderStatusVerificationError,
    PaynkolayPaymentInitializer,
)
from paynkolay_pos.api.schemas import PaymentFormRequest
from paynkolay_pos.clients import PaynkolayClient
from paynkolay_pos.config import PaymentEnvironment
from paynkolay_pos.models import (
    Currency,
    PaymentInitializeRequest,
    PaymentStatus,
    PaynkolayThreeDSInitializeResult,
    TransactionStatusResponse,
)


class StubPaynkolayClient:
    def __init__(self, payload: dict[str, object]) -> None:
        self.payload = payload
        self.calls: list[dict[str, object]] = []
        self.status_calls: list[dict[str, object]] = []

    async def initialize_payment_form(
        self,
        request: PaymentInitializeRequest,
        *,
        success_url: str,
        fail_url: str,
        card_holder_ip: str,
        rnd: str | None = None,
        customer_key: str = "",
        merchant_customer_no: str = "",
    ) -> dict[str, Any]:
        self.calls.append(
            {
                "request": request,
                "success_url": success_url,
                "fail_url": fail_url,
                "card_holder_ip": card_holder_ip,
                "rnd": rnd,
                "customer_key": customer_key,
                "merchant_customer_no": merchant_customer_no,
            }
        )
        return self.payload

    async def get_transaction_status_from_payment_list(
        self,
        order_id: str,
        *,
        start_date: str,
        end_date: str,
        currency: Currency = Currency.TRY,
    ) -> TransactionStatusResponse:
        self.status_calls.append(
            {
                "order_id": order_id,
                "start_date": start_date,
                "end_date": end_date,
                "currency": currency,
            }
        )
        return TransactionStatusResponse.model_validate(
            {
                "order_id": order_id,
                "provider_transaction_id": "ref-status",
                "status": PaymentStatus.CAPTURED,
                "amount": "100.00",
                "currency": currency,
                "updated_at": "2026-07-07T12:00:00+00:00",
                "authorization_code": "AUTHSTAT",
            }
        )


class FailingPaynkolayClient:
    async def initialize_payment_form(
        self,
        request: PaymentInitializeRequest,
        *,
        success_url: str,
        fail_url: str,
        card_holder_ip: str,
        rnd: str | None = None,
        customer_key: str = "",
        merchant_customer_no: str = "",
    ) -> dict[str, Any]:
        raise httpx.ConnectError("provider unavailable")

    async def get_transaction_status_from_payment_list(
        self,
        order_id: str,
        *,
        start_date: str,
        end_date: str,
        currency: Currency = Currency.TRY,
    ) -> TransactionStatusResponse:
        raise httpx.ConnectError("provider unavailable")


def payment_environment() -> PaymentEnvironment:
    return PaymentEnvironment.model_validate(
        {
            "name": "dev",
            "base_url": "https://paynkolay.example.test",
            "callback_base_url": "https://merchant.example.test",
            "merchant": {
                "merchant_id": "merchant-dev",
                "terminal_id": "terminal-dev",
                "api_key": "api-key-dev",
                "secret_key": "secret-dev",
            },
            "cards": [
                {
                    "alias": "visa_3ds_success",
                    "brand": "visa",
                    "pan": "4111111111111111",
                    "expiry_month": 12,
                    "expiry_year": 2030,
                    "cvv": "123",
                    "requires_3ds": True,
                    "expected_otp": "123456",
                }
            ],
        }
    )


def payment_form_request() -> PaymentFormRequest:
    return PaymentFormRequest.model_validate(
        {
            "amount": "100.00",
            "currency": "TRY",
            "card_brand": "visa",
            "card_number": "4111111111111111",
            "card_holder": "TEST-AUTOMATION",
            "expiry_month": 12,
            "expiry_year": 2030,
            "cvv": "123",
            "requires_3ds": True,
            "installment_count": 1,
        }
    )


@pytest.mark.api
@pytest.mark.asyncio
async def test_paynkolay_payment_initializer_builds_form_request() -> None:
    client = StubPaynkolayClient({"BANK_REQUEST_MESSAGE": "<form>3DS</form>"})
    initializer = PaynkolayPaymentInitializer(
        environment=payment_environment(),
        client=cast(PaynkolayClient, client),
    )

    outcome = await initializer.initialize(
        payment_form_request(),
        order_id="order-web-1001",
        card_holder_ip="185.125.190.58",
    )

    assert isinstance(outcome.provider_result, PaynkolayThreeDSInitializeResult)
    assert outcome.success_url == "https://merchant.example.test/payments/result/success"
    assert outcome.fail_url == "https://merchant.example.test/payments/result/fail"
    assert len(client.calls) == 1
    call = client.calls[0]
    sent_request = call["request"]
    assert isinstance(sent_request, PaymentInitializeRequest)
    assert sent_request.order_id == "order-web-1001"
    assert sent_request.merchant_id == "merchant-dev"
    assert sent_request.terminal_id == "terminal-dev"
    assert sent_request.callback_url == "https://merchant.example.test/callbacks/paynkolay"
    assert call["card_holder_ip"] == "185.125.190.58"


@pytest.mark.api
@pytest.mark.asyncio
async def test_paynkolay_payment_initializer_uses_final_callback_endpoint_for_uat() -> None:
    environment_payload = payment_environment().model_dump()
    environment_payload["name"] = "uat"
    environment_payload["callback_base_url"] = "https://paynkolay.com.tr/test/callback"
    environment = PaymentEnvironment.model_validate(environment_payload)
    client = StubPaynkolayClient({"BANK_REQUEST_MESSAGE": "<form>3DS</form>"})
    initializer = PaynkolayPaymentInitializer(
        environment=environment,
        client=cast(PaynkolayClient, client),
    )

    outcome = await initializer.initialize(
        payment_form_request(),
        order_id="order-uat-1001",
        card_holder_ip="185.125.190.58",
    )

    assert outcome.success_url == "https://paynkolay.com.tr/test/callback"
    assert outcome.fail_url == "https://paynkolay.com.tr/test/callback"
    call = client.calls[0]
    sent_request = call["request"]
    assert isinstance(sent_request, PaymentInitializeRequest)
    assert sent_request.callback_url == "https://paynkolay.com.tr/test/callback"


@pytest.mark.api
@pytest.mark.asyncio
async def test_paynkolay_payment_initializer_wraps_provider_errors() -> None:
    initializer = PaynkolayPaymentInitializer(
        environment=payment_environment(),
        client=cast(PaynkolayClient, FailingPaynkolayClient()),
    )

    with pytest.raises(PaymentProviderInitializationError):
        await initializer.initialize(
            payment_form_request(),
            order_id="order-web-1001",
            card_holder_ip="185.125.190.58",
        )


@pytest.mark.api
@pytest.mark.asyncio
async def test_paynkolay_payment_initializer_verifies_payment_list_status() -> None:
    client = StubPaynkolayClient({"BANK_REQUEST_MESSAGE": "<form>3DS</form>"})
    initializer = PaynkolayPaymentInitializer(
        environment=payment_environment(),
        client=cast(PaynkolayClient, client),
    )

    response = await initializer.verify_transaction_status(
        "order-web-1001",
        currency=Currency.TRY,
    )

    assert response.status is PaymentStatus.CAPTURED
    assert response.provider_transaction_id == "ref-status"
    assert client.status_calls[0]["order_id"] == "order-web-1001"


@pytest.mark.api
@pytest.mark.asyncio
async def test_paynkolay_payment_initializer_wraps_payment_list_errors() -> None:
    initializer = PaynkolayPaymentInitializer(
        environment=payment_environment(),
        client=cast(PaynkolayClient, FailingPaynkolayClient()),
    )

    with pytest.raises(PaymentProviderStatusVerificationError):
        await initializer.verify_transaction_status(
            "order-web-1001",
            currency=Currency.TRY,
        )
