"""Payment form routes for the browser UI."""

from __future__ import annotations

from typing import Annotated
from uuid import uuid4

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request, status
from pydantic import SecretStr

from paynkolay_pos.api.dependencies import (
    SupportsThreeDSAutomator,
    get_external_payment_logger,
    get_payment_initializer,
    get_payment_session_store,
    get_three_ds_automator,
    get_three_ds_form_store,
)
from paynkolay_pos.api.payment_initializer import (
    PaymentInitializationOutcome,
    PaymentProviderInitializationError,
    PaymentProviderStatusVerificationError,
    SupportsPaymentInitializer,
)
from paynkolay_pos.api.payment_list_retry import verify_transaction_status_with_retry
from paynkolay_pos.api.schemas import (
    PaymentFormRequest,
    PaymentFormResponse,
    PaymentLookupResponse,
)
from paynkolay_pos.api.session_models import (
    PaymentSession,
    PaymentSessionStatus,
    ProviderRequestSummary,
    ThreeDSAutomationSummary,
    mask_pan,
)
from paynkolay_pos.api.session_store import (
    PaymentSessionAlreadyExistsError,
    PaymentSessionNotFoundError,
    PaymentSessionStore,
)
from paynkolay_pos.api.three_ds_store import ThreeDSFormStore
from paynkolay_pos.config import load_runtime_settings
from paynkolay_pos.models import (
    PaymentStatus,
    PaynkolayPaymentResult,
    PaynkolayThreeDSInitializeResult,
)
from paynkolay_pos.reporting import (
    PaymentLogEvent,
    PaymentLogEventType,
    SupportsExternalPaymentLogger,
)

router = APIRouter(prefix="/api/payments", tags=["payments"])
FINAL_PAYMENT_LIST_STATUSES = {
    PaymentStatus.AUTHENTICATED,
    PaymentStatus.AUTHORIZED,
    PaymentStatus.CAPTURED,
    PaymentStatus.FAILED,
}
PaymentSessionStoreDependency = Annotated[
    PaymentSessionStore,
    Depends(get_payment_session_store),
]
PaymentInitializerDependency = Annotated[
    SupportsPaymentInitializer,
    Depends(get_payment_initializer),
]
ThreeDSFormStoreDependency = Annotated[
    ThreeDSFormStore,
    Depends(get_three_ds_form_store),
]
ThreeDSAutomatorDependency = Annotated[
    SupportsThreeDSAutomator,
    Depends(get_three_ds_automator),
]
ExternalLoggerDependency = Annotated[
    SupportsExternalPaymentLogger,
    Depends(get_external_payment_logger),
]


@router.post("", response_model=PaymentFormResponse, status_code=status.HTTP_202_ACCEPTED)
async def create_payment(
    request: PaymentFormRequest,
    http_request: Request,
    background_tasks: BackgroundTasks,
    session_store: PaymentSessionStoreDependency,
    three_ds_form_store: ThreeDSFormStoreDependency,
    initializer: PaymentInitializerDependency,
    automator: ThreeDSAutomatorDependency,
    external_logger: ExternalLoggerDependency,
) -> PaymentFormResponse:
    """Accept and validate a browser payment form payload.

    Provider execution is intentionally left for the next implementation phases; this route
    creates sanitized session state for the browser workflow.
    """

    order_id = request.order_id or f"web-{uuid4().hex[:12]}"
    try:
        session = await session_store.create(
            order_id=order_id,
            amount=request.amount,
            currency=request.currency,
            pan=request.card_number.get_secret_value(),
            card_holder=request.card_holder,
            requires_3ds=request.requires_3ds,
            installment_count=request.installment_count,
        )
    except PaymentSessionAlreadyExistsError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        ) from exc

    try:
        outcome = await initializer.initialize(
            request,
            order_id=order_id,
            card_holder_ip=_client_host(http_request),
        )
    except PaymentProviderInitializationError as exc:
        session = await session_store.update_status(
            order_id,
            PaymentSessionStatus.FAILED,
            failure_reason="provider payment initialization failed",
        )
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=session.failure_reason,
        ) from exc

    provider_result = outcome.provider_result
    provider_request = _provider_request_summary(outcome)
    if isinstance(provider_result, PaynkolayThreeDSInitializeResult):
        await three_ds_form_store.put(
            order_id,
            provider_result.bank_request_message,
        )
        session = await session_store.update_status(
            order_id,
            PaymentSessionStatus.PENDING_3DS,
            provider_request=provider_request,
        )
        await _log_payment_event(
            external_logger,
            PaymentLogEventType.PAYMENT_INITIALIZED,
            session,
            metadata={"provider_result": "three_ds"},
        )
        await _log_payment_event(
            external_logger,
            PaymentLogEventType.THREE_DS_REQUIRED,
            session,
            metadata={"render_url": f"/payments/{order_id}/three-ds"},
        )
        message = "Payment initialized; 3D Secure authentication is required."
        if request.auto_complete_3ds:
            background_tasks.add_task(
                _auto_complete_three_ds_session,
                order_id=order_id,
                html=provider_result.bank_request_message,
                request=request,
                callback_url=outcome.success_url,
                session_store=session_store,
                initializer=initializer,
                automator=automator,
            )
            message = "Payment initialized; 3D Secure automation has started."
        three_ds = {"render_url": f"/payments/{order_id}/three-ds"}
        return PaymentFormResponse.from_session(
            session,
            message=message,
            three_ds=three_ds,
        )

    if isinstance(provider_result, PaynkolayPaymentResult):
        session_status = (
            PaymentSessionStatus.COMPLETED
            if provider_result.successful
            else PaymentSessionStatus.FAILED
        )
        session = await session_store.update_status(
            order_id,
            session_status,
            provider_request=provider_request,
            provider_transaction_id=provider_result.reference_code,
            provider_response_code=provider_result.response_code,
            provider_response_data=provider_result.response_data,
            failure_reason=(
                provider_result.response_data
                if session_status is PaymentSessionStatus.FAILED
                else None
            ),
        )
        session = await _verify_payment_list_status(
            order_id=order_id,
            request=request,
            session=session,
            session_store=session_store,
            initializer=initializer,
        )
        await _log_payment_event(
            external_logger,
            PaymentLogEventType.PAYMENT_INITIALIZED,
            session,
            metadata={"provider_result": "final"},
        )
        return PaymentFormResponse.from_session(
            session,
            message=_final_result_message(
                provider_result=provider_result,
                provider_request=provider_request,
            ),
        )

    raise TypeError(f"unsupported provider result type: {type(provider_result).__name__}")


def _provider_request_summary(outcome: PaymentInitializationOutcome) -> ProviderRequestSummary:
    payment_request = outcome.payment_request
    return ProviderRequestSummary(
        client_ref_code=payment_request.order_id,
        amount=payment_request.canonical_amount,
        currency=payment_request.currency,
        use_3d=payment_request.requires_3ds,
        installment_no=payment_request.installment_count,
        card_brand=payment_request.card.brand.value,
        masked_pan=mask_pan(payment_request.card.pan.get_secret_value()),
        expiry_month=payment_request.card.expiry_month,
        expiry_year=payment_request.card.expiry_year,
        transaction_type="SALES",
        payment_channel=payment_request.payment_channel.value,
        success_url=outcome.success_url,
        fail_url=outcome.fail_url,
    )


def _final_result_message(
    *,
    provider_result: PaynkolayPaymentResult,
    provider_request: ProviderRequestSummary,
) -> str:
    response_data = provider_result.response_data or "-"
    return (
        "Payment provider returned a final payment result. "
        f"Provider code={provider_result.response_code}; "
        f"provider message={response_data}; "
        f"request={provider_request.card_brand.upper()} {provider_request.masked_pan} "
        f"use3D={provider_request.use_3d} amount={provider_request.amount} "
        f"{provider_request.currency.value}."
    )


@router.get("/{order_id}", response_model=PaymentLookupResponse)
async def get_payment(
    order_id: str,
    session_store: PaymentSessionStoreDependency,
) -> PaymentLookupResponse:
    """Return sanitized session state for an order ID."""

    try:
        session = await session_store.get(order_id)
    except PaymentSessionNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc
    return PaymentLookupResponse.from_session(session)


def _client_host(request: Request) -> str:
    if request.client is None or not request.client.host.strip():
        return "127.0.0.1"
    return request.client.host


async def _verify_payment_list_status(
    *,
    order_id: str,
    request: PaymentFormRequest,
    session: PaymentSession,
    session_store: PaymentSessionStore,
    initializer: SupportsPaymentInitializer,
    accepted_statuses: set[PaymentStatus] | None = None,
) -> PaymentSession:
    try:
        payment_list_status = await verify_transaction_status_with_retry(
            initializer,
            order_id,
            currency=request.currency,
            accepted_statuses=accepted_statuses,
        )
    except PaymentProviderStatusVerificationError as exc:
        return await session_store.update_payment_list_error(order_id, str(exc))
    return await session_store.update_payment_list_status(order_id, payment_list_status)


async def _auto_complete_three_ds_session(
    *,
    order_id: str,
    html: str,
    request: PaymentFormRequest,
    callback_url: str,
    session_store: PaymentSessionStore,
    initializer: SupportsPaymentInitializer,
    automator: SupportsThreeDSAutomator,
) -> None:
    await session_store.update_three_ds_automation(
        order_id,
        ThreeDSAutomationSummary(status="running", reason="3DS automation started"),
    )
    configured_otp = _configured_otp_for_request(request)
    result = await automator.complete(
        html=html,
        brand=request.card_brand,
        configured_otp=configured_otp,
        callback_url=callback_url,
    )
    await session_store.update_three_ds_automation(
        order_id,
        ThreeDSAutomationSummary.model_validate(result.summary()),
    )
    if not result.completed or not result.submitted:
        return

    session = await _verify_payment_list_status(
        order_id=order_id,
        request=request,
        session=await session_store.get(order_id),
        session_store=session_store,
        initializer=initializer,
        accepted_statuses=FINAL_PAYMENT_LIST_STATUSES,
    )
    if session.payment_list_status in {
        PaymentStatus.AUTHENTICATED,
        PaymentStatus.AUTHORIZED,
        PaymentStatus.CAPTURED,
    }:
        await session_store.update_status(order_id, PaymentSessionStatus.COMPLETED)
    elif session.payment_list_status is PaymentStatus.FAILED:
        await session_store.update_status(
            order_id,
            PaymentSessionStatus.FAILED,
            failure_reason="3DS automation completed but PaymentList returned failed",
        )
    elif session.payment_list_status is not None:
        await session_store.update_status(order_id, PaymentSessionStatus.STATUS_VERIFIED)
    elif session.payment_list_error is not None and result.returned_to_callback:
        await session_store.update_status(
            order_id,
            PaymentSessionStatus.SUCCESS_RETURNED,
        )


def _configured_otp_for_request(request: PaymentFormRequest) -> SecretStr | None:
    pan = request.card_number.get_secret_value()
    try:
        cards = load_runtime_settings().current.cards
    except (FileNotFoundError, RuntimeError, ValueError):
        return None
    for card in cards:
        if card.pan.get_secret_value() == pan:
            return card.expected_otp
    return None


async def _log_payment_event(
    external_logger: SupportsExternalPaymentLogger,
    event_type: PaymentLogEventType,
    session: PaymentSession,
    *,
    metadata: dict[str, object] | None = None,
) -> None:
    try:
        event = PaymentLogEvent.from_session(
            event=event_type,
            session=session,
            metadata=metadata,
        )
        await external_logger.log(event)
    except Exception:
        return
