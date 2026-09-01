from __future__ import annotations

import base64
from collections.abc import AsyncIterator
from decimal import Decimal
from typing import cast

import httpx
import pytest
import pytest_asyncio

from paynkolay_pos.api.app import create_app
from paynkolay_pos.api.session_models import PaymentSessionStatus
from paynkolay_pos.api.session_store import PaymentSessionStore
from paynkolay_pos.api.three_ds_store import ThreeDSFormStore
from paynkolay_pos.models import Currency


@pytest_asyncio.fixture
async def app_client() -> AsyncIterator[
    tuple[httpx.AsyncClient, PaymentSessionStore, ThreeDSFormStore]
]:
    app = create_app()
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        yield (
            client,
            cast(PaymentSessionStore, app.state.payment_session_store),
            cast(ThreeDSFormStore, app.state.three_ds_form_store),
        )


@pytest.mark.api
@pytest.mark.three_ds
@pytest.mark.asyncio
async def test_three_ds_route_renders_raw_html_and_updates_session(
    app_client: tuple[httpx.AsyncClient, PaymentSessionStore, ThreeDSFormStore],
) -> None:
    client, session_store, form_store = app_client
    await _seed_three_ds_session(
        session_store,
        form_store,
        order_id="order-three-ds",
        payload='<form action="https://acs.example.test/challenge"></form>',
    )

    response = await client.get("/payments/order-three-ds/three-ds")

    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["x-content-type-options"] == "nosniff"
    assert '<form action="https://acs.example.test/challenge"></form>' in response.text
    session = await session_store.get("order-three-ds")
    assert session.status is PaymentSessionStatus.THREE_DS_RENDERED


@pytest.mark.api
@pytest.mark.three_ds
@pytest.mark.asyncio
async def test_three_ds_route_decodes_base64_form(
    app_client: tuple[httpx.AsyncClient, PaymentSessionStore, ThreeDSFormStore],
) -> None:
    client, session_store, form_store = app_client
    encoded = base64.b64encode(b'<form action="https://acs.example.test"></form>').decode()
    await _seed_three_ds_session(
        session_store,
        form_store,
        order_id="order-base64",
        payload=encoded,
    )

    response = await client.get("/payments/order-base64/three-ds")

    assert response.status_code == 200
    assert '<form action="https://acs.example.test"></form>' in response.text


@pytest.mark.api
@pytest.mark.three_ds
@pytest.mark.asyncio
async def test_three_ds_route_returns_404_for_unknown_session(
    app_client: tuple[httpx.AsyncClient, PaymentSessionStore, ThreeDSFormStore],
) -> None:
    client, _session_store, _form_store = app_client

    response = await client.get("/payments/missing-order/three-ds")

    assert response.status_code == 404


@pytest.mark.api
@pytest.mark.three_ds
@pytest.mark.asyncio
async def test_three_ds_route_returns_409_when_session_is_not_pending(
    app_client: tuple[httpx.AsyncClient, PaymentSessionStore, ThreeDSFormStore],
) -> None:
    client, session_store, form_store = app_client
    await _seed_three_ds_session(
        session_store,
        form_store,
        order_id="order-completed",
        payload="<form></form>",
        status=PaymentSessionStatus.COMPLETED,
    )

    response = await client.get("/payments/order-completed/three-ds")

    assert response.status_code == 409


@pytest.mark.api
@pytest.mark.three_ds
@pytest.mark.asyncio
async def test_three_ds_route_returns_422_for_invalid_form_payload(
    app_client: tuple[httpx.AsyncClient, PaymentSessionStore, ThreeDSFormStore],
) -> None:
    client, session_store, form_store = app_client
    await _seed_three_ds_session(
        session_store,
        form_store,
        order_id="order-invalid",
        payload=base64.b64encode(b"not html").decode(),
    )

    response = await client.get("/payments/order-invalid/three-ds")

    assert response.status_code == 422


async def _seed_three_ds_session(
    session_store: PaymentSessionStore,
    form_store: ThreeDSFormStore,
    *,
    order_id: str,
    payload: str,
    status: PaymentSessionStatus = PaymentSessionStatus.PENDING_3DS,
) -> None:
    await session_store.create(
        order_id=order_id,
        amount=Decimal("100.00"),
        currency=Currency.TRY,
        pan="4111111111111111",
        card_holder="TEST-AUTOMATION",
        requires_3ds=True,
        installment_count=1,
    )
    await session_store.update_status(order_id, status)
    await form_store.put(order_id, payload)
