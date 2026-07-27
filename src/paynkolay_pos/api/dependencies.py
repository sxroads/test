"""Shared dependencies and filesystem paths for the FastAPI app."""

from __future__ import annotations

import asyncio
import os
from collections.abc import AsyncIterator
from contextlib import suppress
from pathlib import Path
from typing import Protocol, cast

from fastapi import HTTPException, Request, status
from playwright.async_api import Browser, Playwright, async_playwright
from pydantic import SecretStr

from paynkolay_pos.api.installment_provider import (
    PaynkolayInstallmentProvider,
    SupportsInstallmentProvider,
)
from paynkolay_pos.api.parallel_run_store import ParallelRunStore
from paynkolay_pos.api.payment_initializer import (
    PaynkolayPaymentInitializer,
    SupportsPaymentInitializer,
)
from paynkolay_pos.api.session_store import PaymentSessionStore
from paynkolay_pos.api.three_ds_store import ThreeDSFormStore
from paynkolay_pos.clients import PaynkolayClient
from paynkolay_pos.config import load_runtime_settings
from paynkolay_pos.config.settings import CardBrand
from paynkolay_pos.reporting import (
    SupportsExternalPaymentLogger,
    external_logger_from_env,
)
from paynkolay_pos.three_ds import AcsBrowserAutomationResult, complete_acs_browser_challenge


class SupportsThreeDSAutomator(Protocol):
    """Behavior required to complete ACS browser challenges."""

    async def complete(
        self,
        *,
        html: str,
        brand: CardBrand,
        configured_otp: SecretStr | None,
        callback_url: str,
    ) -> AcsBrowserAutomationResult:
        """Complete a 3DS challenge and return sanitized evidence."""


class PlaywrightThreeDSAutomator:
    """Default server-side Playwright automator."""

    def __init__(
        self,
        *,
        form_base_url: str,
        headed: bool,
        close_delay_seconds: float,
        headed_fallback: bool,
    ) -> None:
        self._form_base_url = form_base_url
        self._headed = headed
        self._close_delay_seconds = close_delay_seconds
        self._headed_fallback = headed_fallback
        self._playwright: Playwright | None = None
        self._browsers: dict[bool, Browser] = {}
        self._browser_lock = asyncio.Lock()

    async def complete(
        self,
        *,
        html: str,
        brand: CardBrand,
        configured_otp: SecretStr | None,
        callback_url: str,
    ) -> AcsBrowserAutomationResult:
        """Complete a 3DS challenge using Chromium."""

        result = await self._complete(
            html=html,
            brand=brand,
            configured_otp=configured_otp,
            callback_url=callback_url,
            headed=self._headed,
        )
        if self._should_retry_headed(result):
            return await self._complete(
                html=html,
                brand=brand,
                configured_otp=configured_otp,
                callback_url=callback_url,
                headed=True,
            )
        return result

    async def _complete(
        self,
        *,
        html: str,
        brand: CardBrand,
        configured_otp: SecretStr | None,
        callback_url: str,
        headed: bool,
    ) -> AcsBrowserAutomationResult:
        browser = await self._browser(headed=headed)
        return await complete_acs_browser_challenge(
            html=html,
            brand=brand,
            configured_otp=configured_otp,
            callback_url=callback_url,
            form_base_url=self._form_base_url,
            headed=headed,
            close_delay_seconds=self._close_delay_seconds,
            browser=browser,
        )

    async def _browser(self, *, headed: bool) -> Browser:
        async with self._browser_lock:
            browser = self._browsers.get(headed)
            if browser is not None and browser.is_connected():
                return browser
            if self._playwright is None:
                self._playwright = await async_playwright().start()
            browser = await self._playwright.chromium.launch(headless=not headed)
            self._browsers[headed] = browser
            return browser

    async def aclose(self) -> None:
        """Close shared Chromium processes and the Playwright driver."""

        async with self._browser_lock:
            for browser in self._browsers.values():
                with suppress(Exception):
                    await browser.close()
            self._browsers.clear()
            if self._playwright is not None:
                with suppress(Exception):
                    await self._playwright.stop()
                self._playwright = None

    def _should_retry_headed(self, result: AcsBrowserAutomationResult) -> bool:
        """Retry in headed mode only when headless could not find a dynamic OTP source."""

        if self._headed or not self._headed_fallback or result.submitted:
            return False
        resolution = result.otp_resolution or {}
        return (
            result.reason in {"otp_resolution_missing_source", "otp_selector_not_found"}
            or resolution.get("status") == "missing_source"
        )


def package_root() -> Path:
    """Return the installed package root directory."""

    return Path(__file__).resolve().parents[1]


def web_root() -> Path:
    """Return the packaged web asset root directory."""

    return package_root() / "web"


def templates_dir() -> Path:
    """Return the Jinja template directory."""

    return web_root() / "templates"


def static_dir() -> Path:
    """Return the static asset directory."""

    return web_root() / "static"


def allure_report_dir() -> Path:
    """Return the local Allure HTML report directory."""

    return Path(os.getenv("PAYNKOLAY_ALLURE_REPORT_DIR", "allure-report"))


def allure_results_dir() -> Path:
    """Return the local Allure raw results directory."""

    return Path(os.getenv("PAYNKOLAY_ALLURE_RESULTS_DIR", "allure-results"))


def get_payment_session_store(request: Request) -> PaymentSessionStore:
    """Return the app-scoped in-memory payment session store."""

    return cast(PaymentSessionStore, request.app.state.payment_session_store)


def get_three_ds_form_store(request: Request) -> ThreeDSFormStore:
    """Return the app-scoped transient 3DS form store."""

    return cast(ThreeDSFormStore, request.app.state.three_ds_form_store)


def get_parallel_run_store(request: Request) -> ParallelRunStore:
    """Return the app-scoped in-memory parallel run store."""

    return cast(ParallelRunStore, request.app.state.parallel_run_store)


def create_three_ds_automator() -> PlaywrightThreeDSAutomator:
    """Create the app-scoped 3DS browser automator."""

    return PlaywrightThreeDSAutomator(
        form_base_url=os.getenv(
            "PAYNKOLAY_UAT_3DS_FORM_BASE_URL",
            "https://vpostest.qnb.com.tr/PayforACSSimulator/",
        ),
        headed=_env_flag("PAYNKOLAY_3DS_AUTOMATION_HEADED", default=False),
        close_delay_seconds=_env_float("PAYNKOLAY_3DS_AUTOMATION_CLOSE_DELAY", default=0.0),
        headed_fallback=_env_flag("PAYNKOLAY_3DS_AUTOMATION_HEADED_FALLBACK", default=True),
    )


def get_three_ds_automator(request: Request) -> SupportsThreeDSAutomator:
    """Return the app-scoped 3DS browser automator."""

    return cast(SupportsThreeDSAutomator, request.app.state.three_ds_automator)


def _env_flag(name: str, *, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _env_float(name: str, *, default: float) -> float:
    value = os.getenv(name)
    if value is None:
        return default
    try:
        return float(value)
    except ValueError:
        return default


async def get_payment_initializer() -> AsyncIterator[SupportsPaymentInitializer]:
    """Return a configured provider initializer for live payment attempts."""

    try:
        environment = load_runtime_settings().current
    except (FileNotFoundError, RuntimeError, ValueError) as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"runtime payment configuration is unavailable: {exc}",
        ) from exc

    async with PaynkolayClient(environment) as client:
        yield PaynkolayPaymentInitializer(
            environment=environment,
            client=client,
        )


async def get_installment_provider() -> AsyncIterator[SupportsInstallmentProvider | None]:
    """Use the real installment service only in a configured UAT runtime."""

    try:
        environment = load_runtime_settings().current
    except (FileNotFoundError, RuntimeError, ValueError):
        yield None
        return

    if environment.name.value != "uat":
        yield None
        return
    if environment.merchant.installment_api_key is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="runtime installment API key is unavailable",
        )

    async with PaynkolayClient(environment) as client:
        yield PaynkolayInstallmentProvider(client)


async def get_optional_installment_provider() -> (
    AsyncIterator[SupportsInstallmentProvider | None]
):
    """Return a real UAT installment provider without blocking single-payment runs."""

    try:
        environment = load_runtime_settings().current
    except (FileNotFoundError, RuntimeError, ValueError):
        yield None
        return

    if (
        environment.name.value != "uat"
        or environment.merchant.installment_api_key is None
    ):
        yield None
        return

    async with PaynkolayClient(environment) as client:
        yield PaynkolayInstallmentProvider(client)


def get_merchant_secret_key() -> SecretStr:
    """Return the active merchant secret key for provider return verification."""

    try:
        return load_runtime_settings().current.merchant.secret_key
    except (FileNotFoundError, RuntimeError, ValueError) as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"runtime payment configuration is unavailable: {exc}",
        ) from exc


def get_external_payment_logger() -> SupportsExternalPaymentLogger:
    """Return the configured external payment logger."""

    return external_logger_from_env()
