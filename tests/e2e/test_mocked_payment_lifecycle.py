from __future__ import annotations

import json
from typing import Any

import httpx
import pytest
from pydantic import SecretStr

from paynkolay_pos.callbacks import CallbackStore
from paynkolay_pos.clients import PaynkolayClient
from paynkolay_pos.config import RuntimeSettings
from paynkolay_pos.flows import PaymentFlow
from paynkolay_pos.models import (
    PaymentInitializeRequest,
    PaymentStatus,
    PaynkolayCancelRefundResult,
    PaynkolayPaymentResult,
    PaynkolayThreeDSInitializeResult,
    parse_paynkolay_payment_result,
)
from paynkolay_pos.scenarios import PaymentScenario
from paynkolay_pos.security import generate_payment_response_hash
from paynkolay_pos.testing import payment_card_payload, signed_callback_payload_model


def runtime_settings() -> RuntimeSettings:
    return RuntimeSettings.model_validate(
        {
            "active_environment": "dev",
            "environments": {
                "dev": {
                    "name": "dev",
                    "base_url": "https://dev-pos.example.test",
                    "callback_base_url": "https://merchant-dev.example.test",
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
            },
        }
    )


def captured_payment_scenario() -> PaymentScenario:
    return PaymentScenario.model_validate(
        {
            "scenario_id": "visa_3ds_capture",
            "title": "Visa 3DS captured payment",
            "card_alias": "visa_3ds_success",
            "amount": "100.00",
            "currency": "TRY",
            "requires_3ds": True,
            "expected_initialize_status": "pending_3ds",
            "expected_final_status": "captured",
            "tags": ("smoke", "three_ds"),
        }
    )


class MockProvider:
    def __init__(self) -> None:
        self.initialize_payload: dict[str, Any] | None = None
        self.status_calls = 0

    async def __call__(self, request: httpx.Request) -> httpx.Response:
        if request.method == "POST" and request.url.path == "/payments/initialize":
            self.initialize_payload = json.loads(request.content)
            return httpx.Response(
                status_code=200,
                json={
                    "order_id": "order-1001",
                    "provider_transaction_id": "txn-1001",
                    "status": "pending_3ds",
                    "amount": "100.00",
                    "currency": "TRY",
                    "redirect_url": "https://acs.example.test/challenge/order-1001",
                },
            )

        if request.method == "GET" and request.url.path == "/payments/order-1001/status":
            self.status_calls += 1
            status = "authenticated" if self.status_calls == 1 else "captured"
            payload: dict[str, object] = {
                "order_id": "order-1001",
                "provider_transaction_id": "txn-1001",
                "status": status,
                "amount": "100.00",
                "currency": "TRY",
                "updated_at": "2026-07-02T12:00:00+03:00",
            }
            if status == "captured":
                payload["authorization_code"] = "auth-1001"
            return httpx.Response(status_code=200, json=payload)

        return httpx.Response(status_code=404, json={"error": "not_found"})


class MockPaynkolayFormProvider:
    def __init__(
        self,
        *,
        client_reference_code: str = "order-1001",
        reference_code: str = "IKSIRPF102168",
        provider_status: str = "SUCCESS",
        auth_code: str = "S00586",
        description: str = "",
        cancel_refund_response_code: int = 2,
        cancel_refund_response_data: str = "Islem basarili",
    ) -> None:
        self.client_reference_code = client_reference_code
        self.reference_code = reference_code
        self.provider_status = provider_status
        self.auth_code = auth_code
        self.description = description
        self.cancel_refund_response_code = cancel_refund_response_code
        self.cancel_refund_response_data = cancel_refund_response_data
        self.payment_request: httpx.Request | None = None
        self.payment_list_request: httpx.Request | None = None
        self.cancel_refund_request: httpx.Request | None = None

    async def __call__(self, request: httpx.Request) -> httpx.Response:
        if request.method == "POST" and request.url.path == "/v1/Payment":
            self.payment_request = request
            return httpx.Response(
                status_code=200,
                json={"BANK_REQUEST_MESSAGE": "<form>3DS challenge</form>"},
            )

        if request.method == "POST" and request.url.path == "/Payment/PaymentList":
            self.payment_list_request = request
            return httpx.Response(
                status_code=200,
                json={
                    "id": "",
                    "result": {
                        "RESPONSE_CODE": "2",
                        "RESPONSE_DATA": "Islem basarili",
                        "LIST": [
                            {
                                "REFERENCE_CODE": self.reference_code,
                                "AUTH_CODE": self.auth_code,
                                "AUTHORIZATION_AMOUNT": "100.00",
                                "TRANSACTION_AMOUNT": "100.00",
                                "CLIENT_REFERENCE_CODE": self.client_reference_code,
                                "STATUS": self.provider_status,
                                "TRANSACTION_TYPE": "SALES",
                                "TRX_DATE": "03.07.2026 09:45:00",
                                "CARD_HOLDER_NAME": "TEST-AUTOMATION",
                                "IS_3D": True,
                                "INSTALLMENT_COUNT": "1",
                                "DESCRIPTION": self.description,
                            }
                        ],
                    },
                },
            )

        if request.method == "POST" and request.url.path == "/v1/CancelRefundPayment":
            self.cancel_refund_request = request
            return httpx.Response(
                status_code=200,
                json={
                    "responseCode": self.cancel_refund_response_code,
                    "responseData": self.cancel_refund_response_data,
                },
            )

        return httpx.Response(status_code=404, json={"error": "not_found"})


def paynkolay_success_result_payload() -> dict[str, object]:
    payload: dict[str, object] = {
        "RESPONSE_CODE": "2",
        "RESPONSE_DATA": "Islem Basarili",
        "USE_3D": "true",
        "RND": "1630051651137",
        "MERCHANT_NO": "400000001",
        "AUTH_CODE": "S00586",
        "REFERENCE_CODE": "IKSIRPF102168",
        "CLIENT_REFERENCE_CODE": "order-1001",
        "TIMESTAMP": "2026-07-03 09:45:00.000",
        "TRANSACTION_AMOUNT": "100.00",
        "AUTHORIZATION_AMOUNT": "100.00",
        "COMMISION": "0.00",
        "COMMISION_RATE": "0.0000",
        "INSTALLMENT": "1",
        "CURRENCY_CODE": "TRY",
        "hashData": "legacy-hash",
        "hashDataV2": "",
    }
    payload["hashDataV2"] = generate_payment_response_hash(
        merchant_no="400000001",
        reference_code="IKSIRPF102168",
        auth_code="S00586",
        response_code="2",
        use_3d="true",
        rnd="1630051651137",
        installment="1",
        authorization_amount="100.00",
        currency_code="TRY",
        merchant_secret_key="secret-dev",
    )
    return payload


def paynkolay_declined_result_payload() -> dict[str, object]:
    payload = paynkolay_success_result_payload()
    payload.update(
        {
            "RESPONSE_CODE": "99",
            "RESPONSE_DATA": "Issuer declined",
            "AUTH_CODE": "",
            "REFERENCE_CODE": "IKSIRPF102169",
            "CLIENT_REFERENCE_CODE": "order-2002",
            "hashDataV2": "",
        }
    )
    payload["hashDataV2"] = generate_payment_response_hash(
        merchant_no="400000001",
        reference_code="IKSIRPF102169",
        auth_code="",
        response_code="99",
        use_3d="true",
        rnd="1630051651137",
        installment="1",
        authorization_amount="100.00",
        currency_code="TRY",
        merchant_secret_key="secret-dev",
    )
    return payload


@pytest.mark.api
@pytest.mark.callback
@pytest.mark.asyncio
async def test_mocked_payment_lifecycle_confirms_final_status_and_callback() -> None:
    settings = runtime_settings()
    scenario = captured_payment_scenario()
    request = PaymentInitializeRequest.model_validate(
        scenario.payment_request_payload(
            merchant_id=settings.current.merchant.merchant_id,
            terminal_id=settings.current.merchant.terminal_id,
            callback_url=f"{settings.current.callback_base_url}/callback",
            card=payment_card_payload(),
            order_id="order-1001",
            correlation_id="corr-1001",
        )
    )
    provider = MockProvider()

    async with PaynkolayClient(
        settings.current,
        transport=httpx.MockTransport(provider),
    ) as client:
        flow = PaymentFlow(client)

        initialize_response = await flow.initialize(request)
        final_status = await flow.wait_for_final_status(
            request.order_id,
            timeout_seconds=5.0,
            poll_interval_seconds=0.01,
        )

    callback_store = CallbackStore()
    callback_store.add(
        signed_callback_payload_model(
            secret_key=SecretStr("secret-dev"),
            order_id=request.order_id,
            provider_transaction_id=final_status.provider_transaction_id,
            status=final_status.status,
            amount=f"{final_status.amount:.2f}",
            currency=final_status.currency,
        )
    )
    confirmed_callback = await flow.wait_for_verified_callback(
        request,
        final_status,
        callback_store=callback_store,
        secret_key=settings.current.merchant.secret_key,
    )

    assert initialize_response.status is scenario.expected_initialize_status
    assert final_status.status is scenario.expected_final_status
    assert confirmed_callback.status is PaymentStatus.CAPTURED
    assert provider.status_calls == 2
    assert provider.initialize_payload is not None
    assert provider.initialize_payload["order_id"] == "order-1001"
    assert provider.initialize_payload["signature"] != "<redacted>"


@pytest.mark.api
@pytest.mark.three_ds
@pytest.mark.smoke
@pytest.mark.asyncio
async def test_mocked_paynkolay_form_lifecycle_confirms_result_and_payment_list_status() -> None:
    settings = runtime_settings()
    scenario = captured_payment_scenario()
    request = PaymentInitializeRequest.model_validate(
        scenario.payment_request_payload(
            merchant_id=settings.current.merchant.merchant_id,
            terminal_id=settings.current.merchant.terminal_id,
            callback_url=f"{settings.current.callback_base_url}/callback",
            card=payment_card_payload(),
            order_id="order-1001",
            correlation_id="corr-1001",
        )
    )
    provider = MockPaynkolayFormProvider()

    async with PaynkolayClient(
        settings.current,
        transport=httpx.MockTransport(provider),
    ) as client:
        initialize_payload = await client.initialize_payment_form(
            request,
            success_url=f"{settings.current.callback_base_url}/success",
            fail_url=f"{settings.current.callback_base_url}/fail",
            card_holder_ip="185.125.190.58",
            rnd="03-07-2026 09:45:00",
        )
        initialize_result = parse_paynkolay_payment_result(initialize_payload)

        result_payload = paynkolay_success_result_payload()
        payment_result = parse_paynkolay_payment_result(result_payload)
        if not isinstance(payment_result, PaynkolayPaymentResult):
            raise TypeError("expected Paynkolay payment result payload")
        result_status = payment_result.to_transaction_status_response()

        final_status = await client.get_transaction_status_from_payment_list(
            request.order_id,
            start_date="01.07.2026",
            end_date="31.07.2026",
        )
        refund_result = await client.refund_payment(
            reference_code=payment_result.reference_code,
            amount=payment_result.canonical_authorization_amount,
            trx_date="2026.07.03",
            sx=SecretStr("cancel-refund-sx"),
        )

    assert isinstance(initialize_result, PaynkolayThreeDSInitializeResult)
    assert initialize_result.status is PaymentStatus.PENDING_3DS
    assert isinstance(payment_result, PaynkolayPaymentResult)
    assert payment_result.verify_hash(settings.current.merchant.secret_key)
    assert payment_result.successful is True
    assert payment_result.status is scenario.expected_final_status
    assert result_status.status is scenario.expected_final_status
    assert result_status.order_id == request.order_id
    assert result_status.provider_transaction_id == payment_result.reference_code
    assert final_status.status is scenario.expected_final_status
    assert final_status.provider_transaction_id == payment_result.reference_code
    assert final_status.provider_transaction_id == result_status.provider_transaction_id
    assert final_status.amount == result_status.amount
    assert final_status.currency is result_status.currency
    assert isinstance(refund_result, PaynkolayCancelRefundResult)
    assert refund_result.status is PaymentStatus.REFUNDED
    assert refund_result.successful is True
    assert provider.payment_request is not None
    assert provider.payment_request.url.path == "/v1/Payment"
    assert b'name="hashDatav2"' in provider.payment_request.content
    assert provider.payment_list_request is not None
    assert provider.payment_list_request.url.path == "/Payment/PaymentList"
    assert b'name="clientRefCode"' in provider.payment_list_request.content
    assert provider.cancel_refund_request is not None
    assert provider.cancel_refund_request.url.path == "/v1/CancelRefundPayment"
    assert b'name="referenceCode"' in provider.cancel_refund_request.content
    assert b"IKSIRPF102168" in provider.cancel_refund_request.content
    assert b'name="type"' in provider.cancel_refund_request.content
    assert b"refund" in provider.cancel_refund_request.content
    assert b"cancel-refund-sx" in provider.cancel_refund_request.content


@pytest.mark.api
@pytest.mark.three_ds
@pytest.mark.asyncio
async def test_mocked_paynkolay_form_lifecycle_cancels_captured_payment() -> None:
    settings = runtime_settings()
    scenario = captured_payment_scenario()
    request = PaymentInitializeRequest.model_validate(
        scenario.payment_request_payload(
            merchant_id=settings.current.merchant.merchant_id,
            terminal_id=settings.current.merchant.terminal_id,
            callback_url=f"{settings.current.callback_base_url}/callback",
            card=payment_card_payload(),
            order_id="order-1001",
            correlation_id="corr-1001-cancel",
        )
    )
    provider = MockPaynkolayFormProvider()

    async with PaynkolayClient(
        settings.current,
        transport=httpx.MockTransport(provider),
    ) as client:
        result_payload = paynkolay_success_result_payload()
        payment_result = parse_paynkolay_payment_result(result_payload)
        if not isinstance(payment_result, PaynkolayPaymentResult):
            raise TypeError("expected Paynkolay payment result payload")

        final_status = await client.get_transaction_status_from_payment_list(
            request.order_id,
            start_date="01.07.2026",
            end_date="31.07.2026",
        )
        cancel_result = await client.cancel_payment(
            reference_code=payment_result.reference_code,
            amount=payment_result.canonical_authorization_amount,
            trx_date="2026.07.03",
            sx=SecretStr("cancel-refund-sx"),
        )

    assert final_status.status is scenario.expected_final_status
    assert final_status.provider_transaction_id == payment_result.reference_code
    assert isinstance(cancel_result, PaynkolayCancelRefundResult)
    assert cancel_result.successful is True
    assert cancel_result.status is PaymentStatus.CANCELLED
    assert provider.cancel_refund_request is not None
    assert provider.cancel_refund_request.url.path == "/v1/CancelRefundPayment"
    assert b'name="referenceCode"' in provider.cancel_refund_request.content
    assert b"IKSIRPF102168" in provider.cancel_refund_request.content
    assert b'name="type"' in provider.cancel_refund_request.content
    assert b"cancel" in provider.cancel_refund_request.content


@pytest.mark.api
@pytest.mark.negative
@pytest.mark.asyncio
async def test_mocked_paynkolay_form_lifecycle_reports_failed_refund() -> None:
    settings = runtime_settings()
    scenario = captured_payment_scenario()
    request = PaymentInitializeRequest.model_validate(
        scenario.payment_request_payload(
            merchant_id=settings.current.merchant.merchant_id,
            terminal_id=settings.current.merchant.terminal_id,
            callback_url=f"{settings.current.callback_base_url}/callback",
            card=payment_card_payload(),
            order_id="order-1001",
            correlation_id="corr-1001-refund-failed",
        )
    )
    provider = MockPaynkolayFormProvider(
        cancel_refund_response_code=99,
        cancel_refund_response_data="Reference code not found",
    )

    async with PaynkolayClient(
        settings.current,
        transport=httpx.MockTransport(provider),
    ) as client:
        final_status = await client.get_transaction_status_from_payment_list(
            request.order_id,
            start_date="01.07.2026",
            end_date="31.07.2026",
        )
        refund_result = await client.refund_payment(
            reference_code="missing-reference",
            amount=final_status.amount,
            trx_date="2026.07.03",
            sx=SecretStr("cancel-refund-sx"),
        )

    assert final_status.status is scenario.expected_final_status
    assert isinstance(refund_result, PaynkolayCancelRefundResult)
    assert refund_result.successful is False
    assert refund_result.status is PaymentStatus.FAILED
    assert refund_result.response_code == "99"
    assert refund_result.response_data == "Reference code not found"
    assert provider.cancel_refund_request is not None
    assert provider.cancel_refund_request.url.path == "/v1/CancelRefundPayment"
    assert b"missing-reference" in provider.cancel_refund_request.content
    assert b'name="type"' in provider.cancel_refund_request.content
    assert b"refund" in provider.cancel_refund_request.content


@pytest.mark.api
@pytest.mark.three_ds
@pytest.mark.negative
@pytest.mark.asyncio
async def test_mocked_paynkolay_form_lifecycle_confirms_declined_result_status() -> None:
    settings = runtime_settings()
    scenario = captured_payment_scenario()
    request = PaymentInitializeRequest.model_validate(
        scenario.payment_request_payload(
            merchant_id=settings.current.merchant.merchant_id,
            terminal_id=settings.current.merchant.terminal_id,
            callback_url=f"{settings.current.callback_base_url}/callback",
            card=payment_card_payload(),
            order_id="order-2002",
            correlation_id="corr-2002",
        )
    )
    provider = MockPaynkolayFormProvider(
        client_reference_code="order-2002",
        reference_code="IKSIRPF102169",
        provider_status="ERROR",
        auth_code="",
        description="Issuer declined",
    )

    async with PaynkolayClient(
        settings.current,
        transport=httpx.MockTransport(provider),
    ) as client:
        initialize_payload = await client.initialize_payment_form(
            request,
            success_url=f"{settings.current.callback_base_url}/success",
            fail_url=f"{settings.current.callback_base_url}/fail",
            card_holder_ip="185.125.190.58",
            rnd="03-07-2026 09:45:00",
        )
        initialize_result = parse_paynkolay_payment_result(initialize_payload)

        result_payload = paynkolay_declined_result_payload()
        payment_result = parse_paynkolay_payment_result(result_payload)
        if not isinstance(payment_result, PaynkolayPaymentResult):
            raise TypeError("expected Paynkolay payment result payload")
        result_status = payment_result.to_transaction_status_response()

        final_status = await client.get_transaction_status_from_payment_list(
            request.order_id,
            start_date="01.07.2026",
            end_date="31.07.2026",
        )

    assert isinstance(initialize_result, PaynkolayThreeDSInitializeResult)
    assert initialize_result.status is PaymentStatus.PENDING_3DS
    assert payment_result.verify_hash(settings.current.merchant.secret_key)
    assert payment_result.successful is False
    assert result_status.status is PaymentStatus.FAILED
    assert final_status.status is PaymentStatus.FAILED
    assert result_status.order_id == request.order_id
    assert final_status.order_id == request.order_id
    assert result_status.provider_transaction_id == final_status.provider_transaction_id
    assert result_status.amount == final_status.amount
    assert result_status.currency is final_status.currency
    assert result_status.failure_code == "99"
    assert final_status.failure_code == "Issuer declined"
    assert provider.payment_request is not None
    assert provider.payment_request.url.path == "/v1/Payment"
    assert provider.payment_list_request is not None
    assert provider.payment_list_request.url.path == "/Payment/PaymentList"
    assert provider.cancel_refund_request is None
