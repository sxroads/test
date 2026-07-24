from __future__ import annotations

import asyncio
from typing import Any, cast

import pytest

from paynkolay_pos.api import acs_scheduler
from paynkolay_pos.api.acs_scheduler import AdaptiveAcsScheduler
from paynkolay_pos.three_ds import AcsBrowserAutomationResult


def _success() -> AcsBrowserAutomationResult:
    return AcsBrowserAutomationResult(
        completed=True,
        submitted=True,
        returned_to_callback=True,
        reason="otp_submitted",
    )


@pytest.mark.asyncio
async def test_stable_scheduler_ramps_nkolay_after_four_successes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(acs_scheduler, "STABLE_LAUNCH_GAP_SECONDS", 0.0)
    scheduler = AdaptiveAcsScheduler(profile="stable", requested_concurrency=10)

    for _ in range(4):
        await scheduler.execute("nkolay_dynamic_otp_visa_6111", _successful_operation)

    pools = cast(dict[str, dict[str, Any]], scheduler.snapshot()["pools"])
    pool = pools["nkolay"]
    assert pool["initial_limit"] == 4
    assert pool["final_limit"] == 5
    assert pool["maximum_limit"] == 10


@pytest.mark.asyncio
async def test_stable_scheduler_halves_limit_after_chrome_network_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(acs_scheduler, "STABLE_LAUNCH_GAP_SECONDS", 0.0)
    scheduler = AdaptiveAcsScheduler(profile="stable", requested_concurrency=10)

    async def failed_operation() -> AcsBrowserAutomationResult:
        return AcsBrowserAutomationResult(
            completed=False,
            submitted=False,
            reason="otp_selector_not_found",
            final_url="chrome-error://chromewebdata/",
            screen_classification="blank_or_redirect_error",
        )

    await scheduler.execute("nkolay_dynamic_otp_visa_6111", failed_operation)

    pools = cast(dict[str, dict[str, Any]], scheduler.snapshot()["pools"])
    assert pools["nkolay"]["final_limit"] == 2


@pytest.mark.asyncio
async def test_load_scheduler_uses_requested_concurrency(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(acs_scheduler, "STABLE_LAUNCH_GAP_SECONDS", 0.0)
    scheduler = AdaptiveAcsScheduler(profile="load", requested_concurrency=8)
    active = 0
    peak = 0

    async def operation() -> AcsBrowserAutomationResult:
        nonlocal active, peak
        active += 1
        peak = max(peak, active)
        await asyncio.sleep(0.01)
        active -= 1
        return _success()

    await asyncio.gather(
        *[
            scheduler.execute("nkolay_dynamic_otp_visa_6111", operation)
            for _ in range(8)
        ]
    )

    assert peak == 8
    assert scheduler.snapshot()["peak_concurrency"] == 8


@pytest.mark.asyncio
async def test_load_scheduler_keeps_garanti_sequential() -> None:
    scheduler = AdaptiveAcsScheduler(profile="load", requested_concurrency=8)
    active = 0
    peak = 0

    async def operation() -> AcsBrowserAutomationResult:
        nonlocal active, peak
        active += 1
        peak = max(peak, active)
        await asyncio.sleep(0.01)
        active -= 1
        return _success()

    await asyncio.gather(
        *[
            scheduler.execute("garanti_bankasi_mastercard_6017", operation)
            for _ in range(3)
        ]
    )

    assert peak == 1


@pytest.mark.asyncio
async def test_stable_scheduler_uses_independent_nkolay_and_akbank_pools(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(acs_scheduler, "STABLE_LAUNCH_GAP_SECONDS", 0.0)
    scheduler = AdaptiveAcsScheduler(profile="stable", requested_concurrency=10)

    async def operation() -> AcsBrowserAutomationResult:
        await asyncio.sleep(0.02)
        return _success()

    await asyncio.gather(
        *[
            scheduler.execute("nkolay_dynamic_otp_visa_6111", operation)
            for _ in range(4)
        ],
        *[
            scheduler.execute("akbank_visa_7068", operation)
            for _ in range(2)
        ],
    )

    snapshot = scheduler.snapshot()
    pools = cast(dict[str, dict[str, Any]], snapshot["pools"])
    assert snapshot["peak_concurrency"] == 6
    assert pools["nkolay"]["peak_concurrency"] == 4
    assert pools["akbank"]["peak_concurrency"] == 2


async def _successful_operation() -> AcsBrowserAutomationResult:
    return _success()
