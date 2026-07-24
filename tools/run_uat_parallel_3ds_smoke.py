"""Run a guarded Paynkolay UAT parallel auto-3DS smoke through the web API."""

from __future__ import annotations

import argparse
import asyncio
import os
from collections.abc import Sequence
from typing import Any, TypedDict, cast

import httpx

from paynkolay_pos.api.app import create_app
from paynkolay_pos.config import TestCard, load_runtime_settings
from paynkolay_pos.reporting import evidence_json

DEFAULT_CARD_ALIAS = "nkolay_dynamic_otp_visa_6111"


class ManualCardSelection(TypedDict):
    alias: str
    repeat_count: int


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run a guarded UAT parallel auto-3DS smoke via FastAPI routes.",
    )
    parser.add_argument(
        "--card-alias",
        default=DEFAULT_CARD_ALIAS,
        help=(
            "3DS card alias to run. Defaults to the known dynamic OTP Visa/QNB card; "
            "falls back to the first configured 3DS card when the default is absent."
        ),
    )
    parser.add_argument(
        "--manual-card",
        action="append",
        default=[],
        metavar="ALIAS:COUNT",
        help=(
            "Manual card selection for mixed parallel runs. Can be repeated, for example "
            "--manual-card nkolay_dynamic_otp_visa_6111:5 "
            "--manual-card garanti_bankasi_mastercard_6017:5. "
            "When provided, --card-alias and --count are ignored."
        ),
    )
    parser.add_argument(
        "--random",
        action="store_true",
        help="Use the API random mode instead of manual card selection.",
    )
    parser.add_argument(
        "--count",
        type=int,
        default=10,
        help="Number of repeated attempts for the selected card. Max 150.",
    )
    parser.add_argument(
        "--concurrency",
        type=int,
        default=10,
        help="Parallel run concurrency. Max 150.",
    )
    parser.add_argument(
        "--profile",
        choices=("stable", "load"),
        default="stable",
        help="Stable adaptive scheduling or direct load-test concurrency.",
    )
    parser.add_argument(
        "--acs-concurrency",
        type=int,
        default=None,
        help="ACS browser concurrency for --profile load. Defaults to --concurrency.",
    )
    parser.add_argument(
        "--amount",
        default="100.00",
        help="Payment amount used for every item.",
    )
    parser.add_argument(
        "--poll-interval",
        type=float,
        default=1.0,
        help="Seconds between run status polls.",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=180.0,
        help="Maximum seconds to wait for the run to finish.",
    )
    parser.add_argument(
        "--allow-attention",
        action="store_true",
        help=(
            "Exit successfully for completed_with_failures runs. Useful for diagnostic mixed "
            "runs where awaiting_provider_finalization is expected."
        ),
    )
    args = parser.parse_args()

    manual_cards = _parse_manual_cards(args.manual_card)
    total_count = sum(item["repeat_count"] for item in manual_cards) if manual_cards else args.count

    if args.random and manual_cards:
        raise SystemExit("--random cannot be combined with --manual-card.")
    if os.getenv("PAYNKOLAY_ENABLE_LIVE_E2E") != "1":
        raise SystemExit("Set PAYNKOLAY_ENABLE_LIVE_E2E=1 before real UAT calls.")
    if total_count < 1 or total_count > 150:
        raise SystemExit("total item count must be between 1 and 150.")
    if args.concurrency < 1 or args.concurrency > 150:
        raise SystemExit("--concurrency must be between 1 and 150.")
    if args.acs_concurrency is not None and args.profile != "load":
        raise SystemExit("--acs-concurrency requires --profile load.")
    if args.acs_concurrency is not None and not 1 <= args.acs_concurrency <= 150:
        raise SystemExit("--acs-concurrency must be between 1 and 150.")

    asyncio.run(
        _run_parallel_smoke(
            requested_card_alias=args.card_alias,
            count=total_count,
            concurrency=args.concurrency,
            execution_profile=args.profile,
            acs_concurrency=args.acs_concurrency,
            amount=args.amount,
            poll_interval=args.poll_interval,
            timeout=args.timeout,
            manual_cards=manual_cards,
            allow_attention=args.allow_attention,
            random_mode=args.random,
        )
    )


async def _run_parallel_smoke(
    *,
    requested_card_alias: str,
    count: int,
    concurrency: int,
    execution_profile: str,
    acs_concurrency: int | None,
    amount: str,
    poll_interval: float,
    timeout: float,
    manual_cards: list[ManualCardSelection],
    allow_attention: bool,
    random_mode: bool,
) -> None:
    settings = load_runtime_settings()
    selected_cards: list[ManualCardSelection]
    if random_mode:
        selected_cards = []
    elif manual_cards:
        selected_cards = _select_manual_3ds_cards(
            settings.current.cards,
            manual_cards=manual_cards,
        )
    else:
        selected_cards = [
            {
                "alias": _select_3ds_card(
                    settings.current.cards,
                    requested_card_alias=requested_card_alias,
                ).alias,
                "repeat_count": count,
            }
        ]
    print(
        evidence_json(
            {
                "event": "uat_parallel_3ds_smoke_start",
                "environment": settings.current.name.value,
                "provider_base_url": settings.current.base_url,
                "callback_url": settings.current.callback_base_url,
                "requested_card_alias": requested_card_alias,
                "selected_cards": selected_cards,
                "count": count,
                "concurrency": concurrency,
                "execution_profile": execution_profile,
                "acs_concurrency": acs_concurrency,
                "amount": amount,
                "auto_complete_3ds": True,
                "mode": "random" if random_mode else "manual",
            }
        )
    )

    app = create_app()
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport,
        base_url="http://testserver",
        timeout=timeout + 30.0,
    ) as client:
        response = await client.post(
            "/api/parallel-runs",
            json=_parallel_run_request_payload(
                random_mode=random_mode,
                amount=amount,
                concurrency=concurrency,
                execution_profile=execution_profile,
                acs_concurrency=acs_concurrency,
                count=count,
                selected_cards=selected_cards,
            ),
        )
        if response.status_code != httpx.codes.ACCEPTED:
            print(
                evidence_json(
                    {
                        "event": "uat_parallel_3ds_smoke_start_failed",
                        "status_code": response.status_code,
                        "response": _safe_json(response),
                    }
                )
            )
            raise SystemExit(1)

        run = response.json()
        print(
            evidence_json(
                {
                    "event": "uat_parallel_3ds_smoke_started",
                    "run_id": run["run_id"],
                    "status": run["status"],
                    "total": run["total"],
                }
            )
        )
        final_run = await _poll_run(
            client=client,
            run_id=str(run["run_id"]),
            poll_interval=poll_interval,
            timeout=timeout,
        )

    print(evidence_json({"event": "uat_parallel_3ds_smoke_finished", "run": final_run}))
    if final_run["status"] == "completed":
        return
    if allow_attention and final_run["status"] == "completed_with_failures":
        return
    if final_run["status"] != "completed":
        raise SystemExit(1)


def _parallel_run_request_payload(
    *,
    random_mode: bool,
    amount: str,
    concurrency: int,
    execution_profile: str = "stable",
    acs_concurrency: int | None = None,
    count: int,
    selected_cards: list[ManualCardSelection],
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "mode": "random" if random_mode else "manual",
        "amount": amount,
        "currency": "TRY",
        "concurrency": concurrency,
        "execution_profile": execution_profile,
        "auto_complete_3ds": True,
    }
    if execution_profile == "load":
        payload["acs_concurrency"] = acs_concurrency or concurrency
    if random_mode:
        payload["random_count"] = count
    else:
        payload["manual_cards"] = selected_cards
    return payload


async def _poll_run(
    *,
    client: httpx.AsyncClient,
    run_id: str,
    poll_interval: float,
    timeout: float,
) -> dict[str, Any]:
    deadline = asyncio.get_running_loop().time() + timeout
    last_payload: dict[str, Any] | None = None
    while asyncio.get_running_loop().time() < deadline:
        response = await client.get(f"/api/parallel-runs/{run_id}")
        if response.status_code != httpx.codes.OK:
            print(
                evidence_json(
                    {
                        "event": "uat_parallel_3ds_smoke_poll_failed",
                        "run_id": run_id,
                        "status_code": response.status_code,
                        "response": _safe_json(response),
                    }
                )
            )
            raise SystemExit(1)
        payload = cast(dict[str, Any], response.json())
        last_payload = payload
        print(
            evidence_json(
                {
                    "event": "uat_parallel_3ds_smoke_progress",
                    "run_id": run_id,
                    "status": payload["status"],
                    "completed": payload["completed"],
                    "failed": payload["failed"],
                    "total": payload["total"],
                    "classifications": _classification_counts(payload),
                    "card_aliases": _card_alias_counts(payload),
                    "automation_statuses": _automation_status_counts(payload),
                }
            )
        )
        if payload["status"] != "running":
            return payload
        await asyncio.sleep(poll_interval)

    print(
        evidence_json(
            {
                "event": "uat_parallel_3ds_smoke_timeout",
                "run_id": run_id,
                "last_run": last_payload,
            }
        )
    )
    raise SystemExit(1)


def _select_3ds_card(
    cards: Sequence[TestCard],
    *,
    requested_card_alias: str,
) -> TestCard:
    for card in cards:
        if card.alias == requested_card_alias:
            if not card.requires_3ds:
                raise SystemExit(f"Selected card does not require 3DS: {requested_card_alias}")
            return card
    if requested_card_alias != DEFAULT_CARD_ALIAS:
        raise SystemExit(f"3DS card alias is not configured: {requested_card_alias}")
    for card in cards:
        if card.requires_3ds:
            return card
    raise SystemExit("No configured 3DS card was found.")


def _select_manual_3ds_cards(
    cards: Sequence[TestCard],
    *,
    manual_cards: list[ManualCardSelection],
) -> list[ManualCardSelection]:
    cards_by_alias = {card.alias: card for card in cards}
    selected: list[ManualCardSelection] = []
    for item in manual_cards:
        alias = item["alias"]
        repeat_count = item["repeat_count"]
        card = cards_by_alias.get(alias)
        if card is None:
            raise SystemExit(f"3DS card alias is not configured: {alias}")
        if not card.requires_3ds:
            raise SystemExit(f"Selected card does not require 3DS: {alias}")
        selected.append({"alias": alias, "repeat_count": repeat_count})
    return selected


def _parse_manual_cards(values: Sequence[str]) -> list[ManualCardSelection]:
    selections: list[ManualCardSelection] = []
    for value in values:
        alias, separator, count_value = value.partition(":")
        if not separator or not alias.strip() or not count_value.strip():
            raise SystemExit("--manual-card must use ALIAS:COUNT format.")
        try:
            repeat_count = int(count_value)
        except ValueError as exc:
            raise SystemExit("--manual-card COUNT must be an integer.") from exc
        if repeat_count < 1 or repeat_count > 150:
            raise SystemExit("--manual-card COUNT must be between 1 and 150.")
        selections.append({"alias": alias.strip(), "repeat_count": repeat_count})
    return selections


def _classification_counts(run: dict[str, Any]) -> dict[str, int]:
    return _item_value_counts(run, "classification", default="unknown")


def _card_alias_counts(run: dict[str, Any]) -> dict[str, int]:
    return _item_value_counts(run, "card_alias", default="unknown")


def _automation_status_counts(run: dict[str, Any]) -> dict[str, int]:
    return _item_value_counts(run, "automation_status", default="unknown")


def _item_value_counts(
    run: dict[str, Any],
    key: str,
    *,
    default: str,
) -> dict[str, int]:
    counts: dict[str, int] = {}
    for item in run.get("items", []):
        if not isinstance(item, dict):
            continue
        value = str(item.get(key) or default)
        counts[value] = counts.get(value, 0) + 1
    return counts


def _safe_json(response: httpx.Response) -> object:
    try:
        return response.json()
    except ValueError:
        return response.text[:500]


if __name__ == "__main__":
    main()
