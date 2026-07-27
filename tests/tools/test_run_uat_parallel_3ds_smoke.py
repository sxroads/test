from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

import pytest

from paynkolay_pos.config import TestCard as ConfigTestCard


def _load_uat_parallel_3ds_smoke_module() -> ModuleType:
    script_path = Path(__file__).parents[2] / "tools" / "run_uat_parallel_3ds_smoke.py"
    spec = importlib.util.spec_from_file_location("run_uat_parallel_3ds_smoke", script_path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


UAT_PARALLEL_3DS_SMOKE = _load_uat_parallel_3ds_smoke_module()


def test_parse_manual_cards_builds_repeat_selections() -> None:
    selections = UAT_PARALLEL_3DS_SMOKE._parse_manual_cards(
        (
            "nkolay_dynamic_otp_visa_6111:5",
            "garanti_bankasi_mastercard_6017:5",
        )
    )

    assert selections == [
        {"alias": "nkolay_dynamic_otp_visa_6111", "repeat_count": 5},
        {"alias": "garanti_bankasi_mastercard_6017", "repeat_count": 5},
    ]


def test_parse_manual_cards_rejects_invalid_format() -> None:
    with pytest.raises(SystemExit, match="ALIAS:COUNT"):
        UAT_PARALLEL_3DS_SMOKE._parse_manual_cards(("missing-count",))


def test_select_manual_3ds_cards_validates_aliases_and_flow() -> None:
    selected = UAT_PARALLEL_3DS_SMOKE._select_manual_3ds_cards(
        (
            _card("nkolay_dynamic_otp_visa_6111", requires_3ds=True),
            _card("garanti_bankasi_mastercard_6017", requires_3ds=True),
        ),
        manual_cards=[
            {"alias": "nkolay_dynamic_otp_visa_6111", "repeat_count": 5},
            {"alias": "garanti_bankasi_mastercard_6017", "repeat_count": 5},
        ],
    )

    assert selected == [
        {"alias": "nkolay_dynamic_otp_visa_6111", "repeat_count": 5},
        {"alias": "garanti_bankasi_mastercard_6017", "repeat_count": 5},
    ]


def test_select_manual_3ds_cards_rejects_moto_card() -> None:
    with pytest.raises(SystemExit, match="does not require 3DS"):
        UAT_PARALLEL_3DS_SMOKE._select_manual_3ds_cards(
            (_card("moto_card", requires_3ds=False),),
            manual_cards=[{"alias": "moto_card", "repeat_count": 1}],
        )


def test_parallel_run_request_payload_uses_random_mode() -> None:
    payload = UAT_PARALLEL_3DS_SMOKE._parallel_run_request_payload(
        random_mode=True,
        amount="22.00",
        concurrency=10,
        count=10,
        selected_cards=[],
    )

    assert payload == {
        "mode": "random",
        "amount": "22.00",
        "currency": "TRY",
        "installment_count": 1,
        "concurrency": 10,
        "execution_profile": "stable",
        "auto_complete_3ds": True,
        "random_count": 10,
    }


def test_parallel_run_request_payload_uses_manual_cards() -> None:
    selected_cards = [{"alias": "nkolay_dynamic_otp_visa_6111", "repeat_count": 2}]

    payload = UAT_PARALLEL_3DS_SMOKE._parallel_run_request_payload(
        random_mode=False,
        amount="22.00",
        concurrency=2,
        count=2,
        selected_cards=selected_cards,
    )

    assert payload == {
        "mode": "manual",
        "amount": "22.00",
        "currency": "TRY",
        "installment_count": 1,
        "concurrency": 2,
        "execution_profile": "stable",
        "auto_complete_3ds": True,
        "manual_cards": selected_cards,
    }


def test_parallel_run_request_payload_uses_load_profile_acs_concurrency() -> None:
    selected_cards = [{"alias": "nkolay_dynamic_otp_visa_6111", "repeat_count": 8}]

    payload = UAT_PARALLEL_3DS_SMOKE._parallel_run_request_payload(
        random_mode=False,
        amount="22.00",
        concurrency=10,
        execution_profile="load",
        acs_concurrency=8,
        count=8,
        selected_cards=selected_cards,
    )

    assert payload["execution_profile"] == "load"
    assert payload["acs_concurrency"] == 8


def test_parallel_run_request_payload_uses_installment_count() -> None:
    selected_cards = [{"alias": "nkolay_dynamic_otp_visa_6111", "repeat_count": 2}]

    payload = UAT_PARALLEL_3DS_SMOKE._parallel_run_request_payload(
        random_mode=False,
        amount="1000.00",
        concurrency=2,
        count=2,
        selected_cards=selected_cards,
        installment_count=3,
    )

    assert payload["installment_count"] == 3


def test_progress_summaries_include_card_alias_and_automation_status_counts() -> None:
    run = {
        "items": [
            {
                "card_alias": "nkolay_dynamic_otp_visa_6111",
                "classification": "completed",
                "automation_status": "success_auto",
            },
            {
                "card_alias": "garanti_bankasi_mastercard_6017",
                "classification": "completed",
                "automation_status": "success_auto",
            },
        ]
    }

    assert UAT_PARALLEL_3DS_SMOKE._classification_counts(run) == {"completed": 2}
    assert UAT_PARALLEL_3DS_SMOKE._card_alias_counts(run) == {
        "nkolay_dynamic_otp_visa_6111": 1,
        "garanti_bankasi_mastercard_6017": 1,
    }
    assert UAT_PARALLEL_3DS_SMOKE._automation_status_counts(run) == {"success_auto": 2}


def _card(alias: str, *, requires_3ds: bool) -> ConfigTestCard:
    payload: dict[str, object] = {
        "alias": alias,
        "brand": "visa",
        "pan": "4111111111111111",
        "expiry_month": 12,
        "expiry_year": 2030,
        "cvv": "123",
        "requires_3ds": requires_3ds,
    }
    if requires_3ds:
        payload["expected_otp"] = "123456"
    return ConfigTestCard.model_validate(payload)
