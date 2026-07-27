from __future__ import annotations

import json
from decimal import Decimal

import httpx
import pytest
from pydantic import SecretStr

from paynkolay_pos.clients import PaynkolayClient
from paynkolay_pos.config import RuntimeSettings
from paynkolay_pos.models import PaymentStatus
from paynkolay_pos.security import (
    generate_cancel_refund_hash,
    generate_payment_list_hash,
    generate_payment_request_hash,
)
from paynkolay_pos.testing import payment_initialize_request


def valid_settings_payload() -> dict[str, object]:
    return {
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
                    "installment_api_key": "installment-api-key-dev",
                    "list_api_key": "list-api-key-dev",
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


@pytest.mark.api
@pytest.mark.asyncio
async def test_client_posts_json_with_environment_headers() -> None:
    settings = RuntimeSettings.model_validate(valid_settings_payload())
    captured_request: httpx.Request | None = None

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal captured_request
        captured_request = request
        return httpx.Response(
            status_code=200,
            json={"status": "ok", "echo": request.url.path},
        )

    async with PaynkolayClient(
        settings.current,
        transport=httpx.MockTransport(handler),
    ) as client:
        response = await client.post_json("/payments/initialize", {"order_id": "order-1001"})

    assert response == {"status": "ok", "echo": "/payments/initialize"}
    assert captured_request is not None
    assert str(captured_request.url) == "https://dev-pos.example.test/payments/initialize"
    assert captured_request.headers["X-Merchant-Id"] == "merchant-dev"
    assert captured_request.headers["X-Terminal-Id"] == "terminal-dev"


@pytest.mark.api
@pytest.mark.asyncio
async def test_client_rejects_non_object_json_response() -> None:
    settings = RuntimeSettings.model_validate(valid_settings_payload())

    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status_code=200, json=["not", "an", "object"])

    async with PaynkolayClient(
        settings.current,
        transport=httpx.MockTransport(handler),
    ) as client:
        with pytest.raises(TypeError, match="provider response must be a JSON object"):
            await client.post_json("/payments/initialize", {"order_id": "order-1001"})


@pytest.mark.api
@pytest.mark.asyncio
async def test_client_accepts_json_object_encoded_as_json_string() -> None:
    settings = RuntimeSettings.model_validate(valid_settings_payload())

    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            status_code=200,
            json=json.dumps({"id": "", "result": {"RESPONSE_CODE": "2"}}),
        )

    async with PaynkolayClient(
        settings.current,
        transport=httpx.MockTransport(handler),
    ) as client:
        response = await client.post_form("/Payment/PaymentList", {"clientRefCode": "order-1001"})

    assert response == {"id": "", "result": {"RESPONSE_CODE": "2"}}


@pytest.mark.api
@pytest.mark.asyncio
async def test_client_raises_for_provider_http_errors() -> None:
    settings = RuntimeSettings.model_validate(valid_settings_payload())

    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status_code=401, json={"error": "unauthorized"})

    async with PaynkolayClient(
        settings.current,
        transport=httpx.MockTransport(handler),
    ) as client:
        with pytest.raises(httpx.HTTPStatusError):
            await client.post_json("/payments/initialize", {"order_id": "order-1001"})


@pytest.mark.api
@pytest.mark.asyncio
async def test_client_posts_multipart_form_data() -> None:
    settings = RuntimeSettings.model_validate(valid_settings_payload())
    captured_request: httpx.Request | None = None

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal captured_request
        captured_request = request
        return httpx.Response(status_code=200, json={"status": "ok"})

    async with PaynkolayClient(
        settings.current,
        transport=httpx.MockTransport(handler),
    ) as client:
        response = await client.post_form("/v1/Payment", {"clientRefCode": "order-1001"})

    assert response == {"status": "ok"}
    assert captured_request is not None
    assert str(captured_request.url) == "https://dev-pos.example.test/v1/Payment"
    assert captured_request.headers["content-type"].startswith("multipart/form-data")
    assert b'name="clientRefCode"' in captured_request.content
    assert b"order-1001" in captured_request.content


@pytest.mark.api
@pytest.mark.asyncio
async def test_installment_lookup_uses_dedicated_sx_and_parses_quotes() -> None:
    settings = RuntimeSettings.model_validate(valid_settings_payload())
    captured_request: httpx.Request | None = None

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal captured_request
        captured_request = request
        return httpx.Response(
            status_code=200,
            json={
                "PAYMENT_BANK_LIST": [
                    {
                        "INSTALLMENT_AMOUNT": 350.88,
                        "INSTALLMENT": 3,
                        "COMMISION_AMOUNT": 52.63,
                        "COMMISION": 5,
                        "TRANSACTION_AMOUNT": 1000,
                        "AUTHORIZATION_AMOUNT": 1052.63,
                        "EncodedValue": "opaque-provider-quote",
                        "CURRENCY_CODE": "TRY",
                    }
                ],
                "RESPONSE_DATA": "İşlem Başarılı.",
                "RESPONSE_CODE": 2,
            },
        )

    async with PaynkolayClient(
        settings.current,
        transport=httpx.MockTransport(handler),
    ) as client:
        response = await client.get_installment_options(
            amount="1000.00",
            card_number=SecretStr("4111111111111111"),
        )

    assert response.successful is True
    assert response.quotes[0].installment_count == 3
    assert captured_request is not None
    assert captured_request.url.path == "/Payment/PaymentInstallments"
    assert b'installment-api-key-dev' in captured_request.content
    assert b'name="amount"' in captured_request.content
    assert b"1000.00" in captured_request.content
    assert b'name="cardNumber"' in captured_request.content
    assert b"4111111111111111" in captured_request.content
    assert b'name="iscardvalid"' in captured_request.content
    assert b"true" in captured_request.content


@pytest.mark.api
@pytest.mark.asyncio
async def test_initialize_payment_signs_request_and_parses_response() -> None:
    settings = RuntimeSettings.model_validate(valid_settings_payload())
    captured_payload: dict[str, object] | None = None

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal captured_payload
        captured_payload = json.loads(request.content)
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

    payment_request = payment_initialize_request()

    async with PaynkolayClient(
        settings.current,
        transport=httpx.MockTransport(handler),
    ) as client:
        response = await client.initialize_payment(payment_request)

    assert response.status is PaymentStatus.PENDING_3DS
    assert response.provider_transaction_id == "txn-1001"
    assert captured_payload is not None
    assert captured_payload["signature"] == (
        "e97f9342129169b35e8e760e243dcfc8"
        "33d390f0cbb991c9d8c6d99ac7b88d3f"
    )
    assert captured_payload["card"] == {
        "brand": "visa",
        "pan": "4111111111111111",
        "expiry_month": 12,
        "expiry_year": 2030,
        "cvv": "123",
        "card_holder": "PAYNKOLAY TEST",
    }
    assert captured_payload["installment_count"] == 1
    assert captured_payload["payment_channel"] == "e_commerce"
    assert captured_payload["moto"] is False


@pytest.mark.api
@pytest.mark.smoke
@pytest.mark.asyncio
async def test_payment_form_payload_maps_internal_request_to_paynkolay_fields() -> None:
    settings = RuntimeSettings.model_validate(valid_settings_payload())
    payment_request = payment_initialize_request()

    async with PaynkolayClient(settings.current) as client:
        payload = client.payment_form_payload(
            payment_request,
            success_url="https://merchant.example.test/success",
            fail_url="https://merchant.example.test/fail",
            card_holder_ip=" 185.125.190.58 ",
            rnd="03-07-2026 09:45:00",
        )

    expected_hash = generate_payment_request_hash(
        sx=settings.current.merchant.api_key,
        client_ref_code="order-1001",
        amount="100.00",
        success_url="https://merchant.example.test/success",
        fail_url="https://merchant.example.test/fail",
        rnd="03-07-2026 09:45:00",
        merchant_secret_key=settings.current.merchant.secret_key,
    )
    assert payload == {
        "sx": "api-key-dev",
        "clientRefCode": "order-1001",
        "successUrl": "https://merchant.example.test/success",
        "failUrl": "https://merchant.example.test/fail",
        "amount": "100.00",
        "installmentNo": "1",
        "cardHolderName": "PAYNKOLAY TEST",
        "month": "12",
        "year": "2030",
        "cvv": "123",
        "cardNumber": "4111111111111111",
        "use3D": "true",
        "transactionType": "SALES",
        "cardHolderIP": "185.125.190.58",
        "rnd": "03-07-2026 09:45:00",
        "hashDatav2": expected_hash,
        "environment": "API",
        "currencyNumber": "949",
        "MerchantCustomerNo": "",
    }


@pytest.mark.api
@pytest.mark.asyncio
async def test_payment_form_payload_includes_selected_installment_quote() -> None:
    settings = RuntimeSettings.model_validate(valid_settings_payload())
    payment_request = payment_initialize_request(
        installment_count=3,
        installment_encoded_value=SecretStr("opaque-provider-quote"),
    )

    async with PaynkolayClient(settings.current) as client:
        payload = client.payment_form_payload(
            payment_request,
            success_url="https://merchant.example.test/success",
            fail_url="https://merchant.example.test/fail",
            card_holder_ip="185.125.190.58",
            rnd="27-07-2026 10:30:00",
        )

    assert payload["installmentNo"] == "3"
    assert payload["EncodedValue"] == "opaque-provider-quote"


@pytest.mark.negative
@pytest.mark.asyncio
async def test_payment_form_payload_requires_quote_for_installments() -> None:
    settings = RuntimeSettings.model_validate(valid_settings_payload())
    payment_request = payment_initialize_request(installment_count=3)

    async with PaynkolayClient(settings.current) as client:
        with pytest.raises(ValueError, match="installment encoded value is required"):
            client.payment_form_payload(
                payment_request,
                success_url="https://merchant.example.test/success",
                fail_url="https://merchant.example.test/fail",
                card_holder_ip="185.125.190.58",
                rnd="27-07-2026 10:30:00",
            )


@pytest.mark.negative
@pytest.mark.asyncio
async def test_payment_form_payload_rejects_invalid_provider_required_fields() -> None:
    settings = RuntimeSettings.model_validate(valid_settings_payload())
    payment_request = payment_initialize_request()

    async with PaynkolayClient(settings.current) as client:
        with pytest.raises(ValueError, match="success_url must use https"):
            client.payment_form_payload(
                payment_request,
                success_url="http://merchant.example.test/success",
                fail_url="https://merchant.example.test/fail",
                card_holder_ip="185.125.190.58",
                rnd="03-07-2026 09:45:00",
            )

        with pytest.raises(ValueError, match="card_holder_ip must not be empty"):
            client.payment_form_payload(
                payment_request,
                success_url="https://merchant.example.test/success",
                fail_url="https://merchant.example.test/fail",
                card_holder_ip=" ",
                rnd="03-07-2026 09:45:00",
            )


@pytest.mark.api
@pytest.mark.asyncio
async def test_initialize_payment_form_posts_paynkolay_payment_request() -> None:
    settings = RuntimeSettings.model_validate(valid_settings_payload())
    captured_request: httpx.Request | None = None

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal captured_request
        captured_request = request
        return httpx.Response(
            status_code=200,
            json={"BANK_REQUEST_MESSAGE": "<form>3DS challenge</form>"},
        )

    payment_request = payment_initialize_request()
    async with PaynkolayClient(
        settings.current,
        transport=httpx.MockTransport(handler),
    ) as client:
        response = await client.initialize_payment_form(
            payment_request,
            success_url="https://merchant.example.test/success",
            fail_url="https://merchant.example.test/fail",
            card_holder_ip="185.125.190.58",
            rnd="03-07-2026 09:45:00",
        )

    assert response == {"BANK_REQUEST_MESSAGE": "<form>3DS challenge</form>"}
    assert captured_request is not None
    assert captured_request.method == "POST"
    assert captured_request.url.path == "/v1/Payment"
    assert captured_request.headers["content-type"].startswith("multipart/form-data")
    assert b'name="hashDatav2"' in captured_request.content
    assert b'name="cardNumber"' in captured_request.content


@pytest.mark.api
@pytest.mark.asyncio
async def test_payment_list_form_payload_builds_paynkolay_status_query_fields() -> None:
    settings = RuntimeSettings.model_validate(valid_settings_payload())

    async with PaynkolayClient(settings.current) as client:
        payload = client.payment_list_form_payload(
            start_date="01.07.2026",
            end_date="31.07.2026",
            client_ref_code="order-1001",
        )

    expected_hash = generate_payment_list_hash(
        sx=SecretStr("list-api-key-dev"),
        start_date="01.07.2026",
        end_date="31.07.2026",
        client_ref_code="order-1001",
        merchant_secret_key=settings.current.merchant.secret_key,
    )
    assert payload == {
        "sx": "list-api-key-dev",
        "startDate": "01.07.2026",
        "endDate": "31.07.2026",
        "clientRefCode": "order-1001",
        "hashDatav2": expected_hash,
    }


@pytest.mark.api
@pytest.mark.asyncio
async def test_get_transaction_status_from_payment_list_posts_query_and_maps_row() -> None:
    settings = RuntimeSettings.model_validate(valid_settings_payload())
    captured_request: httpx.Request | None = None

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal captured_request
        captured_request = request
        return httpx.Response(
            status_code=200,
            json={
                "id": "",
                "result": {
                    "RESPONSE_CODE": "2",
                    "RESPONSE_DATA": "Islem basarili",
                    "LIST": [
                        {
                            "REFERENCE_CODE": "IKSIRPF102168",
                            "AUTH_CODE": "S00586",
                            "AUTHORIZATION_AMOUNT": "1.00",
                            "TRANSACTION_AMOUNT": "1.00",
                            "CLIENT_REFERENCE_CODE": "order-1001",
                            "STATUS": "SUCCESS",
                            "TRANSACTION_TYPE": "SALES",
                            "TRX_DATE": "03.07.2026 09:45:00",
                            "CARD_HOLDER_NAME": "PAYNKOLAY TEST",
                            "IS_3D": True,
                            "INSTALLMENT_COUNT": "1",
                            "DESCRIPTION": "",
                        }
                    ],
                },
            },
        )

    async with PaynkolayClient(
        settings.current,
        transport=httpx.MockTransport(handler),
    ) as client:
        response = await client.get_transaction_status_from_payment_list(
            " order-1001 ",
            start_date="01.07.2026",
            end_date="31.07.2026",
        )

    assert response.status is PaymentStatus.CAPTURED
    assert response.order_id == "order-1001"
    assert response.provider_transaction_id == "IKSIRPF102168"
    assert response.authorization_code == "S00586"
    assert captured_request is not None
    assert captured_request.url.path == "/Payment/PaymentList"
    assert captured_request.headers["content-type"].startswith("multipart/form-data")
    assert b'name="clientRefCode"' in captured_request.content
    assert b"order-1001" in captured_request.content
    assert b'name="hashDatav2"' in captured_request.content


@pytest.mark.negative
@pytest.mark.asyncio
async def test_get_transaction_status_from_payment_list_rejects_missing_provider_row() -> None:
    settings = RuntimeSettings.model_validate(valid_settings_payload())

    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            status_code=200,
            json={
                "id": "",
                "result": {
                    "RESPONSE_CODE": "2",
                    "LIST": [],
                },
            },
        )

    async with PaynkolayClient(
        settings.current,
        transport=httpx.MockTransport(handler),
    ) as client:
        with pytest.raises(
            LookupError,
            match="clientRefCode='order-1001'",
        ):
            await client.get_transaction_status_from_payment_list(
                "order-1001",
                start_date="01.07.2026",
                end_date="31.07.2026",
            )


@pytest.mark.api
@pytest.mark.asyncio
async def test_get_transaction_status_from_payment_list_accepts_flat_live_response() -> None:
    settings = RuntimeSettings.model_validate(valid_settings_payload())

    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            status_code=200,
            json={
                "RESPONSE_CODE": "2",
                "RESPONSE_DATA": "Islem basarili",
                "LIST": [
                    {
                        "REFERENCE_CODE": "IKSIRPF102168",
                        "AUTH_CODE": "S00586",
                        "AUTHORIZATION_AMOUNT": "1.00",
                        "TRANSACTION_AMOUNT": "1.00",
                        "CLIENT_REFERENCE_CODE": "order-1001",
                        "STATUS": "SUCCESS",
                        "TRANSACTION_TYPE": "SALES",
                        "TRX_DATE": "24.07.2026 09:45:00",
                        "IS_3D": True,
                        "INSTALLMENT_COUNT": "1",
                    }
                ],
                "TimeStamp": None,
            },
        )

    async with PaynkolayClient(
        settings.current,
        transport=httpx.MockTransport(handler),
    ) as client:
        response = await client.get_transaction_status_from_payment_list(
            "order-1001",
            start_date="23.07.2026",
            end_date="25.07.2026",
        )

    assert response.status is PaymentStatus.CAPTURED
    assert response.order_id == "order-1001"
    assert response.provider_transaction_id == "IKSIRPF102168"


@pytest.mark.negative
@pytest.mark.asyncio
async def test_get_transaction_status_from_payment_list_rejects_service_failure() -> None:
    settings = RuntimeSettings.model_validate(valid_settings_payload())

    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            status_code=200,
            json={
                "id": "",
                "result": {
                    "RESPONSE_CODE": "99",
                    "RESPONSE_DATA": "Service unavailable",
                    "LIST": [],
                },
            },
        )

    async with PaynkolayClient(
        settings.current,
        transport=httpx.MockTransport(handler),
    ) as client:
        with pytest.raises(
            RuntimeError,
            match=(
                "Paynkolay PaymentList service failed: "
                "response_code='99', response_data='Service unavailable'"
            ),
        ):
            await client.get_transaction_status_from_payment_list(
                "order-1001",
                start_date="01.07.2026",
                end_date="31.07.2026",
            )


@pytest.mark.api
@pytest.mark.asyncio
async def test_cancel_refund_form_payload_builds_paynkolay_operation_fields() -> None:
    settings = RuntimeSettings.model_validate(valid_settings_payload())

    async with PaynkolayClient(settings.current) as client:
        payload = client.cancel_refund_form_payload(
            reference_code=" IKSIRPF102168 ",
            transaction_type="refund",
            amount=Decimal("100"),
            trx_date="2026.07.03",
            sx=SecretStr("cancel-refund-sx"),
        )

    expected_hash = generate_cancel_refund_hash(
        sx=SecretStr("cancel-refund-sx"),
        reference_code="IKSIRPF102168",
        transaction_type="refund",
        amount=Decimal("100"),
        trx_date="2026.07.03",
        merchant_secret_key=settings.current.merchant.secret_key,
    )
    assert payload == {
        "sx": "cancel-refund-sx",
        "referenceCode": "IKSIRPF102168",
        "type": "refund",
        "amount": "100.00",
        "trxDate": "2026.07.03",
        "hashDatav2": expected_hash,
    }


@pytest.mark.api
@pytest.mark.asyncio
async def test_cancel_refund_form_payload_uses_configured_operation_sx() -> None:
    payload = valid_settings_payload()
    environments = payload["environments"]
    assert isinstance(environments, dict)
    dev = environments["dev"]
    assert isinstance(dev, dict)
    merchant = dev["merchant"]
    assert isinstance(merchant, dict)
    merchant["cancel_refund_api_key"] = "configured-cancel-refund-sx"
    settings = RuntimeSettings.model_validate(payload)

    async with PaynkolayClient(settings.current) as client:
        form_payload = client.cancel_refund_form_payload(
            reference_code="IKSIRPF102168",
            transaction_type="cancel",
            amount="100.00",
            trx_date="2026.07.03",
        )

    expected_hash = generate_cancel_refund_hash(
        sx=SecretStr("configured-cancel-refund-sx"),
        reference_code="IKSIRPF102168",
        transaction_type="cancel",
        amount="100.00",
        trx_date="2026.07.03",
        merchant_secret_key=settings.current.merchant.secret_key,
    )
    assert form_payload["sx"] == "configured-cancel-refund-sx"
    assert form_payload["hashDatav2"] == expected_hash


@pytest.mark.negative
@pytest.mark.asyncio
async def test_cancel_refund_form_payload_rejects_invalid_required_fields() -> None:
    settings = RuntimeSettings.model_validate(valid_settings_payload())

    async with PaynkolayClient(settings.current) as client:
        with pytest.raises(ValueError, match="reference_code must not be empty"):
            client.cancel_refund_form_payload(
                reference_code=" ",
                transaction_type="cancel",
                amount="100.00",
                trx_date="2026.07.03",
            )

        with pytest.raises(ValueError, match="'void' is not a valid"):
            client.cancel_refund_form_payload(
                reference_code="IKSIRPF102168",
                transaction_type="void",
                amount="100.00",
                trx_date="2026.07.03",
            )


@pytest.mark.api
@pytest.mark.asyncio
async def test_cancel_payment_posts_paynkolay_cancel_request_and_maps_response() -> None:
    settings = RuntimeSettings.model_validate(valid_settings_payload())
    captured_request: httpx.Request | None = None

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal captured_request
        captured_request = request
        return httpx.Response(
            status_code=200,
            json={"responseCode": 2, "responseData": "Islem basarili"},
        )

    async with PaynkolayClient(
        settings.current,
        transport=httpx.MockTransport(handler),
    ) as client:
        response = await client.cancel_payment(
            reference_code="IKSIRPF102168",
            amount="100.00",
            trx_date="2026.07.03",
            sx=SecretStr("cancel-refund-sx"),
        )

    assert response.status is PaymentStatus.CANCELLED
    assert response.successful is True
    assert captured_request is not None
    assert captured_request.url.path == "/v1/CancelRefundPayment"
    assert captured_request.headers["content-type"].startswith("multipart/form-data")
    assert b'name="referenceCode"' in captured_request.content
    assert b"IKSIRPF102168" in captured_request.content
    assert b'name="type"' in captured_request.content
    assert b"cancel" in captured_request.content
    assert b'name="hashDatav2"' in captured_request.content


@pytest.mark.api
@pytest.mark.asyncio
async def test_refund_payment_maps_failed_provider_response() -> None:
    settings = RuntimeSettings.model_validate(valid_settings_payload())

    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            status_code=200,
            json={"RESPONSE_CODE": "99", "RESPONSE_DATA": "Islem basarisiz"},
        )

    async with PaynkolayClient(
        settings.current,
        transport=httpx.MockTransport(handler),
    ) as client:
        response = await client.refund_payment(
            reference_code="IKSIRPF102168",
            amount="100.00",
            trx_date="2026.07.03",
        )

    assert response.status is PaymentStatus.FAILED
    assert response.successful is False


@pytest.mark.api
@pytest.mark.asyncio
async def test_get_transaction_status_fetches_encoded_order_and_parses_response() -> None:
    settings = RuntimeSettings.model_validate(valid_settings_payload())
    captured_request: httpx.Request | None = None

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal captured_request
        captured_request = request
        return httpx.Response(
            status_code=200,
            json={
                "order_id": "order 1001",
                "provider_transaction_id": "txn-1001",
                "status": "captured",
                "amount": "100.00",
                "currency": "TRY",
                "updated_at": "2026-07-02T12:00:00+03:00",
                "authorization_code": "auth-1001",
            },
        )

    async with PaynkolayClient(
        settings.current,
        transport=httpx.MockTransport(handler),
    ) as client:
        response = await client.get_transaction_status(" order 1001 ")

    assert response.status is PaymentStatus.CAPTURED
    assert response.authorization_code == "auth-1001"
    assert captured_request is not None
    assert str(captured_request.url) == "https://dev-pos.example.test/payments/order%201001/status"


@pytest.mark.negative
@pytest.mark.asyncio
async def test_get_transaction_status_rejects_blank_order_id() -> None:
    settings = RuntimeSettings.model_validate(valid_settings_payload())

    async with PaynkolayClient(settings.current) as client:
        with pytest.raises(ValueError, match="order_id must not be empty"):
            await client.get_transaction_status("   ")
