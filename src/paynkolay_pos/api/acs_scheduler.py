"""Adaptive concurrency control for parallel ACS browser automation."""

from __future__ import annotations

import asyncio
import math
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Literal

from paynkolay_pos.three_ds import AcsBrowserAutomationResult

ExecutionProfile = Literal["stable", "load"]
STABLE_LAUNCH_GAP_SECONDS = 0.25
STABLE_SUCCESS_RAMP_WINDOW = 4
STABLE_FAILURE_COOLDOWN_SECONDS = 2.0


@dataclass(frozen=True)
class AcsPoolPolicy:
    """Stable concurrency policy for one ACS/provider lane."""

    group: str
    initial_limit: int
    maximum_limit: int
    fixed: bool = False


@dataclass
class _AcsPoolState:
    policy: AcsPoolPolicy
    limit: int
    active: int = 0
    peak_active: int = 0
    consecutive_successes: int = 0
    next_start_at: float = 0.0
    cooldown_until: float = 0.0


@dataclass(frozen=True)
class AcsExecution:
    """One scheduled ACS execution with queue and browser timings."""

    result: AcsBrowserAutomationResult
    wait_ms: int
    duration_ms: int


class AdaptiveAcsScheduler:
    """Run ACS work through stable adaptive or direct load-test limits."""

    def __init__(
        self,
        *,
        profile: ExecutionProfile,
        requested_concurrency: int,
        clock: Callable[[], float] = time.monotonic,
        async_sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self.profile = profile
        self.requested_concurrency = requested_concurrency
        self._clock = clock
        self._sleep = async_sleep
        self._condition = asyncio.Condition()
        self._pools: dict[str, _AcsPoolState] = {}
        self._active = 0
        self._peak_active = 0

    async def execute(
        self,
        card_alias: str,
        operation: Callable[[], Awaitable[AcsBrowserAutomationResult]],
    ) -> AcsExecution:
        """Wait for an ACS slot, execute the browser operation, and update capacity."""

        queued_at = self._clock()
        state = await self._acquire(card_alias)
        started_at = self._clock()
        try:
            result = await operation()
        except BaseException:
            await self._release(state, result=None)
            raise
        finished_at = self._clock()
        await self._release(state, result=result)
        return AcsExecution(
            result=result,
            wait_ms=_milliseconds(started_at - queued_at),
            duration_ms=_milliseconds(finished_at - started_at),
        )

    def snapshot(self) -> dict[str, object]:
        """Return serializable scheduler metrics for API and evidence output."""

        return {
            "profile": self.profile,
            "requested_concurrency": self.requested_concurrency,
            "peak_concurrency": self._peak_active,
            "pools": {
                name: {
                    "initial_limit": state.policy.initial_limit,
                    "final_limit": state.limit,
                    "maximum_limit": state.policy.maximum_limit,
                    "peak_concurrency": state.peak_active,
                }
                for name, state in sorted(self._pools.items())
            },
        }

    async def _acquire(self, card_alias: str) -> _AcsPoolState:
        state = self._pool(card_alias)
        launch_gap = STABLE_LAUNCH_GAP_SECONDS if self.profile == "stable" else 0.0
        while True:
            delay = 0.01
            async with self._condition:
                now = self._clock()
                capacity_available = (
                    self._active < self.requested_concurrency
                    and state.active < state.limit
                    and now >= state.cooldown_until
                )
                if capacity_available and now >= state.next_start_at:
                    self._active += 1
                    state.active += 1
                    self._peak_active = max(self._peak_active, self._active)
                    state.peak_active = max(state.peak_active, state.active)
                    state.next_start_at = now + launch_gap
                    return state
                waits = [
                    timestamp - now
                    for timestamp in (state.next_start_at, state.cooldown_until)
                    if timestamp > now
                ]
                if waits:
                    delay = min(waits)
            await self._sleep(max(0.01, delay))

    async def _release(
        self,
        state: _AcsPoolState,
        *,
        result: AcsBrowserAutomationResult | None,
    ) -> None:
        async with self._condition:
            self._active -= 1
            state.active -= 1
            if self.profile == "stable" and not state.policy.fixed:
                self._adapt(state, result=result)
            self._condition.notify_all()

    def _adapt(
        self,
        state: _AcsPoolState,
        *,
        result: AcsBrowserAutomationResult | None,
    ) -> None:
        if result is not None and result.completed and result.submitted:
            state.consecutive_successes += 1
            if state.consecutive_successes >= STABLE_SUCCESS_RAMP_WINDOW:
                state.limit = min(state.limit + 1, state.policy.maximum_limit)
                state.consecutive_successes = 0
            return

        state.consecutive_successes = 0
        if result is None or _is_transient_browser_failure(result):
            state.limit = max(1, math.ceil(state.limit / 2))
            state.cooldown_until = self._clock() + STABLE_FAILURE_COOLDOWN_SECONDS

    def _pool(self, card_alias: str) -> _AcsPoolState:
        policy = _stable_policy_for_alias(card_alias)
        state = self._pools.get(policy.group)
        if state is not None:
            return state
        if self.profile == "load" and not policy.fixed:
            policy = AcsPoolPolicy(
                group=policy.group,
                initial_limit=self.requested_concurrency,
                maximum_limit=self.requested_concurrency,
            )
        state = _AcsPoolState(policy=policy, limit=policy.initial_limit)
        self._pools[policy.group] = state
        return state


def _stable_policy_for_alias(card_alias: str) -> AcsPoolPolicy:
    if card_alias == "nkolay_dynamic_otp_visa_6111":
        return AcsPoolPolicy("nkolay", initial_limit=4, maximum_limit=10)
    if card_alias == "akbank_visa_7068":
        return AcsPoolPolicy("akbank", initial_limit=2, maximum_limit=6)
    if card_alias == "garanti_bankasi_mastercard_6017":
        return AcsPoolPolicy("garanti", initial_limit=1, maximum_limit=1, fixed=True)
    return AcsPoolPolicy(f"card:{card_alias}", initial_limit=2, maximum_limit=4)


def _is_transient_browser_failure(result: AcsBrowserAutomationResult) -> bool:
    return (
        result.screen_classification == "blank_or_redirect_error"
        or (result.final_url or "").startswith("chrome-error://")
        or result.reason.startswith("playwright_error:")
    )


def _milliseconds(seconds: float) -> int:
    return max(0, int(seconds * 1000))
