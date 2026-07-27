"""Private runtime config template builder for sandbox preparation."""

from __future__ import annotations

import json
from copy import deepcopy
from typing import Any

from paynkolay_pos.config.settings import CardBrand

REQUIRED_SANDBOX_CARDS: tuple[dict[str, object], ...] = (
    {
        "alias": "visa_3ds_success",
        "brand": "visa",
        "requires_3ds": True,
        "expected_otp": "000000",
    },
    {
        "alias": "visa_installment_success",
        "brand": "visa",
        "requires_3ds": True,
        "expected_otp": "000001",
    },
    {
        "alias": "visa_3ds_declined",
        "brand": "visa",
        "requires_3ds": True,
        "expected_otp": "000002",
    },
    {
        "alias": "visa_moto_success",
        "brand": "visa",
        "requires_3ds": False,
    },
    {
        "alias": "visa_3ds_wrong_otp",
        "brand": "visa",
        "requires_3ds": True,
        "expected_otp": "999999",
    },
    {
        "alias": "visa_insufficient_funds",
        "brand": "visa",
        "requires_3ds": True,
        "expected_otp": "000005",
    },
    {
        "alias": "visa_invalid_cvv",
        "brand": "visa",
        "requires_3ds": True,
        "expected_otp": "000006",
    },
    {
        "alias": "visa_expired_card",
        "brand": "visa",
        "requires_3ds": True,
        "expected_otp": "000007",
    },
    {
        "alias": "visa_debit_3ds_success",
        "brand": "visa",
        "requires_3ds": True,
        "expected_otp": "000008",
    },
    {
        "alias": "visa_credit_3ds_success",
        "brand": "visa",
        "requires_3ds": True,
        "expected_otp": "000009",
    },
)


def build_private_runtime_config_payload(
    *,
    card_count: int = 100,
    profile: str = "mixed",
) -> dict[str, object]:
    """Build a local-only runtime config payload ready for credential replacement."""

    if card_count < len(REQUIRED_SANDBOX_CARDS):
        raise ValueError(
            f"card_count must be at least {len(REQUIRED_SANDBOX_CARDS)} "
            "to include required scenario aliases"
        )

    return {
        "active_environment": "dev",
        "environments": {
            name: _environment_payload(name, offset, card_count=card_count, profile=profile)
            for offset, name in enumerate(("dev", "uat", "test"))
        },
    }


def build_private_runtime_config_json(
    *,
    card_count: int = 100,
    profile: str = "mixed",
) -> str:
    """Build pretty JSON for a private runtime config file."""

    payload = build_private_runtime_config_payload(card_count=card_count, profile=profile)
    return json.dumps(payload, indent=2, ensure_ascii=False)


def _environment_payload(
    name: str,
    environment_index: int,
    *,
    card_count: int,
    profile: str,
) -> dict[str, object]:
    return {
        "name": name,
        "base_url": "https://paynkolaytest.nkolayislem.com.tr/Vpos",
        "callback_base_url": f"https://merchant-{name}.example.test",
        "merchant": {
            "merchant_id": f"replace-with-{name}-merchant-id",
            "terminal_id": f"replace-with-{name}-terminal-id",
            "api_key": f"replace-with-{name}-payment-sx",
            "installment_api_key": f"replace-with-{name}-installment-sx",
            "list_api_key": f"replace-with-{name}-list-sx",
            "cancel_refund_api_key": f"replace-with-{name}-cancel-refund-sx-if-different",
            "secret_key": f"replace-with-{name}-merchant-secret-key",
        },
        "cards": _cards(environment_index, card_count=card_count, profile=profile),
    }


def _cards(
    environment_index: int,
    *,
    card_count: int,
    profile: str,
) -> list[dict[str, object]]:
    required_cards = [
        _required_card_payload(card, card_index=index, environment_index=environment_index)
        for index, card in enumerate(REQUIRED_SANDBOX_CARDS)
    ]
    filler_count = card_count - len(required_cards)
    filler_cards = _synthetic_card_payloads(
        filler_count,
        alias_prefix=f"synthetic_env{environment_index + 1}_card",
        profile=profile,
        start_index=len(required_cards),
    )
    return required_cards + filler_cards


def _required_card_payload(
    card: dict[str, object],
    *,
    card_index: int,
    environment_index: int,
) -> dict[str, object]:
    payload: dict[str, Any] = deepcopy(card)
    numeric_offset = (environment_index * 1000) + card_index
    payload.update(
        {
            "pan": f"{numeric_offset:016d}",
            "expiry_month": 12,
            "expiry_year": 2030,
            "cvv": f"{numeric_offset % 1000:03d}",
        }
    )
    return payload


def _synthetic_card_payloads(
    count: int,
    *,
    alias_prefix: str,
    profile: str,
    start_index: int,
) -> list[dict[str, object]]:
    normalized_profile = profile.strip().lower()
    if normalized_profile not in {"mixed", "three_ds", "moto"}:
        raise ValueError("profile must be one of: mixed, three_ds, moto")

    cards: list[dict[str, object]] = []
    for index in range(count):
        absolute_index = start_index + index
        requires_3ds = _requires_3ds(index, normalized_profile)
        card: dict[str, object] = {
            "alias": f"{alias_prefix}_{index + 1:04d}",
            "brand": _brand(absolute_index).value,
            "pan": f"{absolute_index:016d}",
            "expiry_month": (absolute_index % 12) + 1,
            "expiry_year": 2030 + (absolute_index % 5),
            "cvv": f"{absolute_index % 1000:03d}",
            "requires_3ds": requires_3ds,
        }
        if requires_3ds:
            card["expected_otp"] = f"{absolute_index % 1000000:06d}"
        cards.append(card)
    return cards


def _requires_3ds(index: int, profile: str) -> bool:
    if profile == "three_ds":
        return True
    if profile == "moto":
        return False
    return index % 2 == 0


def _brand(index: int) -> CardBrand:
    brands = (CardBrand.VISA, CardBrand.MASTERCARD, CardBrand.TROY)
    return brands[index % len(brands)]
