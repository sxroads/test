from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import httpx
import pytest

from paynkolay_pos.api.session_models import PaymentSession, PaymentSessionStatus
from paynkolay_pos.models import Currency
from paynkolay_pos.reporting import (
    DisabledExternalPaymentLogger,
    HttpExternalPaymentLogger,
    PaymentLogEvent,
    PaymentLogEventType,
    external_logger_from_env,
)


def payment_session() -> PaymentSession:
    return PaymentSession(
        order_id="order-1001",
        status=PaymentSessionStatus.PENDING_3DS,
        amount=Decimal("100.00"),
        currency=Currency.TRY,
        masked_pan="411111******1111",
        card_holder="TEST-AUTOMATION",
        requires_3ds=True,
        installment_count=1,
        created_at=datetime(2026, 7, 7, 12, 0, tzinfo=UTC),
        updated_at=datetime(2026, 7, 7, 12, 1, tzinfo=UTC),
    )


@pytest.mark.api
def test_payment_log_event_from_session_sanitizes_metadata() -> None:
    event = PaymentLogEvent.from_session(
        event=PaymentLogEventType.THREE_DS_REQUIRED,
        session=payment_session(),
        metadata={
            "card_number": "4111111111111111",
            "cvv": "123",
            "otp": "456789",
            "hashDataV2": "secret-hash",
            "raw_3ds_html": "<form>bank</form>",
        },
    )

    payload = event.model_dump(mode="json")
    assert payload["masked_pan"] == "411111******1111"
    assert "4111111111111111" not in str(payload)
    assert "123" not in str(payload)
    assert "456789" not in str(payload)
    assert "secret-hash" not in str(payload)
    assert payload["metadata"]["card_number"] == "************1111"
    assert payload["metadata"]["cvv"] == "<redacted>"
    assert payload["metadata"]["otp"] == "<redacted>"
    assert payload["metadata"]["hashDataV2"] == "<redacted>"


@pytest.mark.api
@pytest.mark.asyncio
async def test_http_external_payment_logger_posts_sanitized_event() -> None:
    requests: list[httpx.Request] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(status_code=204)

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    logger = HttpExternalPaymentLogger(
        endpoint_url="https://logs.example.test/events",
        client=client,
    )
    event = PaymentLogEvent.from_session(
        event=PaymentLogEventType.PAYMENT_INITIALIZED,
        session=payment_session(),
    )

    await logger.log(event)

    assert len(requests) == 1
    assert requests[0].url == "https://logs.example.test/events"
    assert b"4111111111111111" not in requests[0].content
    await client.aclose()


@pytest.mark.api
def test_external_logger_from_env_returns_disabled_logger_when_unconfigured(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("PAYNKOLAY_EXTERNAL_LOG_URL", raising=False)

    logger = external_logger_from_env()

    assert isinstance(logger, DisabledExternalPaymentLogger)

