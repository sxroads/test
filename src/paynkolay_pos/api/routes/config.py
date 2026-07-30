"""Runtime metadata routes for the browser UI."""

from __future__ import annotations

import json
import os
from collections import Counter
from typing import Any, cast

from fastapi import APIRouter, HTTPException, status
from pydantic import ValidationError

from paynkolay_pos.api.runtime_config_store import mutate_runtime_config
from paynkolay_pos.api.schemas import (
    ConfigCardSummary,
    ConfigMerchantSummary,
    ConfigOverviewResponse,
    ConfigReadinessIssueSummary,
    ConfigReadinessSummary,
    ConfigResponse,
    ConfigScenarioCoverage,
    ConfigScenarioSummary,
    MerchantSettingsResponse,
    MerchantSettingsUpdateRequest,
)
from paynkolay_pos.config import CardBrand, TestCard, load_runtime_settings
from paynkolay_pos.models import Currency, PaymentChannel
from paynkolay_pos.sandbox import check_sandbox_readiness
from paynkolay_pos.scenarios import (
    PaymentScenarioCatalog,
    load_payment_scenario_catalog_from_env,
    scenario_catalog_path_from_env,
)
from paynkolay_pos.testing.card_behaviors import behavior_for_alias

router = APIRouter(prefix="/api/config", tags=["config"])


@router.get("", response_model=ConfigResponse)
async def get_config() -> ConfigResponse:
    """Return safe runtime configuration metadata for the browser."""

    supported_currencies = [currency.value for currency in Currency]
    supported_card_brands = [brand.value for brand in CardBrand]
    payment_channels = [channel.value for channel in PaymentChannel]

    try:
        settings = load_runtime_settings()
    except (FileNotFoundError, RuntimeError, ValueError) as exc:
        return ConfigResponse(
            runtime_configured=False,
            supported_currencies=supported_currencies,
            supported_card_brands=supported_card_brands,
            payment_channels=payment_channels,
            message=str(exc),
        )

    current = settings.current
    return ConfigResponse(
        runtime_configured=True,
        active_environment=current.name.value,
        supported_currencies=supported_currencies,
        supported_card_brands=supported_card_brands,
        payment_channels=payment_channels,
        card_aliases=[card.alias for card in current.cards],
    )


@router.get("/overview", response_model=ConfigOverviewResponse)
async def get_config_overview() -> ConfigOverviewResponse:
    """Return safe runtime, scenario, and readiness metadata for testers."""

    config_source = os.getenv("PAYNKOLAY_CONFIG_FILE")
    try:
        settings = load_runtime_settings()
    except (FileNotFoundError, RuntimeError, ValueError) as exc:
        return ConfigOverviewResponse(
            runtime_configured=False,
            config_source=config_source,
            scenarios=_scenario_summary_without_runtime(),
            readiness=ConfigReadinessSummary(
                checked=False,
                message="Runtime config is required before readiness can be checked.",
            ),
            message=str(exc),
        )

    current = settings.current
    scenario_summary, catalog = _scenario_summary()
    readiness = ConfigReadinessSummary(
        checked=False,
        message="Scenario catalogue is required before readiness can be checked.",
    )
    if catalog is not None:
        report = check_sandbox_readiness(settings, catalog)
        readiness = ConfigReadinessSummary(
            checked=True,
            ready=report.ready,
            issue_count=len(report.issues),
            issues=[
                ConfigReadinessIssueSummary(code=issue.code, message=issue.message)
                for issue in report.issues
            ],
        )

    return ConfigOverviewResponse(
        runtime_configured=True,
        active_environment=current.name.value,
        config_source=config_source,
        base_url_configured=True,
        callback_configured=True,
        merchant=ConfigMerchantSummary(
            merchant_id=_mask_value(current.merchant.merchant_id),
            terminal_id=_mask_value(current.merchant.terminal_id),
            has_list_key=current.merchant.list_api_key is not None,
            has_cancel_refund_key=current.merchant.cancel_refund_api_key is not None,
        ),
        card_count=len(current.cards),
        cards=[
            _card_summary(card)
            for card in current.cards
        ],
        scenarios=scenario_summary,
        readiness=readiness,
    )


@router.get("/merchant", response_model=MerchantSettingsResponse)
async def get_merchant_settings() -> MerchantSettingsResponse:
    """Return editable merchant metadata without exposing payment SX."""

    try:
        current = load_runtime_settings().current
    except (FileNotFoundError, RuntimeError, ValueError) as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="runtime merchant configuration is unavailable",
        ) from exc

    return MerchantSettingsResponse(
        environment=current.name.value,
        merchant_no=current.merchant.merchant_id,
        payment_sx_configured=bool(
            current.merchant.api_key.get_secret_value().strip()
        ),
    )


@router.patch("/merchant", response_model=MerchantSettingsResponse)
async def update_merchant_settings(
    request: MerchantSettingsUpdateRequest,
) -> MerchantSettingsResponse:
    """Update active merchant/payment SX values in the private runtime config."""

    payment_sx = (
        request.payment_sx.get_secret_value()
        if request.payment_sx is not None
        else None
    )
    if payment_sx is not None and not 1 <= len(payment_sx) <= 4096:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="payment_sx must contain between 1 and 4096 characters",
        )

    def update(payload: dict[str, object], active_environment: str) -> None:
        if request.environment != active_environment:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=(
                    "active environment changed; refresh Settings before saving "
                    f"(expected {request.environment}, active {active_environment})"
                ),
            )
        environment_payload = _active_environment_payload(payload, active_environment)
        merchant_payload = environment_payload.get("merchant")
        if not isinstance(merchant_payload, dict):
            raise ValueError("active runtime environment merchant must be an object")
        merchant_payload["merchant_id"] = request.merchant_no
        if payment_sx is not None:
            merchant_payload["api_key"] = payment_sx

    try:
        await mutate_runtime_config(update)
        current = load_runtime_settings().current
    except HTTPException:
        raise
    except (OSError, json.JSONDecodeError, ValidationError, ValueError, RuntimeError) as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="runtime merchant configuration could not be saved",
        ) from exc

    return MerchantSettingsResponse(
        environment=current.name.value,
        merchant_no=current.merchant.merchant_id,
        payment_sx_configured=bool(
            current.merchant.api_key.get_secret_value().strip()
        ),
        message="Merchant settings saved for new payment runs.",
    )


def _card_summary(card: TestCard) -> ConfigCardSummary:
    behavior = behavior_for_alias(card.alias)
    return ConfigCardSummary(
        alias=card.alias,
        brand=card.brand.value,
        requires_3ds=card.requires_3ds,
        has_expected_otp=card.expected_otp is not None,
        automation_status=behavior.status.value,
        automation_reason=behavior.reason,
        diagnostic_class=behavior.diagnostic_class,
        automatic_success_candidate=behavior.eligible_for_automatic_success,
    )


def _scenario_summary() -> tuple[ConfigScenarioSummary, PaymentScenarioCatalog | None]:
    source = str(scenario_catalog_path_from_env())
    try:
        catalog = load_payment_scenario_catalog_from_env()
    except (FileNotFoundError, RuntimeError, ValueError) as exc:
        return (
            ConfigScenarioSummary(
                configured=False,
                source=source,
                message=str(exc),
            ),
            None,
        )

    tags = sorted({tag for scenario in catalog.scenarios for tag in scenario.tags})
    return (
        ConfigScenarioSummary(
            configured=True,
            source=source,
            scenario_count=len(catalog.scenarios),
            tags=tags,
            coverage=_scenario_coverage(catalog),
        ),
        catalog,
    )


def _scenario_summary_without_runtime() -> ConfigScenarioSummary:
    source = str(scenario_catalog_path_from_env())
    try:
        catalog = load_payment_scenario_catalog_from_env()
    except (FileNotFoundError, RuntimeError, ValueError) as exc:
        return ConfigScenarioSummary(configured=False, source=source, message=str(exc))

    tags = sorted({tag for scenario in catalog.scenarios for tag in scenario.tags})
    return ConfigScenarioSummary(
        configured=True,
        source=source,
        scenario_count=len(catalog.scenarios),
        tags=tags,
        coverage=_scenario_coverage(catalog),
    )


def _scenario_coverage(catalog: PaymentScenarioCatalog) -> ConfigScenarioCoverage:
    payment_channels = Counter(scenario.payment_channel.value for scenario in catalog.scenarios)
    final_statuses = Counter(scenario.expected_final_status.value for scenario in catalog.scenarios)
    installments = Counter(str(scenario.installment_count) for scenario in catalog.scenarios)
    error_codes = Counter(
        tag.removeprefix("error_code_")
        for scenario in catalog.scenarios
        for tag in scenario.tags
        if tag.startswith("error_code_")
    )
    return ConfigScenarioCoverage(
        three_ds_count=sum(1 for scenario in catalog.scenarios if scenario.requires_3ds),
        moto_count=sum(1 for scenario in catalog.scenarios if scenario.moto),
        single_payment_count=sum(
            1 for scenario in catalog.scenarios if scenario.installment_count == 1
        ),
        installment_count=sum(
            1 for scenario in catalog.scenarios if scenario.installment_count > 1
        ),
        negative_count=sum(1 for scenario in catalog.scenarios if "negative" in scenario.tags),
        payment_channel_counts=dict(sorted(payment_channels.items())),
        final_status_counts=dict(sorted(final_statuses.items())),
        installment_counts=dict(sorted(installments.items(), key=lambda item: int(item[0]))),
        error_code_counts=dict(sorted(error_codes.items())),
    )


def _mask_value(value: str) -> str:
    if len(value) <= 4:
        return "*" * len(value)
    return f"{value[:2]}{'*' * max(len(value) - 4, 4)}{value[-2:]}"


def _active_environment_payload(
    payload: dict[str, object],
    current_environment: str,
) -> dict[str, Any]:
    environments = payload.get("environments")
    if not isinstance(environments, dict):
        raise ValueError("runtime configuration environments must be an object")
    environment_payload = environments.get(current_environment)
    if not isinstance(environment_payload, dict):
        raise ValueError(
            f"active environment is missing from runtime config: {current_environment}"
        )
    return cast(dict[str, Any], environment_payload)
