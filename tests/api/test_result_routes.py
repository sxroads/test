from __future__ import annotations

from collections.abc import AsyncIterator
from decimal import Decimal

import httpx
import pytest
import pytest_asyncio
from pydantic import SecretStr

from paynkolay_pos.api.app import create_app
from paynkolay_pos.api.dependencies import get_external_payment_logger, get_merchant_secret_key
from paynkolay_pos.api.session_models import PaymentSessionStatus
from paynkolay_pos.api.session_store import PaymentSessionStore
from paynkolay_pos.models import Currency
from paynkolay_pos.reporting import PaymentLogEvent
from paynkolay_pos.security import generate_payment_response_hash

MERCHANT_SECRET = "merchant-secret"


@pytest_asyncio.fixture
async def app_client() -> AsyncIterator[
    tuple[httpx.AsyncClient, PaymentSessionStore, FakeExternalPaymentLogger]
]:
    app = create_app()
    fake_logger = FakeExternalPaymentLogger()
    app.dependency_overrides[get_merchant_secret_key] = lambda: SecretStr(MERCHANT_SECRET)
    app.dependency_overrides[get_external_payment_logger] = lambda: fake_logger
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        yield client, app.state.payment_session_store, fake_logger


class FakeExternalPaymentLogger:
    def __init__(self) -> None:
        self.events: list[PaymentLogEvent] = []

    async def log(self, event: PaymentLogEvent) -> None:
        self.events.append(event)


@pytest.mark.api
@pytest.mark.asyncio
async def test_success_result_route_verifies_hash_and_completes_session(
    app_client: tuple[httpx.AsyncClient, PaymentSessionStore, FakeExternalPaymentLogger],
) -> None:
    client, session_store, fake_logger = app_client
    await _seed_session(session_store, order_id="order-success")
    payload = _result_payload(client_ref_code="order-success")

    response = await client.get("/payments/result/success", params=payload)

    assert response.status_code == 200
    assert "Payment approved" in response.text
    assert "4111111111111111" not in response.text
    session = await session_store.get("order-success")
    assert session.status is PaymentSessionStatus.COMPLETED
    assert session.provider_transaction_id == "IKSIRPF102168"
    assert session.failure_reason is None
    assert [event.event for event in fake_logger.events] == ["payment_success_returned"]
    assert "4111111111111111" not in str([event.model_dump() for event in fake_logger.events])


@pytest.mark.api
@pytest.mark.asyncio
async def test_fail_result_route_verifies_hash_and_fails_session(
    app_client: tuple[httpx.AsyncClient, PaymentSessionStore, FakeExternalPaymentLogger],
) -> None:
    client, session_store, fake_logger = app_client
    await _seed_session(session_store, order_id="order-fail")
    payload = _result_payload(
        client_ref_code="order-fail",
        response_code="99",
        response_data="Issuer declined",
        auth_code="",
        reference_code="IKSIRPF102169",
    )

    response = await client.post("/payments/result/fail", data=payload)

    assert response.status_code == 200
    assert "Payment failed" in response.text
    assert "Issuer declined" in response.text
    session = await session_store.get("order-fail")
    assert session.status is PaymentSessionStatus.FAILED
    assert session.provider_transaction_id == "IKSIRPF102169"
    assert session.failure_reason == "Issuer declined"
    assert [event.event for event in fake_logger.events] == ["payment_fail_returned"]


@pytest.mark.api
@pytest.mark.asyncio
async def test_result_route_rejects_invalid_hash_and_marks_session_failed(
    app_client: tuple[httpx.AsyncClient, PaymentSessionStore, FakeExternalPaymentLogger],
) -> None:
    client, session_store, fake_logger = app_client
    await _seed_session(session_store, order_id="order-bad-hash")
    payload = _result_payload(client_ref_code="order-bad-hash")
    payload["hashDataV2"] = "bad-hash"

    response = await client.get("/payments/result/success", params=payload)

    assert response.status_code == 400
    session = await session_store.get("order-bad-hash")
    assert session.status is PaymentSessionStatus.FAILED
    assert session.failure_reason == "provider result hash verification failed"
    assert fake_logger.events == []


@pytest.mark.api
@pytest.mark.asyncio
async def test_result_route_returns_404_for_unknown_session(
    app_client: tuple[httpx.AsyncClient, PaymentSessionStore, FakeExternalPaymentLogger],
) -> None:
    client, _session_store, _fake_logger = app_client
    payload = _result_payload(client_ref_code="missing-order")

    response = await client.get("/payments/result/success", params=payload)

    assert response.status_code == 404


@pytest.mark.api
@pytest.mark.asyncio
async def test_result_route_requires_runtime_config_without_override(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("PAYNKOLAY_CONFIG_FILE", raising=False)
    app = create_app()
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.get(
            "/payments/result/success",
            params=_result_payload(client_ref_code="order-success"),
        )

    assert response.status_code == 503


async def _seed_session(
    session_store: PaymentSessionStore,
    *,
    order_id: str,
) -> None:
    await session_store.create(
        order_id=order_id,
        amount=Decimal("1.00"),
        currency=Currency.TRY,
        pan="4111111111111111",
        card_holder="TEST-AUTOMATION",
        requires_3ds=True,
        installment_count=1,
    )
    await session_store.update_status(order_id, PaymentSessionStatus.THREE_DS_RENDERED)


def _result_payload(
    *,
    client_ref_code: str,
    response_code: str = "2",
    response_data: str = "Islem Basarili",
    auth_code: str = "S00586",
    reference_code: str = "IKSIRPF102168",
) -> dict[str, str]:
    payload = {
        "RESPONSE_CODE": response_code,
        "RESPONSE_DATA": response_data,
        "USE_3D": "true",
        "RND": "1630051651137",
        "MERCHANT_NO": "400000001",
        "AUTH_CODE": auth_code,
        "REFERENCE_CODE": reference_code,
        "CLIENT_REFERENCE_CODE": client_ref_code,
        "TIMESTAMP": "2026-07-03 09:45:00.000",
        "TRANSACTION_AMOUNT": "1.00",
        "AUTHORIZATION_AMOUNT": "1.00",
        "COMMISION": "0.00",
        "COMMISION_RATE": "0.0000",
        "INSTALLMENT": "1",
        "CURRENCY_CODE": "TRY",
        "hashData": "legacy-hash",
    }
    payload["hashDataV2"] = generate_payment_response_hash(
        merchant_no=payload["MERCHANT_NO"],
        reference_code=payload["REFERENCE_CODE"],
        auth_code=payload["AUTH_CODE"],
        response_code=payload["RESPONSE_CODE"],
        use_3d=payload["USE_3D"],
        rnd=payload["RND"],
        installment=payload["INSTALLMENT"],
        authorization_amount=payload["AUTHORIZATION_AMOUNT"],
        currency_code=payload["CURRENCY_CODE"],
        merchant_secret_key=MERCHANT_SECRET,
    )
    return payload
