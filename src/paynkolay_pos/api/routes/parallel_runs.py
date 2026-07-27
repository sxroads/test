"""Parallel payment initialization run routes."""

from __future__ import annotations

import asyncio
import os
import random
from collections import Counter
from collections.abc import Sequence
from decimal import Decimal
from pathlib import Path
from time import perf_counter
from typing import Annotated, Literal
from uuid import uuid4

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request, status
from pydantic import SecretStr

from paynkolay_pos.api.acs_scheduler import AdaptiveAcsScheduler
from paynkolay_pos.api.dependencies import (
    SupportsThreeDSAutomator,
    get_optional_installment_provider,
    get_parallel_run_store,
    get_payment_initializer,
    get_payment_session_store,
    get_three_ds_automator,
    get_three_ds_form_store,
)
from paynkolay_pos.api.installment_provider import (
    InstallmentOptionUnavailableError,
    InstallmentProviderLookupError,
    SupportsInstallmentProvider,
    local_stub_installment_counts,
    select_installment_quote,
)
from paynkolay_pos.api.parallel_run_store import (
    ParallelRunItemState,
    ParallelRunNotFoundError,
    ParallelRunState,
    ParallelRunStore,
    utc_now,
)
from paynkolay_pos.api.payment_initializer import (
    PaymentInitializationOutcome,
    PaymentProviderInitializationError,
    PaymentProviderStatusVerificationError,
    SupportsPaymentInitializer,
)
from paynkolay_pos.api.payment_list_retry import verify_transaction_status_with_retry
from paynkolay_pos.api.routes.payments import _provider_request_summary
from paynkolay_pos.api.schemas import (
    ParallelRunCreateRequest,
    ParallelRunItemResponse,
    ParallelRunResponse,
    PaymentFormRequest,
    PaymentListStatusSummary,
)
from paynkolay_pos.api.session_models import (
    PaymentSession,
    PaymentSessionStatus,
    ProviderRequestSummary,
    ThreeDSAutomationSummary,
)
from paynkolay_pos.api.session_store import PaymentSessionStore
from paynkolay_pos.api.three_ds_store import ThreeDSFormStore
from paynkolay_pos.config import TestCard, load_runtime_settings
from paynkolay_pos.models import (
    Currency,
    PaymentStatus,
    PaynkolayPaymentResult,
    PaynkolayThreeDSInitializeResult,
)
from paynkolay_pos.reporting import evidence_json
from paynkolay_pos.testing.card_behaviors import (
    CardAutomationStatus,
    behavior_for_alias,
)

router = APIRouter(prefix="/api/parallel-runs", tags=["parallel_runs"])
FINAL_PAYMENT_LIST_STATUSES = {
    PaymentStatus.AUTHENTICATED,
    PaymentStatus.AUTHORIZED,
    PaymentStatus.CAPTURED,
    PaymentStatus.FAILED,
}
SUBMITTED_3DS_PAYMENT_LIST_RETRY_DELAYS = (2.0, 5.0, 10.0, 20.0)
INSTALLMENT_LOOKUP_CONCURRENCY = 5

PaymentInitializerDependency = Annotated[
    SupportsPaymentInitializer,
    Depends(get_payment_initializer),
]
PaymentSessionStoreDependency = Annotated[
    PaymentSessionStore,
    Depends(get_payment_session_store),
]
ThreeDSFormStoreDependency = Annotated[
    ThreeDSFormStore,
    Depends(get_three_ds_form_store),
]
ThreeDSAutomatorDependency = Annotated[
    SupportsThreeDSAutomator,
    Depends(get_three_ds_automator),
]
ParallelRunStoreDependency = Annotated[
    ParallelRunStore,
    Depends(get_parallel_run_store),
]
OptionalInstallmentProviderDependency = Annotated[
    SupportsInstallmentProvider | None,
    Depends(get_optional_installment_provider),
]


@router.post("", response_model=ParallelRunResponse, status_code=status.HTTP_202_ACCEPTED)
async def create_parallel_run(
    request: ParallelRunCreateRequest,
    http_request: Request,
    background_tasks: BackgroundTasks,
    initializer: PaymentInitializerDependency,
    session_store: PaymentSessionStoreDependency,
    three_ds_form_store: ThreeDSFormStoreDependency,
    automator: ThreeDSAutomatorDependency,
    run_store: ParallelRunStoreDependency,
    installment_provider: OptionalInstallmentProviderDependency,
) -> ParallelRunResponse:
    """Start a parallel payment initialization run from configured cards."""

    cards = _load_card_map()
    _require_uat_installment_provider(request, installment_provider)
    selected_cards = _select_cards(request, cards)
    run_id = uuid4().hex[:12]
    items = _parallel_items(
        run_id=run_id,
        selected_cards=selected_cards,
        installment_count=request.installment_count,
    )
    run = ParallelRunState(
        run_id=run_id,
        mode=request.mode,
        execution_profile=request.execution_profile,
        concurrency=request.concurrency,
        acs_concurrency=request.effective_acs_concurrency,
        installment_count=request.installment_count,
        items=items,
        status="running",
        started_at=utc_now(),
        message="Parallel run started.",
    )
    await run_store.create(run)
    background_tasks.add_task(
        _execute_parallel_run,
        run_id=run_id,
        cards_by_alias=cards,
        amount=request.amount,
        currency=request.currency,
        client_host=_client_host(http_request),
        auto_complete_3ds=request.auto_complete_3ds,
        installment_count=request.installment_count,
        installment_provider=installment_provider,
        initializer=initializer,
        automator=automator,
        session_store=session_store,
        three_ds_form_store=three_ds_form_store,
        run_store=run_store,
    )
    return run.response(include_items=True)


@router.get("/{run_id}", response_model=ParallelRunResponse)
async def get_parallel_run(
    run_id: str,
    run_store: ParallelRunStoreDependency,
) -> ParallelRunResponse:
    """Return a parallel run summary."""

    try:
        run = await run_store.get(run_id)
    except ParallelRunNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return run.response(include_items=True)


@router.get("/{run_id}/items", response_model=list[ParallelRunItemResponse])
async def get_parallel_run_items(
    run_id: str,
    run_store: ParallelRunStoreDependency,
) -> list[ParallelRunItemResponse]:
    """Return item results for a parallel run."""

    try:
        run = await run_store.get(run_id)
    except ParallelRunNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return [item.response() for item in run.items]


async def _execute_parallel_run(
    *,
    run_id: str,
    cards_by_alias: dict[str, TestCard],
    amount: Decimal,
    currency: Currency,
    client_host: str,
    auto_complete_3ds: bool,
    installment_count: int,
    installment_provider: SupportsInstallmentProvider | None,
    initializer: SupportsPaymentInitializer,
    automator: SupportsThreeDSAutomator,
    session_store: PaymentSessionStore,
    three_ds_form_store: ThreeDSFormStore,
    run_store: ParallelRunStore,
) -> None:
    run = await run_store.get(run_id)
    initialization_semaphore = asyncio.Semaphore(run.concurrency)
    installment_lookup_semaphore = asyncio.Semaphore(INSTALLMENT_LOOKUP_CONCURRENCY)
    payment_list_semaphore = asyncio.Semaphore(
        run.concurrency if run.execution_profile == "load" else min(run.concurrency, 10)
    )
    acs_scheduler = AdaptiveAcsScheduler(
        profile=run.execution_profile,
        requested_concurrency=run.acs_concurrency,
    )
    await _sync_acs_scheduler(run_store, run_id, acs_scheduler)
    serial_3ds_locks = _serial_3ds_locks_for_run(run.items, cards_by_alias)
    tasks = [
        _execute_item(
            run_id=run_id,
            item=item,
            card=cards_by_alias[item.card_alias],
            amount=amount,
            currency=currency,
            client_host=client_host,
            auto_complete_3ds=auto_complete_3ds,
            installment_count=installment_count,
            installment_provider=installment_provider,
            initializer=initializer,
            automator=automator,
            session_store=session_store,
            three_ds_form_store=three_ds_form_store,
            run_store=run_store,
            initialization_semaphore=initialization_semaphore,
            installment_lookup_semaphore=installment_lookup_semaphore,
            payment_list_semaphore=payment_list_semaphore,
            acs_scheduler=acs_scheduler,
            serial_3ds_locks=serial_3ds_locks,
        )
        for item in run.items
    ]
    task_results = await asyncio.gather(*tasks, return_exceptions=True)
    await _sync_acs_scheduler(run_store, run_id, acs_scheduler)
    await run_store.mutate(run_id, lambda run: _record_unhandled_task_errors(run, task_results))
    await run_store.mutate(run_id, _finish_run)


async def _execute_item(
    *,
    run_id: str,
    item: ParallelRunItemState,
    card: TestCard,
    amount: Decimal,
    currency: Currency,
    client_host: str,
    auto_complete_3ds: bool,
    installment_count: int,
    installment_provider: SupportsInstallmentProvider | None,
    initializer: SupportsPaymentInitializer,
    automator: SupportsThreeDSAutomator,
    session_store: PaymentSessionStore,
    three_ds_form_store: ThreeDSFormStore,
    run_store: ParallelRunStore,
    initialization_semaphore: asyncio.Semaphore,
    installment_lookup_semaphore: asyncio.Semaphore,
    payment_list_semaphore: asyncio.Semaphore,
    acs_scheduler: AdaptiveAcsScheduler,
    serial_3ds_locks: dict[str, asyncio.Lock],
) -> None:
    serial_lock = serial_3ds_locks.get(item.card_alias)
    try:
        if serial_lock is None:
            await _execute_item_attempt(
                run_id=run_id,
                item=item,
                card=card,
                amount=amount,
                currency=currency,
                client_host=client_host,
                auto_complete_3ds=auto_complete_3ds,
                installment_count=installment_count,
                installment_provider=installment_provider,
                initializer=initializer,
                automator=automator,
                session_store=session_store,
                three_ds_form_store=three_ds_form_store,
                run_store=run_store,
                initialization_semaphore=initialization_semaphore,
                installment_lookup_semaphore=installment_lookup_semaphore,
                payment_list_semaphore=payment_list_semaphore,
                acs_scheduler=acs_scheduler,
            )
        else:
            async with serial_lock:
                await _execute_item_attempt(
                    run_id=run_id,
                    item=item,
                    card=card,
                    amount=amount,
                    currency=currency,
                    client_host=client_host,
                    auto_complete_3ds=auto_complete_3ds,
                    installment_count=installment_count,
                    installment_provider=installment_provider,
                    initializer=initializer,
                    automator=automator,
                    session_store=session_store,
                    three_ds_form_store=three_ds_form_store,
                    run_store=run_store,
                    initialization_semaphore=initialization_semaphore,
                    installment_lookup_semaphore=installment_lookup_semaphore,
                    payment_list_semaphore=payment_list_semaphore,
                    acs_scheduler=acs_scheduler,
                )
    except InstallmentOptionUnavailableError as exc:
        error_message = str(exc)
        await _mark_session_failed(session_store, item.order_id, error_message)
        await run_store.mutate(
            run_id,
            lambda run: _mark_item_failed(
                run,
                item.item_id,
                classification="installment_option_unavailable",
                error_message=error_message,
            ),
        )
    except InstallmentProviderLookupError as exc:
        error_message = str(exc)
        await _mark_session_failed(session_store, item.order_id, error_message)
        await run_store.mutate(
            run_id,
            lambda run: _mark_item_failed(
                run,
                item.item_id,
                classification="installment_lookup_failed",
                error_message=error_message,
            ),
        )
    except PaymentProviderInitializationError as exc:
        classification = _classify_initialization_error(exc)
        error_message = str(exc)
        await _mark_session_failed(
            session_store,
            item.order_id,
            "provider payment initialization failed",
        )
        await run_store.mutate(
            run_id,
            lambda run: _mark_item_failed(
                run,
                item.item_id,
                classification=classification,
                error_message=error_message,
            ),
        )
    except Exception as exc:
        error_message = f"{type(exc).__name__}: {exc}"
        await _mark_session_failed(
            session_store,
            item.order_id,
            error_message,
        )
        await run_store.mutate(
            run_id,
            lambda run: _mark_item_failed(
                run,
                item.item_id,
                classification="framework_error",
                error_message=error_message,
            ),
        )


async def _execute_item_attempt(
    *,
    run_id: str,
    item: ParallelRunItemState,
    card: TestCard,
    amount: Decimal,
    currency: Currency,
    client_host: str,
    auto_complete_3ds: bool,
    installment_count: int,
    installment_provider: SupportsInstallmentProvider | None,
    initializer: SupportsPaymentInitializer,
    automator: SupportsThreeDSAutomator,
    session_store: PaymentSessionStore,
    three_ds_form_store: ThreeDSFormStore,
    run_store: ParallelRunStore,
    initialization_semaphore: asyncio.Semaphore,
    installment_lookup_semaphore: asyncio.Semaphore,
    payment_list_semaphore: asyncio.Semaphore,
    acs_scheduler: AdaptiveAcsScheduler,
) -> None:
    encoded_value = await _resolve_parallel_installment(
        run_id=run_id,
        item=item,
        card=card,
        amount=amount,
        currency=currency,
        installment_count=installment_count,
        provider=installment_provider,
        run_store=run_store,
        semaphore=installment_lookup_semaphore,
    )
    request = _payment_form_request(
        card=card,
        amount=amount,
        currency=currency,
        installment_count=installment_count,
        installment_encoded_value=encoded_value,
    )
    await session_store.create(
        order_id=item.order_id,
        amount=request.amount,
        currency=request.currency,
        pan=request.card_number.get_secret_value(),
        card_holder=request.card_holder,
        requires_3ds=request.requires_3ds,
        installment_count=request.installment_count,
    )
    initialization_started = perf_counter()
    async with initialization_semaphore:
        if installment_count == 1:
            await run_store.mutate(
                run_id,
                lambda run: _mark_item_running(run, item.item_id),
            )
        outcome = await initializer.initialize(
            request,
            order_id=item.order_id,
            card_holder_ip=client_host,
        )
    initialization_ms = _elapsed_ms(initialization_started)
    await _record_provider_outcome(
        run_id=run_id,
        item_id=item.item_id,
        outcome=outcome,
        card=card,
        auto_complete_3ds=auto_complete_3ds,
        initializer=initializer,
        automator=automator,
        session_store=session_store,
        three_ds_form_store=three_ds_form_store,
        run_store=run_store,
        currency=request.currency,
        initialization_ms=initialization_ms,
        payment_list_semaphore=payment_list_semaphore,
        acs_scheduler=acs_scheduler,
    )


async def _resolve_parallel_installment(
    *,
    run_id: str,
    item: ParallelRunItemState,
    card: TestCard,
    amount: Decimal,
    currency: Currency,
    installment_count: int,
    provider: SupportsInstallmentProvider | None,
    run_store: ParallelRunStore,
    semaphore: asyncio.Semaphore,
) -> SecretStr | None:
    if installment_count == 1:
        return None

    source: Literal["local_stub", "paynkolay_uat"] = (
        "paynkolay_uat" if provider is not None else "local_stub"
    )
    started_at = perf_counter()
    try:
        async with semaphore:
            await run_store.mutate(
                run_id,
                lambda run: _mark_item_running(run, item.item_id),
            )
            if provider is None:
                available_counts = local_stub_installment_counts(
                    amount=amount,
                    currency=currency.value,
                )
                if installment_count not in available_counts:
                    raise InstallmentOptionUnavailableError(
                        f"installment count {installment_count} is unavailable "
                        "for this card and amount"
                    )
                return None

            response = await provider.get_options(
                amount=amount,
                card_number=card.pan,
            )
            quote = select_installment_quote(
                response,
                installment_count=installment_count,
                currency=currency.value,
            )
            return quote.encoded_value
    finally:
        elapsed_ms = _elapsed_ms(started_at)
        await run_store.mutate(
            run_id,
            lambda run: _record_installment_lookup(
                run,
                item.item_id,
                source=source,
                elapsed_ms=elapsed_ms,
            ),
        )


async def _mark_session_failed(
    session_store: PaymentSessionStore,
    order_id: str,
    failure_reason: str,
) -> None:
    try:
        await session_store.update_status(
            order_id,
            PaymentSessionStatus.FAILED,
            failure_reason=failure_reason,
        )
    except Exception:
        return


async def _record_provider_outcome(
    *,
    run_id: str,
    item_id: str,
    outcome: PaymentInitializationOutcome,
    card: TestCard,
    auto_complete_3ds: bool,
    initializer: SupportsPaymentInitializer,
    automator: SupportsThreeDSAutomator,
    session_store: PaymentSessionStore,
    three_ds_form_store: ThreeDSFormStore,
    run_store: ParallelRunStore,
    currency: Currency,
    initialization_ms: int,
    payment_list_semaphore: asyncio.Semaphore,
    acs_scheduler: AdaptiveAcsScheduler,
) -> None:
    provider_request = _provider_request_summary(outcome)
    provider_result = outcome.provider_result
    if isinstance(provider_result, PaynkolayThreeDSInitializeResult):
        order_id = outcome.payment_request.order_id
        await three_ds_form_store.put(
            order_id,
            provider_result.bank_request_message,
        )
        await session_store.update_status(
            order_id,
            PaymentSessionStatus.PENDING_3DS,
            provider_request=provider_request,
        )
        if not auto_complete_3ds:
            await run_store.mutate(
                run_id,
                lambda run: _mark_item_completed(
                    run,
                    item_id,
                    provider_request=provider_request,
                    classification="pending_3ds",
                    initialization_ms=initialization_ms,
                    three_ds_url=f"/payments/{order_id}/three-ds",
                ),
            )
            return
        await session_store.update_three_ds_automation(
            order_id,
            ThreeDSAutomationSummary(status="running", reason="3DS automation started"),
        )
        acs_execution = await acs_scheduler.execute(
            card.alias,
            lambda: automator.complete(
                html=provider_result.bank_request_message,
                brand=card.brand,
                configured_otp=card.expected_otp,
                callback_url=outcome.success_url,
            ),
        )
        automation_result = acs_execution.result
        await _sync_acs_scheduler(run_store, run_id, acs_scheduler)
        automation_summary = ThreeDSAutomationSummary.model_validate(
            automation_result.summary()
        )
        await session_store.update_three_ds_automation(order_id, automation_summary)
        if not automation_result.completed or not automation_result.submitted:
            await run_store.mutate(
                run_id,
                lambda run: _mark_item_completed(
                    run,
                    item_id,
                    provider_request=provider_request,
                    classification=_classification_for_acs_automation(automation_result),
                    initialization_ms=initialization_ms,
                    acs_wait_ms=acs_execution.wait_ms,
                    acs_duration_ms=acs_execution.duration_ms,
                    three_ds_url=f"/payments/{order_id}/three-ds",
                    three_ds_automation=automation_summary,
                ),
            )
            return

        payment_list_started = perf_counter()
        async with payment_list_semaphore:
            session = await _verify_parallel_payment_list(
                order_id=order_id,
                currency=currency,
                initializer=initializer,
                session_store=session_store,
                retry_delays=SUBMITTED_3DS_PAYMENT_LIST_RETRY_DELAYS,
            )
        payment_list_ms = _elapsed_ms(payment_list_started)
        classification = _classification_for_payment_list_status(
            session.payment_list_status.value if session.payment_list_status is not None else None
        )
        await session_store.update_status(
            order_id,
            PaymentSessionStatus.COMPLETED
            if classification == "completed"
            else PaymentSessionStatus.STATUS_VERIFIED,
        )
        await run_store.mutate(
            run_id,
            lambda run: _mark_item_completed(
                run,
                item_id,
                provider_request=provider_request,
                classification=classification,
                initialization_ms=initialization_ms,
                acs_wait_ms=acs_execution.wait_ms,
                acs_duration_ms=acs_execution.duration_ms,
                payment_list_ms=payment_list_ms,
                payment_list=PaymentListStatusSummary.from_session(session),
                payment_list_status=(
                    session.payment_list_status.value
                    if session.payment_list_status is not None
                    else None
                ),
                payment_list_error=session.payment_list_error,
                three_ds_url=f"/payments/{order_id}/three-ds",
                three_ds_automation=automation_summary,
            ),
        )
        return

    if isinstance(provider_result, PaynkolayPaymentResult):
        session_status = (
            PaymentSessionStatus.COMPLETED
            if provider_result.successful
            else PaymentSessionStatus.FAILED
        )
        session = await session_store.update_status(
            outcome.payment_request.order_id,
            session_status,
            provider_request=provider_request,
            provider_transaction_id=provider_result.reference_code,
            provider_response_code=provider_result.response_code,
            provider_response_data=provider_result.response_data,
            failure_reason=(
                provider_result.response_data if not provider_result.successful else None
            ),
        )
        payment_list_started = perf_counter()
        try:
            async with payment_list_semaphore:
                status_response = await verify_transaction_status_with_retry(
                    initializer,
                    outcome.payment_request.order_id,
                    currency=currency,
                )
            session = await session_store.update_payment_list_status(
                outcome.payment_request.order_id,
                status_response,
            )
        except PaymentProviderStatusVerificationError as exc:
            session = await session_store.update_payment_list_error(
                outcome.payment_request.order_id,
                str(exc),
            )
        payment_list_ms = _elapsed_ms(payment_list_started)
        await run_store.mutate(
            run_id,
            lambda run: _mark_item_completed(
                run,
                item_id,
                provider_request=provider_request,
                provider_response_code=provider_result.response_code,
                provider_response_data=provider_result.response_data,
                initialization_ms=initialization_ms,
                payment_list_ms=payment_list_ms,
                payment_list=PaymentListStatusSummary.from_session(session),
                payment_list_status=(
                    session.payment_list_status.value
                    if session.payment_list_status is not None
                    else None
                ),
                payment_list_error=session.payment_list_error,
                classification="completed" if provider_result.successful else "provider_failed",
            ),
        )


async def _verify_parallel_payment_list(
    *,
    order_id: str,
    currency: Currency,
    initializer: SupportsPaymentInitializer,
    session_store: PaymentSessionStore,
    retry_delays: tuple[float, ...] | None = None,
) -> PaymentSession:
    try:
        return await session_store.update_payment_list_status(
            order_id,
            await verify_transaction_status_with_retry(
                initializer,
                order_id,
                currency=currency,
                accepted_statuses=FINAL_PAYMENT_LIST_STATUSES,
                **({"retry_delays": retry_delays} if retry_delays is not None else {}),
            ),
        )
    except PaymentProviderStatusVerificationError as exc:
        return await session_store.update_payment_list_error(order_id, str(exc))


async def _sync_acs_scheduler(
    run_store: ParallelRunStore,
    run_id: str,
    scheduler: AdaptiveAcsScheduler,
) -> None:
    snapshot = scheduler.snapshot()
    await run_store.mutate(
        run_id,
        lambda run: setattr(run, "acs_scheduler", snapshot),
    )


def _elapsed_ms(started_at: float) -> int:
    return max(0, int((perf_counter() - started_at) * 1000))


def _load_card_map() -> dict[str, TestCard]:
    try:
        cards = load_runtime_settings().current.cards
    except (FileNotFoundError, RuntimeError, ValueError) as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"runtime payment configuration is unavailable: {exc}",
        ) from exc
    return {card.alias: card for card in cards}


def _require_uat_installment_provider(
    request: ParallelRunCreateRequest,
    provider: SupportsInstallmentProvider | None,
) -> None:
    if request.installment_count == 1 or provider is not None:
        return
    try:
        environment = load_runtime_settings().current
    except (FileNotFoundError, RuntimeError, ValueError):
        return
    if environment.name.value == "uat":
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="runtime installment API key is unavailable",
        )


def _serial_3ds_locks_for_run(
    items: Sequence[ParallelRunItemState],
    cards_by_alias: dict[str, TestCard],
) -> dict[str, asyncio.Lock]:
    locks: dict[str, asyncio.Lock] = {}
    for item in items:
        card = cards_by_alias[item.card_alias]
        if _requires_serial_3ds_automation(card):
            locks.setdefault(item.card_alias, asyncio.Lock())
    return locks


def _requires_serial_3ds_automation(card: TestCard) -> bool:
    return (
        card.requires_3ds
        and behavior_for_alias(card.alias).status is CardAutomationStatus.AUTOMATION_DIAGNOSTIC
    )


def _select_cards(
    request: ParallelRunCreateRequest,
    cards: dict[str, TestCard],
) -> list[TestCard]:
    if request.mode == "manual":
        selected: list[TestCard] = []
        for item in request.manual_cards:
            card = cards.get(item.alias)
            if card is None:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                    detail=f"unknown card alias: {item.alias}",
                )
            selected.extend([card] * item.repeat_count)
        return selected

    real_cards = [
        card
        for card in cards.values()
        if not card.alias.startswith("synthetic_")
        and behavior_for_alias(card.alias).status is CardAutomationStatus.SUCCESS_AUTO
    ]
    if not real_cards:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="random mode requires at least one automatic success candidate card",
        )
    count = request.random_count or 1
    return [random.choice(real_cards) for _ in range(count)]


def _parallel_items(
    *,
    run_id: str,
    selected_cards: list[TestCard],
    installment_count: int,
) -> list[ParallelRunItemState]:
    attempts_by_alias: Counter[str] = Counter()
    items: list[ParallelRunItemState] = []
    for index, card in enumerate(selected_cards, start=1):
        attempts_by_alias[card.alias] += 1
        behavior = behavior_for_alias(card.alias)
        items.append(
            ParallelRunItemState(
                item_id=f"item-{index:03d}",
                card_alias=card.alias,
                attempt_index=attempts_by_alias[card.alias],
                order_id=f"batch-{run_id[:8]}-{index:03d}",
                requires_3ds=card.requires_3ds,
                installment_count=installment_count,
                automation_status=behavior.status.value,
                automation_reason=behavior.reason,
                diagnostic_class=behavior.diagnostic_class,
                automatic_success_candidate=behavior.eligible_for_automatic_success,
            )
        )
    return items


def _payment_form_request(
    *,
    card: TestCard,
    amount: Decimal,
    currency: Currency,
    installment_count: int,
    installment_encoded_value: SecretStr | None,
) -> PaymentFormRequest:
    return PaymentFormRequest(
        amount=amount,
        currency=currency,
        card_brand=card.brand,
        card_number=card.pan,
        card_holder="PAYNKOLAY TEST",
        expiry_month=card.expiry_month,
        expiry_year=card.expiry_year,
        cvv=card.cvv,
        requires_3ds=card.requires_3ds,
        installment_count=installment_count,
        installment_encoded_value=installment_encoded_value,
    )


def _mark_item_running(run: ParallelRunState, item_id: str) -> None:
    item = _item(run, item_id)
    item.status = "running"
    item.classification = "running"
    item.started_at = utc_now()
    active_items = sum(candidate.status == "running" for candidate in run.items)
    run.peak_active_items = max(run.peak_active_items, active_items)


def _record_installment_lookup(
    run: ParallelRunState,
    item_id: str,
    *,
    source: Literal["local_stub", "paynkolay_uat"],
    elapsed_ms: int,
) -> None:
    item = _item(run, item_id)
    item.installment_source = source
    item.installment_lookup_ms = elapsed_ms


def _mark_item_completed(
    run: ParallelRunState,
    item_id: str,
    *,
    provider_request: ProviderRequestSummary,
    classification: str,
    provider_response_code: str | None = None,
    provider_response_data: str | None = None,
    payment_list: PaymentListStatusSummary | None = None,
    payment_list_status: str | None = None,
    payment_list_error: str | None = None,
    three_ds_automation: ThreeDSAutomationSummary | None = None,
    three_ds_url: str | None = None,
    initialization_ms: int | None = None,
    acs_wait_ms: int | None = None,
    acs_duration_ms: int | None = None,
    payment_list_ms: int | None = None,
) -> None:
    item = _item(run, item_id)
    item.status = "completed"
    item.classification = classification
    item.provider_request = provider_request
    item.provider_response_code = provider_response_code
    item.provider_response_data = provider_response_data
    item.payment_list = payment_list
    item.payment_list_status = payment_list_status
    item.payment_list_error = payment_list_error
    item.three_ds_automation = three_ds_automation
    item.three_ds_url = three_ds_url
    item.initialization_ms = initialization_ms
    item.acs_wait_ms = acs_wait_ms
    item.acs_duration_ms = acs_duration_ms
    item.payment_list_ms = payment_list_ms
    item.finished_at = utc_now()


def _mark_item_failed(
    run: ParallelRunState,
    item_id: str,
    *,
    classification: str,
    error_message: str,
) -> None:
    item = _item(run, item_id)
    item.status = "failed"
    item.classification = classification
    item.error_message = error_message
    item.finished_at = utc_now()


def _record_unhandled_task_errors(
    run: ParallelRunState,
    task_results: Sequence[object],
) -> None:
    unhandled_errors = [result for result in task_results if isinstance(result, BaseException)]
    pending_items = [item for item in run.items if item.status in {"pending", "running"}]
    for item, error in zip(pending_items, unhandled_errors, strict=False):
        item.status = "failed"
        item.classification = "framework_error"
        item.error_message = f"{type(error).__name__}: {error}"
        item.finished_at = utc_now()


def _finish_run(run: ParallelRunState) -> None:
    run.finished_at = utc_now()
    failed_count = sum(1 for item in run.items if item.status == "failed")
    attention_count = sum(1 for item in run.items if item.classification != "completed")
    if failed_count or attention_count:
        run.status = "completed_with_failures"
        run.message = "Parallel run completed with failed items."
    else:
        run.status = "completed"
        run.message = "Parallel run completed."
    _export_parallel_run_evidence(run)


def _export_parallel_run_evidence(run: ParallelRunState) -> None:
    evidence_dir = Path(os.getenv("PAYNKOLAY_PARALLEL_EVIDENCE_DIR", "reports/parallel-runs"))
    evidence_path = evidence_dir / f"{run.run_id}.json"
    run.evidence_path = str(evidence_path)
    payload = {
        "event": "parallel_run_evidence",
        "run": run.response(include_items=True).model_dump(mode="json"),
    }
    try:
        evidence_dir.mkdir(parents=True, exist_ok=True)
        evidence_path.write_text(f"{evidence_json(payload)}\n", encoding="utf-8")
    except OSError as exc:
        run.evidence_path = None
        run.message = f"{run.message} Evidence export failed: {exc}"


def _item(run: ParallelRunState, item_id: str) -> ParallelRunItemState:
    for item in run.items:
        if item.item_id == item_id:
            return item
    raise KeyError(f"parallel run item does not exist: {item_id}")


def _client_host(request: Request) -> str:
    if request.client is None or not request.client.host.strip():
        return "127.0.0.1"
    return request.client.host


def _classify_initialization_error(exc: PaymentProviderInitializationError) -> str:
    error_text = " ".join(str(part) for part in _exception_chain(exc)).lower()
    network_markers = (
        "nodename nor servname",
        "name or service not known",
        "temporary failure in name resolution",
        "connection refused",
        "connection reset",
        "connecterror",
        "network",
        "timeout",
        "timed out",
        "dns",
    )
    if any(marker in error_text for marker in network_markers):
        return "network_error"
    return "framework_error"


def _classification_for_acs_automation(result: object) -> str:
    classification = getattr(result, "screen_classification", None)
    reason = str(getattr(result, "reason", "") or "")
    if classification in {"sms_manual_required", "mobile_approval_required"}:
        return "acs_manual_required"
    if classification == "acs_error_screen":
        return "acs_error"
    if classification == "blank_or_redirect_error":
        return "blank_or_redirect_error"
    if "missing_source" in reason:
        return "acs_manual_required"
    return "framework_error"


def _classification_for_payment_list_status(payment_list_status: str | None) -> str:
    if payment_list_status in {
        PaymentStatus.AUTHENTICATED.value,
        PaymentStatus.AUTHORIZED.value,
        PaymentStatus.CAPTURED.value,
    }:
        return "completed"
    if payment_list_status == PaymentStatus.FAILED.value:
        return "provider_failed"
    if payment_list_status == PaymentStatus.CREATED.value:
        return "awaiting_provider_finalization"
    if payment_list_status is None:
        return "payment_list_missing"
    return "needs_investigation"


def _exception_chain(exc: BaseException) -> list[BaseException]:
    chain = [exc]
    current = exc
    while current.__cause__ is not None:
        chain.append(current.__cause__)
        current = current.__cause__
    return chain
