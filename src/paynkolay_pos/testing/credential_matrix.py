"""Build UAT/local test matrices from externally supplied credential CSV files."""

from __future__ import annotations

import csv
import json
import re
import unicodedata
from collections.abc import Callable
from dataclasses import asdict, dataclass
from html.parser import HTMLParser
from pathlib import Path

from paynkolay_pos.config import RuntimeSettings
from paynkolay_pos.scenarios import PaymentScenarioCatalog
from paynkolay_pos.testing.synthetic_cards import (
    SyntheticCardProfile,
    generate_synthetic_card_payloads,
)


@dataclass(frozen=True)
class CredentialCardMatrixItem:
    """One normalized card row for local/mock scenario planning."""

    alias: str
    source: str
    bank_name: str
    brand: str
    card_type: str
    pan: str
    expiry_month: int
    expiry_year: int
    cvv: str
    requires_3ds: bool
    expected_otp: str | None
    recommended_scenarios: tuple[str, ...]


@dataclass(frozen=True)
class CredentialErrorMatrixItem:
    """One normalized error row for local/mock negative scenario planning."""

    scenario_id: str
    cvv: str
    expected_error_code: str
    expected_error_message: str
    input_condition: str


@dataclass(frozen=True)
class PaynkolayUATCredentialValues:
    """UAT credential values extracted from ignored Paynkolay artifacts."""

    payment_sx: str | None = None
    installment_sx: str | None = None
    list_sx: str | None = None
    cancel_refund_sx: str | None = None
    secret_key: str | None = None
    merchant_id: str | None = None
    terminal_id: str | None = None


class _HiddenInputParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.inputs: dict[str, str] = {}

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() != "input":
            return
        attributes = {key.lower(): value or "" for key, value in attrs}
        name = attributes.get("name") or attributes.get("id")
        if name:
            self.inputs[name] = attributes.get("value", "")


def extract_paynkolay_uat_values(
    *,
    postman_collection_path: Path | None = None,
    gateway_form_path: Path | None = None,
    installment_service_path: Path | None = None,
) -> PaynkolayUATCredentialValues:
    """Extract UAT credential defaults from ignored Paynkolay/Postman files."""

    postman_values = (
        _read_postman_collection_variables(postman_collection_path)
        if postman_collection_path is not None and postman_collection_path.is_file()
        else {}
    )
    gateway_values = (
        _read_gateway_form_inputs(gateway_form_path)
        if gateway_form_path is not None and gateway_form_path.is_file()
        else {}
    )
    installment_sx = (
        _read_installment_service_sx(installment_service_path)
        if installment_service_path is not None and installment_service_path.is_file()
        else None
    )
    return PaynkolayUATCredentialValues(
        payment_sx=_non_empty(postman_values.get("sx")),
        installment_sx=installment_sx,
        list_sx=_non_empty(postman_values.get("sx-list")),
        cancel_refund_sx=_non_empty(postman_values.get("sx-cancel")),
        secret_key=_non_empty(postman_values.get("merchantSecretKey")),
        merchant_id=_non_empty(gateway_values.get("SUBMERCHANTID")),
        terminal_id=_non_empty(gateway_values.get("clientid")),
    )


def build_credential_matrix_payload(
    *,
    param_cards_path: Path | None = None,
    paynkolay_cards_path: Path | None = None,
    error_codes_path: Path | None = None,
    total_card_count: int | None = None,
) -> dict[str, object]:
    """Build a normalized matrix payload from available local credential files."""

    cards: list[CredentialCardMatrixItem] = []
    if param_cards_path is not None and param_cards_path.is_file():
        cards.extend(_read_param_cards(param_cards_path))
    if paynkolay_cards_path is not None and paynkolay_cards_path.is_file():
        cards.extend(_read_paynkolay_cards(paynkolay_cards_path))
    if total_card_count is not None:
        _append_synthetic_fillers(cards, total_card_count=total_card_count)

    errors: list[CredentialErrorMatrixItem] = []
    if error_codes_path is not None and error_codes_path.is_file():
        errors.extend(_read_error_codes(error_codes_path))

    return {
        "summary": {
            "card_count": len(cards),
            "three_ds_card_count": sum(1 for card in cards if card.requires_3ds),
            "moto_candidate_count": sum(1 for card in cards if not card.requires_3ds),
            "error_case_count": len(errors),
            "brands": sorted({card.brand for card in cards}),
            "card_types": sorted({card.card_type for card in cards}),
        },
        "cards": [asdict(card) for card in cards],
        "errors": [asdict(error) for error in errors],
    }


def build_credential_matrix_json(
    *,
    param_cards_path: Path | None = None,
    paynkolay_cards_path: Path | None = None,
    error_codes_path: Path | None = None,
    total_card_count: int | None = None,
) -> str:
    """Build pretty JSON for the local/mock credential matrix."""

    payload = build_credential_matrix_payload(
        param_cards_path=param_cards_path,
        paynkolay_cards_path=paynkolay_cards_path,
        error_codes_path=error_codes_path,
        total_card_count=total_card_count,
    )
    return json.dumps(payload, indent=2, ensure_ascii=False)


def build_credential_scenario_catalog_payload(
    *,
    param_cards_path: Path | None = None,
    paynkolay_cards_path: Path | None = None,
    error_codes_path: Path | None = None,
    total_card_count: int | None = None,
) -> dict[str, object]:
    """Build executable local/mock scenarios from credential CSV files."""

    matrix = build_credential_matrix_payload(
        param_cards_path=param_cards_path,
        paynkolay_cards_path=paynkolay_cards_path,
        error_codes_path=error_codes_path,
        total_card_count=total_card_count,
    )
    cards = matrix["cards"]
    errors = matrix["errors"]
    if not isinstance(cards, list) or not isinstance(errors, list):
        raise TypeError("credential matrix payload is invalid")

    scenarios: list[dict[str, object]] = []
    for index, card in enumerate(cards, start=1):
        if not isinstance(card, dict):
            raise TypeError("credential matrix card item is invalid")
        scenarios.extend(_card_scenarios(card, index=index))

    error_card = _first_card(cards)
    for index, error in enumerate(errors, start=1):
        if not isinstance(error, dict):
            raise TypeError("credential matrix error item is invalid")
        scenarios.append(_error_scenario(error, error_card=error_card, index=index))

    _append_uat_coverage_scenarios(scenarios, cards)

    payload: dict[str, object] = {"scenarios": scenarios}
    PaymentScenarioCatalog.model_validate(payload)
    return payload


def build_credential_scenario_catalog_json(
    *,
    param_cards_path: Path | None = None,
    paynkolay_cards_path: Path | None = None,
    error_codes_path: Path | None = None,
    total_card_count: int | None = None,
) -> str:
    """Build pretty JSON for credential-driven local/mock scenarios."""

    payload = build_credential_scenario_catalog_payload(
        param_cards_path=param_cards_path,
        paynkolay_cards_path=paynkolay_cards_path,
        error_codes_path=error_codes_path,
        total_card_count=total_card_count,
    )
    return json.dumps(payload, indent=2, ensure_ascii=False)


def build_credential_runtime_config_payload(
    *,
    param_cards_path: Path | None = None,
    paynkolay_cards_path: Path | None = None,
    total_card_count: int | None = None,
    postman_collection_path: Path | None = None,
    gateway_form_path: Path | None = None,
    installment_service_path: Path | None = None,
    active_environment: str = "dev",
    base_url: str = "https://local-mock.payments.invalid",
    callback_base_url: str = "https://local-mock.callbacks.invalid",
    merchant_id: str = "local-mock-merchant",
    terminal_id: str = "local-mock-terminal",
    api_key: str = "local-mock-payment-key",
    installment_api_key: str = "local-mock-installment-key",
    list_api_key: str = "local-mock-list-key",
    cancel_refund_api_key: str = "local-mock-cancel-refund-key",
    secret_key: str = "local-mock-secret-key",
) -> dict[str, object]:
    """Build a runtime config from credential card CSV files.

    Defaults preserve the original local/mock behavior. Callers can pass UAT endpoint,
    merchant, and callback values to create a private UAT-ready config without copying
    credential values into the repository.
    """

    matrix = build_credential_matrix_payload(
        param_cards_path=param_cards_path,
        paynkolay_cards_path=paynkolay_cards_path,
        total_card_count=total_card_count,
    )
    cards = matrix["cards"]
    if not isinstance(cards, list) or not cards:
        raise ValueError("at least one credential card is required to build runtime config")

    normalized_environment = active_environment.strip().lower()
    if normalized_environment == "uat":
        uat_values = extract_paynkolay_uat_values(
            postman_collection_path=postman_collection_path,
            gateway_form_path=gateway_form_path,
            installment_service_path=installment_service_path,
        )
        merchant_id = _fallback_placeholder(merchant_id, uat_values.merchant_id)
        terminal_id = _fallback_placeholder(terminal_id, uat_values.terminal_id)
        api_key = _fallback_placeholder(api_key, uat_values.payment_sx)
        installment_api_key = _fallback_placeholder(
            installment_api_key,
            uat_values.installment_sx,
        )
        list_api_key = _fallback_placeholder(list_api_key, uat_values.list_sx)
        cancel_refund_api_key = _fallback_placeholder(
            cancel_refund_api_key,
            uat_values.cancel_refund_sx,
        )
        secret_key = _fallback_placeholder(secret_key, uat_values.secret_key)

    payload: dict[str, object] = {
        "active_environment": normalized_environment,
        "environments": {
            normalized_environment: {
                "name": normalized_environment,
                "base_url": base_url,
                "callback_base_url": callback_base_url,
                "merchant": {
                    "merchant_id": merchant_id,
                    "terminal_id": terminal_id,
                    "api_key": api_key,
                    "installment_api_key": installment_api_key,
                    "list_api_key": list_api_key,
                    "cancel_refund_api_key": cancel_refund_api_key,
                    "secret_key": secret_key,
                },
                "cards": [_runtime_card_payload(card) for card in cards],
            }
        },
    }
    RuntimeSettings.model_validate(payload)
    return payload


def build_credential_runtime_config_json(
    *,
    param_cards_path: Path | None = None,
    paynkolay_cards_path: Path | None = None,
    total_card_count: int | None = None,
    postman_collection_path: Path | None = None,
    gateway_form_path: Path | None = None,
    installment_service_path: Path | None = None,
    active_environment: str = "dev",
    base_url: str = "https://local-mock.payments.invalid",
    callback_base_url: str = "https://local-mock.callbacks.invalid",
    merchant_id: str = "local-mock-merchant",
    terminal_id: str = "local-mock-terminal",
    api_key: str = "local-mock-payment-key",
    installment_api_key: str = "local-mock-installment-key",
    list_api_key: str = "local-mock-list-key",
    cancel_refund_api_key: str = "local-mock-cancel-refund-key",
    secret_key: str = "local-mock-secret-key",
) -> str:
    """Build pretty JSON for a runtime config from credential cards."""

    payload = build_credential_runtime_config_payload(
        param_cards_path=param_cards_path,
        paynkolay_cards_path=paynkolay_cards_path,
        total_card_count=total_card_count,
        postman_collection_path=postman_collection_path,
        gateway_form_path=gateway_form_path,
        installment_service_path=installment_service_path,
        active_environment=active_environment,
        base_url=base_url,
        callback_base_url=callback_base_url,
        merchant_id=merchant_id,
        terminal_id=terminal_id,
        api_key=api_key,
        installment_api_key=installment_api_key,
        list_api_key=list_api_key,
        cancel_refund_api_key=cancel_refund_api_key,
        secret_key=secret_key,
    )
    return json.dumps(payload, indent=2, ensure_ascii=False)


def _read_param_cards(path: Path) -> list[CredentialCardMatrixItem]:
    rows = _read_csv(path)
    cards: list[CredentialCardMatrixItem] = []
    for index, row in enumerate(rows, start=1):
        card_type_text = _value(row, "Kart Tipi")
        pan = _digits(_value(row, "Kart Numarasi"))
        month, year = _parse_expiry(_value(row, "Son Kullanma Tarihi"))
        otp = _extract_otp(card_type_text)
        requires_3ds = bool(otp) or "3ds" in card_type_text.lower()
        cards.append(
            _card_item(
                source=path.name,
                index=index,
                bank_name=_value(row, "Banka"),
                brand=_infer_brand(card_type_text),
                card_type=_infer_card_type(card_type_text),
                pan=pan,
                expiry_month=month,
                expiry_year=year,
                cvv=_digits(_value(row, "Guvenlik Numarasi (CVV)")),
                requires_3ds=requires_3ds,
                expected_otp=otp,
            )
        )
    return cards


def _append_synthetic_fillers(
    cards: list[CredentialCardMatrixItem],
    *,
    total_card_count: int,
) -> None:
    if total_card_count < 1:
        raise ValueError("total_card_count must be greater than zero")
    if total_card_count < len(cards):
        raise ValueError(
            f"total_card_count ({total_card_count}) is smaller than credential "
            f"card count ({len(cards)})"
        )

    filler_count = total_card_count - len(cards)
    if filler_count == 0:
        return

    for card in generate_synthetic_card_payloads(
        filler_count,
        alias_prefix="synthetic_filler",
        profile=SyntheticCardProfile.MOTO,
    ):
        expiry_month = card["expiry_month"]
        expiry_year = card["expiry_year"]
        if not isinstance(expiry_month, int) or not isinstance(expiry_year, int):
            raise TypeError("synthetic filler expiry values must be integers")
        cards.append(
            CredentialCardMatrixItem(
                alias=str(card["alias"]),
                source="synthetic_filler",
                bank_name="Synthetic Filler",
                brand=str(card["brand"]),
                card_type="credit",
                pan=str(card["pan"]),
                expiry_month=expiry_month,
                expiry_year=expiry_year,
                cvv=str(card["cvv"]),
                requires_3ds=False,
                expected_otp=None,
                recommended_scenarios=("moto_authorized", "credit_coverage"),
            )
        )


def _runtime_card_payload(card: object) -> dict[str, object]:
    if not isinstance(card, dict):
        raise TypeError("credential matrix card item is invalid")

    payload: dict[str, object] = {
        "alias": str(card["alias"]),
        "brand": str(card["brand"]),
        "pan": str(card["pan"]),
        "expiry_month": int(card["expiry_month"]),
        "expiry_year": int(card["expiry_year"]),
        "cvv": str(card["cvv"]),
        "requires_3ds": bool(card["requires_3ds"]),
    }
    expected_otp = card.get("expected_otp")
    if expected_otp is not None:
        payload["expected_otp"] = str(expected_otp)
    return payload


def _card_scenarios(card: dict[str, object], *, index: int) -> list[dict[str, object]]:
    alias = str(card["alias"])
    requires_3ds = bool(card["requires_3ds"])
    card_type = str(card["card_type"])
    scenarios: list[dict[str, object]] = []
    if requires_3ds:
        scenarios.append(
            _scenario_payload(
                scenario_id=f"credential_{alias}_3ds_success",
                title=f"Credential {alias} 3DS success",
                card_alias=alias,
                amount=_amount(index),
                requires_3ds=True,
                expected_initialize_status="pending_3ds",
                expected_final_status="captured",
                installment_count=1,
                payment_channel="e_commerce",
                moto=False,
                tags=["credential", "local_mock", "three_ds", card_type],
            )
        )
    else:
        scenarios.append(
            _scenario_payload(
                scenario_id=f"credential_{alias}_moto_authorized",
                title=f"Credential {alias} MoTo authorized",
                card_alias=alias,
                amount=_amount(index),
                requires_3ds=False,
                expected_initialize_status="authorized",
                expected_final_status="authorized",
                installment_count=1,
                payment_channel="moto",
                moto=True,
                tags=["credential", "local_mock", "moto", card_type],
            )
        )

    if card_type == "credit":
        for installment_count in (3, 2, 6, 9, 12):
            scenarios.append(
                _scenario_payload(
                    scenario_id=f"credential_{alias}_installment_{installment_count}",
                    title=f"Credential {alias} {installment_count} installment",
                    card_alias=alias,
                    amount=f"{installment_count * 100}.00",
                    requires_3ds=requires_3ds,
                    expected_initialize_status=(
                        "pending_3ds" if requires_3ds else "authorized"
                    ),
                    expected_final_status="captured" if requires_3ds else "authorized",
                    installment_count=installment_count,
                    payment_channel="e_commerce" if requires_3ds else "moto",
                    moto=not requires_3ds,
                    tags=["credential", "local_mock", "installment", "credit"],
                )
            )
    return scenarios


def _append_uat_coverage_scenarios(
    scenarios: list[dict[str, object]],
    cards: list[object],
) -> None:
    typed_cards = [card for card in cards if isinstance(card, dict)]
    three_ds_card = _first_matching_card(
        typed_cards,
        lambda card: bool(card["requires_3ds"]),
    )
    moto_card = _first_matching_card(
        typed_cards,
        lambda card: not bool(card["requires_3ds"]),
    )
    credit_card = _first_matching_card(
        typed_cards,
        lambda card: str(card["card_type"]) == "credit",
    )

    if three_ds_card is not None:
        alias = str(three_ds_card["alias"])
        scenarios.extend(
            [
                _scenario_payload(
                    scenario_id=f"uat_{alias}_wrong_otp",
                    title=f"UAT {alias} wrong OTP",
                    card_alias=alias,
                    amount="110.00",
                    requires_3ds=True,
                    expected_initialize_status="pending_3ds",
                    expected_final_status="failed",
                    installment_count=1,
                    payment_channel="e_commerce",
                    moto=False,
                    tags=["credential", "uat", "three_ds", "negative", "wrong_otp"],
                ),
                _scenario_payload(
                    scenario_id=f"uat_{alias}_payment_list",
                    title=f"UAT {alias} PaymentList verification",
                    card_alias=alias,
                    amount="120.00",
                    requires_3ds=True,
                    expected_initialize_status="pending_3ds",
                    expected_final_status="captured",
                    installment_count=1,
                    payment_channel="e_commerce",
                    moto=False,
                    tags=["credential", "uat", "three_ds", "payment_list"],
                ),
                _scenario_payload(
                    scenario_id=f"uat_{alias}_expired_card",
                    title=f"UAT {alias} expired card negative",
                    card_alias=alias,
                    amount="130.00",
                    requires_3ds=True,
                    expected_initialize_status="failed",
                    expected_final_status="failed",
                    installment_count=1,
                    payment_channel="e_commerce",
                    moto=False,
                    tags=["credential", "uat", "negative", "expired_card"],
                ),
            ]
        )

    if moto_card is not None:
        alias = str(moto_card["alias"])
        scenarios.append(
            _scenario_payload(
                scenario_id=f"uat_{alias}_moto_declined",
                title=f"UAT {alias} MoTo declined",
                card_alias=alias,
                amount="140.00",
                requires_3ds=False,
                expected_initialize_status="failed",
                expected_final_status="failed",
                installment_count=1,
                payment_channel="moto",
                moto=True,
                tags=["credential", "uat", "moto", "negative", "issuer_declined"],
            )
        )

    if credit_card is not None:
        _append_post_payment_scenarios(scenarios, credit_card)


def _append_post_payment_scenarios(
    scenarios: list[dict[str, object]],
    card: dict[str, object],
) -> None:
    alias = str(card["alias"])
    requires_3ds = bool(card["requires_3ds"])
    for operation, amount, final_status in (
        ("cancel", "150.00", "cancelled"),
        ("refund", "160.00", "refunded"),
    ):
        scenarios.append(
            _scenario_payload(
                scenario_id=f"uat_{alias}_{operation}",
                title=f"UAT {alias} {operation}",
                card_alias=alias,
                amount=amount,
                requires_3ds=requires_3ds,
                expected_initialize_status=(
                    "pending_3ds" if requires_3ds else "authorized"
                ),
                expected_final_status=final_status,
                installment_count=1,
                payment_channel="e_commerce" if requires_3ds else "moto",
                moto=not requires_3ds,
                tags=["credential", "uat", operation],
            )
        )


def _first_matching_card(
    cards: list[dict[str, object]],
    predicate: Callable[[dict[str, object]], bool],
) -> dict[str, object] | None:
    for card in cards:
        if predicate(card):
            return card
    return None


def _error_scenario(
    error: dict[str, object],
    *,
    error_card: dict[str, object],
    index: int,
) -> dict[str, object]:
    alias = str(error_card["alias"])
    requires_3ds = bool(error_card["requires_3ds"])
    error_code = str(error["expected_error_code"])
    scenario_id = str(error["scenario_id"]).replace("cvv_", "credential_cvv_")
    return _scenario_payload(
        scenario_id=f"{scenario_id}_{index:02d}",
        title=f"Credential CVV error {error_code}",
        card_alias=alias,
        amount="100.00",
        requires_3ds=requires_3ds,
        expected_initialize_status="failed",
        expected_final_status="failed",
        installment_count=1,
        payment_channel="e_commerce",
        moto=False,
        tags=[
            "credential",
            "local_mock",
            "negative",
            *_error_tags(error_code),
            "cvv_error",
            f"error_code_{error_code}",
        ],
    )


def _error_tags(error_code: str) -> list[str]:
    tags = ["invalid_cvv"]
    if error_code == "51":
        tags.append("insufficient_funds")
    return tags


def _first_card(cards: list[object]) -> dict[str, object]:
    if not cards:
        raise ValueError("at least one credential card is required to build scenarios")
    first = cards[0]
    if not isinstance(first, dict):
        raise TypeError("credential matrix card item is invalid")
    return first


def _scenario_payload(
    *,
    scenario_id: str,
    title: str,
    card_alias: str,
    amount: str,
    requires_3ds: bool,
    expected_initialize_status: str,
    expected_final_status: str,
    installment_count: int,
    payment_channel: str,
    moto: bool,
    tags: list[str],
) -> dict[str, object]:
    return {
        "scenario_id": scenario_id[:80],
        "title": title[:160],
        "card_alias": card_alias,
        "amount": amount,
        "currency": "TRY",
        "requires_3ds": requires_3ds,
        "expected_initialize_status": expected_initialize_status,
        "expected_final_status": expected_final_status,
        "installment_count": installment_count,
        "payment_channel": payment_channel,
        "moto": moto,
        "tags": _unique_tags(tags),
    }


def _unique_tags(tags: list[str]) -> list[str]:
    return list(dict.fromkeys(["sandbox", *tags]))


def _amount(index: int) -> str:
    return f"{((index % 20) + 1) * 10}.00"


def _read_paynkolay_cards(path: Path) -> list[CredentialCardMatrixItem]:
    rows = _read_csv(path)
    cards: list[CredentialCardMatrixItem] = []
    for index, row in enumerate(rows, start=1):
        pan = _digits(_value(row, "Kart Numarasi"))
        month, year = _parse_expiry(_value(row, "Son Kullanma Tarihi"))
        otp = _digits(_value(row, "Sifre")) or None
        cards.append(
            _card_item(
                source=path.name,
                index=index,
                bank_name=_value(row, "Banka Adi"),
                brand=_infer_brand(_value(row, "Kart Semasi")),
                card_type="credit",
                pan=pan,
                expiry_month=month,
                expiry_year=year,
                cvv=_digits(_value(row, "CVC Kodu")),
                requires_3ds=otp is not None,
                expected_otp=otp,
            )
        )
    return cards


def _read_error_codes(path: Path) -> list[CredentialErrorMatrixItem]:
    rows = _read_csv(path)
    errors: list[CredentialErrorMatrixItem] = []
    for row in rows:
        cvv = _digits(_value(row, "CVV"))
        code = _value(row, "Hata Kodu")
        message = _value(row, "Hata Aciklamasi")
        errors.append(
            CredentialErrorMatrixItem(
                scenario_id=f"cvv_{cvv}_error_{code}",
                cvv=cvv,
                expected_error_code=code,
                expected_error_message=message,
                input_condition=f"Use CVV {cvv} to trigger provider error {code}.",
            )
        )
    return errors


def _card_item(
    *,
    source: str,
    index: int,
    bank_name: str,
    brand: str,
    card_type: str,
    pan: str,
    expiry_month: int,
    expiry_year: int,
    cvv: str,
    requires_3ds: bool,
    expected_otp: str | None,
) -> CredentialCardMatrixItem:
    alias = f"{_slug(bank_name)}_{brand}_{pan[-4:] or index:0>4}"
    return CredentialCardMatrixItem(
        alias=alias,
        source=source,
        bank_name=bank_name,
        brand=brand,
        card_type=card_type,
        pan=pan,
        expiry_month=expiry_month,
        expiry_year=expiry_year,
        cvv=cvv,
        requires_3ds=requires_3ds,
        expected_otp=expected_otp,
        recommended_scenarios=_recommended_scenarios(
            card_type=card_type,
            requires_3ds=requires_3ds,
        ),
    )


def _recommended_scenarios(*, card_type: str, requires_3ds: bool) -> tuple[str, ...]:
    scenarios = ["three_ds_success"] if requires_3ds else ["moto_authorized"]
    scenarios.append("debit_coverage" if card_type == "debit" else "credit_coverage")
    if card_type == "credit":
        scenarios.append("installment_candidate")
    return tuple(scenarios)


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def _read_postman_collection_variables(path: Path) -> dict[str, str]:
    collection = json.loads(path.read_text(encoding="utf-8"))
    values: dict[str, str] = {}

    def walk(value: object) -> None:
        if isinstance(value, dict):
            key = value.get("key")
            item_value = value.get("value")
            if isinstance(key, str) and isinstance(item_value, str):
                values.setdefault(key, item_value)

            exec_lines = value.get("exec")
            if isinstance(exec_lines, list):
                for line in exec_lines:
                    if isinstance(line, str):
                        _collect_postman_setters(line, values)

            for child in value.values():
                walk(child)
        elif isinstance(value, list):
            for child in value:
                walk(child)

    walk(collection)
    return values


def _collect_postman_setters(line: str, values: dict[str, str]) -> None:
    pattern = re.compile(
        r"pm\.collectionVariables\.set\(\s*"
        r"(?P<quote>['\"])(?P<key>[^'\"]+)(?P=quote)\s*,\s*"
        r"(?P<value_quote>['\"])(?P<value>.*?)(?P=value_quote)\s*"
        r"\)"
    )
    for match in pattern.finditer(line):
        values[match.group("key")] = match.group("value")


def _read_gateway_form_inputs(path: Path) -> dict[str, str]:
    parser = _HiddenInputParser()
    parser.feed(path.read_text(encoding="utf-8"))
    return parser.inputs


def _read_installment_service_sx(path: Path) -> str | None:
    for line in path.read_text(encoding="utf-8").splitlines():
        key, separator, value = line.partition(":")
        if separator and key.strip().lower() == "sx":
            return _non_empty(value)
    return None


def _fallback_placeholder(current: str, extracted: str | None) -> str:
    if extracted is None:
        return current
    normalized = current.strip().lower()
    if (
        normalized.startswith("replace-with-")
        or normalized.startswith("local-mock-")
        or normalized == ""
    ):
        return extracted
    return current


def _non_empty(value: str | None) -> str | None:
    if value is None:
        return None
    stripped = value.strip()
    return stripped or None


def _value(row: dict[str, str], key: str) -> str:
    return (row.get(key) or "").strip()


def _digits(value: str) -> str:
    return "".join(character for character in value if character.isdigit())


def _parse_expiry(value: str) -> tuple[int, int]:
    parts = _digits(value)
    if len(parts) == 4:
        month = int(parts[:2])
        year = int(parts[2:])
        return month, 2000 + year
    if len(parts) == 6:
        year = int(parts[:4])
        month = int(parts[4:])
        return month, year
    raise ValueError(f"unsupported expiry format: {value!r}")


def _infer_brand(value: str) -> str:
    normalized = value.lower()
    if "master" in normalized:
        return "mastercard"
    if "troy" in normalized:
        return "troy"
    return "visa"


def _infer_card_type(value: str) -> str:
    return "debit" if "debit" in value.lower() else "credit"


def _extract_otp(value: str) -> str | None:
    match = re.search(r"orn:\s*(\d{4,8})|örn:\s*(\d{4,8})", value.lower())
    if match is None:
        return None
    return next(group for group in match.groups() if group)


def _slug(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value)
    ascii_value = normalized.encode("ascii", "ignore").decode("ascii").lower()
    slug = re.sub(r"[^a-z0-9]+", "_", ascii_value).strip("_")
    return slug or "card"
