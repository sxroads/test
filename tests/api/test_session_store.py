from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from paynkolay_pos.api.session_models import PaymentSessionStatus, mask_pan
from paynkolay_pos.api.session_store import (
    PaymentSessionAlreadyExistsError,
    PaymentSessionNotFoundError,
    PaymentSessionStore,
)
from paynkolay_pos.models import Currency


class FixedClock:
    def __init__(self) -> None:
        self._current = datetime(2026, 7, 7, 12, 0, tzinfo=UTC)

    def __call__(self) -> datetime:
        current = self._current
        self._current += timedelta(seconds=1)
        return current


@pytest.mark.api
def test_mask_pan_returns_safe_display_value() -> None:
    cases = (
        ("4111111111111111", "411111******1111"),
        ("123456789012", "123456**9012"),
        ("1234567890123456789", "123456*********6789"),
    )
    for pan, masked in cases:
        assert mask_pan(pan) == masked


@pytest.mark.api
def test_mask_pan_rejects_invalid_values() -> None:
    for pan in ("41111111111x1111", "123", "12345678901234567890"):
        with pytest.raises(ValueError):
            mask_pan(pan)


@pytest.mark.api
@pytest.mark.asyncio
async def test_session_store_creates_sanitized_session() -> None:
    store = PaymentSessionStore(clock=FixedClock())

    session = await store.create(
        order_id="order-1001",
        amount=Decimal("100.00"),
        currency=Currency.TRY,
        pan="4111111111111111",
        card_holder="TEST-AUTOMATION",
        requires_3ds=True,
        installment_count=1,
    )

    assert session.order_id == "order-1001"
    assert session.status is PaymentSessionStatus.CREATED
    assert session.canonical_amount == "100.00"
    assert session.masked_pan == "411111******1111"
    assert "4111111111111111" not in session.model_dump_json()


@pytest.mark.api
@pytest.mark.asyncio
async def test_session_store_rejects_duplicate_order_id() -> None:
    store = PaymentSessionStore(clock=FixedClock())

    async def create_session() -> None:
        await store.create(
            order_id="order-duplicate",
            amount=Decimal("100.00"),
            currency=Currency.TRY,
            pan="4111111111111111",
            card_holder="TEST-AUTOMATION",
            requires_3ds=True,
            installment_count=1,
        )

    await create_session()
    with pytest.raises(PaymentSessionAlreadyExistsError):
        await create_session()


@pytest.mark.api
@pytest.mark.asyncio
async def test_session_store_updates_status() -> None:
    store = PaymentSessionStore(clock=FixedClock())
    await store.create(
        order_id="order-1001",
        amount=Decimal("100.00"),
        currency=Currency.TRY,
        pan="4111111111111111",
        card_holder="TEST-AUTOMATION",
        requires_3ds=True,
        installment_count=1,
    )

    updated = await store.update_status(
        "order-1001",
        PaymentSessionStatus.PENDING_3DS,
        provider_transaction_id="txn-1001",
    )

    assert updated.status is PaymentSessionStatus.PENDING_3DS
    assert updated.provider_transaction_id == "txn-1001"
    assert updated.updated_at > updated.created_at


@pytest.mark.api
@pytest.mark.asyncio
async def test_session_store_raises_for_unknown_session() -> None:
    store = PaymentSessionStore(clock=FixedClock())

    with pytest.raises(PaymentSessionNotFoundError):
        await store.get("missing-order")
