from __future__ import annotations

from typing import Any

import pytest
from pydantic import SecretStr

from paynkolay_pos.api import dependencies
from paynkolay_pos.api.dependencies import PlaywrightThreeDSAutomator
from paynkolay_pos.config import CardBrand
from paynkolay_pos.three_ds import AcsBrowserAutomationResult

pytestmark = pytest.mark.asyncio


def automation_result(
    *,
    submitted: bool,
    reason: str,
    otp_resolution: dict[str, object] | None = None,
) -> AcsBrowserAutomationResult:
    return AcsBrowserAutomationResult(
        completed=submitted,
        submitted=submitted,
        reason=reason,
        otp_resolution=otp_resolution,
        frames=(),
    )


async def complete_with(
    automator: PlaywrightThreeDSAutomator,
) -> AcsBrowserAutomationResult:
    return await automator.complete(
        html="<form></form>",
        brand=CardBrand.VISA,
        configured_otp=SecretStr("123456"),
        callback_url="https://merchant.example.test/callback",
    )


async def test_playwright_automator_retries_headed_when_headless_missing_source(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[bool] = []

    async def fake_complete(**kwargs: Any) -> AcsBrowserAutomationResult:
        calls.append(bool(kwargs["headed"]))
        if len(calls) == 1:
            return automation_result(
                submitted=False,
                reason="otp_resolution_missing_source",
                otp_resolution={
                    "status": "missing_source",
                    "source_type": None,
                    "otp_present": False,
                    "should_auto_submit": False,
                    "reason": "no visible OTP",
                },
            )
        return automation_result(
            submitted=True,
            reason="otp_submitted",
            otp_resolution={
                "status": "ready",
                "source_type": "visible_page",
                "otp_present": True,
                "should_auto_submit": True,
                "reason": "resolved OTP from visible ACS simulator text",
            },
        )

    monkeypatch.setattr(dependencies, "complete_acs_browser_challenge", fake_complete)
    automator = PlaywrightThreeDSAutomator(
        form_base_url="https://acs.example.test/",
        headed=False,
        close_delay_seconds=0.0,
        headed_fallback=True,
    )

    result = await complete_with(automator)

    assert result.submitted is True
    assert calls == [False, True]


async def test_playwright_automator_retries_headed_when_headless_otp_selector_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[bool] = []

    async def fake_complete(**kwargs: Any) -> AcsBrowserAutomationResult:
        calls.append(bool(kwargs["headed"]))
        if len(calls) == 1:
            return automation_result(submitted=False, reason="otp_selector_not_found")
        return automation_result(
            submitted=True,
            reason="otp_submitted",
            otp_resolution={
                "status": "ready",
                "source_type": "visible_page",
                "otp_present": True,
                "should_auto_submit": True,
                "reason": "resolved OTP from visible ACS simulator text",
            },
        )

    monkeypatch.setattr(dependencies, "complete_acs_browser_challenge", fake_complete)
    automator = PlaywrightThreeDSAutomator(
        form_base_url="https://acs.example.test/",
        headed=False,
        close_delay_seconds=0.0,
        headed_fallback=True,
    )

    result = await complete_with(automator)

    assert result.submitted is True
    assert calls == [False, True]


async def test_playwright_automator_does_not_retry_when_fallback_disabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[bool] = []

    async def fake_complete(**kwargs: Any) -> AcsBrowserAutomationResult:
        calls.append(bool(kwargs["headed"]))
        return automation_result(
            submitted=False,
            reason="otp_resolution_missing_source",
            otp_resolution={"status": "missing_source"},
        )

    monkeypatch.setattr(dependencies, "complete_acs_browser_challenge", fake_complete)
    automator = PlaywrightThreeDSAutomator(
        form_base_url="https://acs.example.test/",
        headed=False,
        close_delay_seconds=0.0,
        headed_fallback=False,
    )

    result = await complete_with(automator)

    assert result.submitted is False
    assert calls == [False]


async def test_playwright_automator_does_not_retry_other_failures(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[bool] = []

    async def fake_complete(**kwargs: Any) -> AcsBrowserAutomationResult:
        calls.append(bool(kwargs["headed"]))
        return automation_result(submitted=False, reason="submit_selector_not_found")

    monkeypatch.setattr(dependencies, "complete_acs_browser_challenge", fake_complete)
    automator = PlaywrightThreeDSAutomator(
        form_base_url="https://acs.example.test/",
        headed=False,
        close_delay_seconds=0.0,
        headed_fallback=True,
    )

    result = await complete_with(automator)

    assert result.submitted is False
    assert calls == [False]


async def test_playwright_automator_reuses_shared_browser() -> None:
    automator = PlaywrightThreeDSAutomator(
        form_base_url="https://acs.example.test/",
        headed=False,
        close_delay_seconds=0.0,
        headed_fallback=False,
    )
    try:
        first = await automator._browser(headed=False)
        second = await automator._browser(headed=False)

        assert first is second
        assert first.is_connected()
    finally:
        await automator.aclose()
