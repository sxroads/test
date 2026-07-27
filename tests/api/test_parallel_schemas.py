from __future__ import annotations

import pytest
from pydantic import ValidationError

from paynkolay_pos.api.schemas import ParallelRunCreateRequest


def test_parallel_request_defaults_to_stable_profile() -> None:
    request = ParallelRunCreateRequest.model_validate(
        {
            "mode": "manual",
            "amount": "100.00",
            "concurrency": 10,
            "manual_cards": [{"alias": "nkolay_dynamic_otp_visa_6111", "repeat_count": 20}],
        }
    )

    assert request.execution_profile == "stable"
    assert request.effective_acs_concurrency == 10
    assert request.installment_count == 1


def test_parallel_request_accepts_run_level_installment_count() -> None:
    request = ParallelRunCreateRequest.model_validate(
        {
            "mode": "manual",
            "amount": "1000.00",
            "installment_count": 12,
            "manual_cards": [
                {"alias": "nkolay_dynamic_otp_visa_6111", "repeat_count": 2}
            ],
        }
    )

    assert request.installment_count == 12


def test_parallel_request_rejects_manual_acs_limit_in_stable_profile() -> None:
    with pytest.raises(
        ValidationError,
        match="stable profile manages acs_concurrency automatically",
    ):
        ParallelRunCreateRequest.model_validate(
            {
                "mode": "manual",
                "amount": "100.00",
                "execution_profile": "stable",
                "concurrency": 10,
                "acs_concurrency": 8,
                "manual_cards": [
                    {"alias": "nkolay_dynamic_otp_visa_6111", "repeat_count": 20}
                ],
            }
        )


def test_parallel_request_load_profile_defaults_acs_limit_to_run_concurrency() -> None:
    request = ParallelRunCreateRequest.model_validate(
        {
            "mode": "manual",
            "amount": "100.00",
            "execution_profile": "load",
            "concurrency": 20,
            "manual_cards": [{"alias": "akbank_visa_7068", "repeat_count": 20}],
        }
    )

    assert request.effective_acs_concurrency == 20
