from __future__ import annotations

import json
from pathlib import Path

import pytest

from paynkolay_pos.config import RuntimeSettings
from paynkolay_pos.scenarios import PaymentScenarioCatalog
from paynkolay_pos.testing import (
    build_credential_matrix_json,
    build_credential_matrix_payload,
    build_credential_runtime_config_json,
    build_credential_runtime_config_payload,
    build_credential_scenario_catalog_json,
    build_credential_scenario_catalog_payload,
    extract_paynkolay_uat_values,
)


def test_build_credential_matrix_payload_normalizes_cards_and_errors(tmp_path: Path) -> None:
    param_cards = tmp_path / "param_merchants.csv"
    param_cards.write_text(
        "\ufeffBanka,Kart Numarasi,Son Kullanma Tarihi,Guvenlik Numarasi (CVV),"
        "Ticari Kart,Kart Tipi\n"
        "Is Bankasi,6501738564461396,12/26,000,Hayir,"
        "Kredi Karti / TROY - 3DS Sifre: test (orn: 102824)\n"
        "Halk Bankasi,5818775818772285,12/26,001,Hayir,Debit / MASTERCARD\n",
        encoding="utf-8",
    )
    paynkolay_cards = tmp_path / "paynkolay_merchants.csv"
    paynkolay_cards.write_text(
        "\ufeffBanka Adi,Kart Numarasi,Kart Semasi,Son Kullanma Tarihi,CVC Kodu,Sifre\n"
        "DenizBank,5200190006338608,MasterCard,2030/01,410,123456\n",
        encoding="utf-8",
    )
    errors = tmp_path / "param_hata_kodlari.csv"
    errors.write_text(
        "\ufeffCVV,Hata Kodu,Hata Aciklamasi\n"
        "510,51,Limit Yetersiz\n",
        encoding="utf-8",
    )

    payload = build_credential_matrix_payload(
        param_cards_path=param_cards,
        paynkolay_cards_path=paynkolay_cards,
        error_codes_path=errors,
    )

    assert payload["summary"] == {
        "card_count": 3,
        "three_ds_card_count": 2,
        "moto_candidate_count": 1,
        "error_case_count": 1,
        "brands": ["mastercard", "troy"],
        "card_types": ["credit", "debit"],
    }
    cards = payload["cards"]
    assert isinstance(cards, list)
    assert cards[0]["brand"] == "troy"
    assert cards[0]["requires_3ds"] is True
    assert cards[0]["expected_otp"] == "102824"
    assert cards[1]["card_type"] == "debit"
    assert cards[1]["recommended_scenarios"] == ("moto_authorized", "debit_coverage")
    assert cards[2]["expiry_month"] == 1
    assert cards[2]["expiry_year"] == 2030

    error_items = payload["errors"]
    assert isinstance(error_items, list)
    assert error_items[0]["scenario_id"] == "cvv_510_error_51"
    assert error_items[0]["expected_error_message"] == "Limit Yetersiz"


def test_build_credential_matrix_json_serializes_payload(tmp_path: Path) -> None:
    errors = tmp_path / "param_hata_kodlari.csv"
    errors.write_text(
        "\ufeffCVV,Hata Kodu,Hata Aciklamasi\n"
        "120,12,Gecersiz Islem\n",
        encoding="utf-8",
    )

    body = build_credential_matrix_json(error_codes_path=errors)
    payload = json.loads(body)

    assert payload["summary"]["card_count"] == 0
    assert payload["summary"]["error_case_count"] == 1
    assert payload["errors"][0]["input_condition"] == (
        "Use CVV 120 to trigger provider error 12."
    )


def test_build_credential_matrix_payload_fills_to_total_card_count(
    tmp_path: Path,
) -> None:
    paynkolay_cards = tmp_path / "paynkolay_merchants.csv"
    paynkolay_cards.write_text(
        "\ufeffBanka Adi,Kart Numarasi,Kart Semasi,Son Kullanma Tarihi,CVC Kodu,Sifre\n"
        "DenizBank,5200190006338608,MasterCard,2030/01,410,123456\n",
        encoding="utf-8",
    )

    payload = build_credential_matrix_payload(
        paynkolay_cards_path=paynkolay_cards,
        total_card_count=5,
    )

    summary = payload["summary"]
    assert isinstance(summary, dict)
    assert summary["card_count"] == 5
    cards = payload["cards"]
    assert isinstance(cards, list)
    first_card = cards[0]
    last_card = cards[-1]
    assert isinstance(first_card, dict)
    assert isinstance(last_card, dict)
    assert first_card["alias"] == "denizbank_mastercard_8608"
    assert last_card["alias"] == "synthetic_filler_0004"
    assert last_card["requires_3ds"] is False
    assert last_card["source"] == "synthetic_filler"


def test_build_credential_matrix_rejects_total_smaller_than_real_cards(
    tmp_path: Path,
) -> None:
    paynkolay_cards = tmp_path / "paynkolay_merchants.csv"
    paynkolay_cards.write_text(
        "\ufeffBanka Adi,Kart Numarasi,Kart Semasi,Son Kullanma Tarihi,CVC Kodu,Sifre\n"
        "DenizBank,5200190006338608,MasterCard,2030/01,410,123456\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="total_card_count must be greater than zero"):
        build_credential_matrix_payload(
            paynkolay_cards_path=paynkolay_cards,
            total_card_count=0,
        )


def test_build_credential_scenario_catalog_payload_validates(tmp_path: Path) -> None:
    param_cards = tmp_path / "param_merchants.csv"
    param_cards.write_text(
        "\ufeffBanka,Kart Numarasi,Son Kullanma Tarihi,Guvenlik Numarasi (CVV),"
        "Ticari Kart,Kart Tipi\n"
        "Is Bankasi,6501738564461396,12/26,000,Hayir,"
        "Kredi Karti / TROY - 3DS Sifre: test (orn: 102824)\n"
        "Halk Bankasi,5818775818772285,12/26,001,Hayir,Debit / MASTERCARD\n",
        encoding="utf-8",
    )
    errors = tmp_path / "param_hata_kodlari.csv"
    errors.write_text(
        "\ufeffCVV,Hata Kodu,Hata Aciklamasi\n"
        "510,51,Limit Yetersiz\n",
        encoding="utf-8",
    )

    payload = build_credential_scenario_catalog_payload(
        param_cards_path=param_cards,
        error_codes_path=errors,
    )
    catalog = PaymentScenarioCatalog.model_validate(payload)

    assert len(catalog.scenarios) >= 4
    assert catalog.scenarios[0].scenario_id == "credential_is_bankasi_troy_1396_3ds_success"
    assert catalog.scenarios[0].requires_3ds is True
    assert "three_ds" in catalog.scenarios[0].tags
    assert catalog.scenarios[1].installment_count == 3
    assert any(scenario.moto for scenario in catalog.scenarios)
    negative = catalog.tagged("cvv_error")[0]
    assert negative.expected_final_status.value == "failed"
    assert "invalid_cvv" in negative.tags
    assert "insufficient_funds" in negative.tags
    assert "error_code_51" in negative.tags
    assert catalog.tagged("wrong_otp")
    assert catalog.tagged("payment_list")
    assert catalog.tagged("cancel")
    assert catalog.tagged("refund")


def test_build_credential_scenario_catalog_json_serializes_catalogue(tmp_path: Path) -> None:
    paynkolay_cards = tmp_path / "paynkolay_merchants.csv"
    paynkolay_cards.write_text(
        "\ufeffBanka Adi,Kart Numarasi,Kart Semasi,Son Kullanma Tarihi,CVC Kodu,Sifre\n"
        "DenizBank,5200190006338608,MasterCard,2030/01,410,123456\n",
        encoding="utf-8",
    )

    body = build_credential_scenario_catalog_json(paynkolay_cards_path=paynkolay_cards)
    payload = json.loads(body)
    catalog = PaymentScenarioCatalog.model_validate(payload)

    assert len(catalog.scenarios) >= 2
    assert catalog.scenarios[0].card_alias == "denizbank_mastercard_8608"


def test_build_credential_scenario_catalog_rejects_empty_card_set() -> None:
    with pytest.raises(ValueError, match="at least one credential card"):
        build_credential_scenario_catalog_payload()


def test_build_credential_runtime_config_payload_matches_scenario_aliases(
    tmp_path: Path,
) -> None:
    param_cards = tmp_path / "param_merchants.csv"
    param_cards.write_text(
        "\ufeffBanka,Kart Numarasi,Son Kullanma Tarihi,Guvenlik Numarasi (CVV),"
        "Ticari Kart,Kart Tipi\n"
        "Is Bankasi,6501738564461396,12/26,000,Hayir,"
        "Kredi Karti / TROY - 3DS Sifre: test (orn: 102824)\n"
        "Halk Bankasi,5818775818772285,12/26,001,Hayir,Debit / MASTERCARD\n",
        encoding="utf-8",
    )

    settings = RuntimeSettings.model_validate(
        build_credential_runtime_config_payload(param_cards_path=param_cards)
    )
    catalog = PaymentScenarioCatalog.model_validate(
        build_credential_scenario_catalog_payload(param_cards_path=param_cards)
    )

    configured_aliases = {card.alias for card in settings.current.cards}
    scenario_aliases = {scenario.card_alias for scenario in catalog.scenarios}

    assert len(settings.current.cards) == 2
    assert scenario_aliases <= configured_aliases
    assert settings.current.cards[0].alias == "is_bankasi_troy_1396"
    assert settings.current.cards[0].expected_otp is not None


def test_build_credential_runtime_config_and_scenarios_share_synthetic_fillers(
    tmp_path: Path,
) -> None:
    paynkolay_cards = tmp_path / "paynkolay_merchants.csv"
    paynkolay_cards.write_text(
        "\ufeffBanka Adi,Kart Numarasi,Kart Semasi,Son Kullanma Tarihi,CVC Kodu,Sifre\n"
        "DenizBank,5200190006338608,MasterCard,2030/01,410,123456\n",
        encoding="utf-8",
    )

    settings = RuntimeSettings.model_validate(
        build_credential_runtime_config_payload(
            paynkolay_cards_path=paynkolay_cards,
            total_card_count=5,
        )
    )
    catalog = PaymentScenarioCatalog.model_validate(
        build_credential_scenario_catalog_payload(
            paynkolay_cards_path=paynkolay_cards,
            total_card_count=5,
        )
    )

    configured_aliases = {card.alias for card in settings.current.cards}
    scenario_aliases = {scenario.card_alias for scenario in catalog.scenarios}

    assert len(settings.current.cards) == 5
    assert "synthetic_filler_0004" in configured_aliases
    assert scenario_aliases <= configured_aliases
    assert "synthetic_filler_0004" in scenario_aliases


def test_build_credential_runtime_config_json_serializes_valid_settings(tmp_path: Path) -> None:
    paynkolay_cards = tmp_path / "paynkolay_merchants.csv"
    paynkolay_cards.write_text(
        "\ufeffBanka Adi,Kart Numarasi,Kart Semasi,Son Kullanma Tarihi,CVC Kodu,Sifre\n"
        "DenizBank,5200190006338608,MasterCard,2030/01,410,123456\n",
        encoding="utf-8",
    )

    body = build_credential_runtime_config_json(paynkolay_cards_path=paynkolay_cards)
    settings = RuntimeSettings.model_validate_json(body)

    assert settings.current.name == "dev"
    assert settings.current.cards[0].alias == "denizbank_mastercard_8608"
    assert settings.current.cards[0].requires_3ds is True


def test_build_credential_runtime_config_can_target_uat(tmp_path: Path) -> None:
    paynkolay_cards = tmp_path / "paynkolay_merchants.csv"
    paynkolay_cards.write_text(
        "\ufeffBanka Adi,Kart Numarasi,Kart Semasi,Son Kullanma Tarihi,CVC Kodu,Sifre\n"
        "DenizBank,5200190006338608,MasterCard,2030/01,410,123456\n",
        encoding="utf-8",
    )

    settings = RuntimeSettings.model_validate(
        build_credential_runtime_config_payload(
            paynkolay_cards_path=paynkolay_cards,
            active_environment="uat",
            base_url="https://paynkolaytest.nkolayislem.com.tr/Vpos",
            callback_base_url="https://internal.example.com/paynkolay",
            merchant_id="uat-merchant",
            terminal_id="uat-terminal",
            api_key="uat-payment-sx",
            installment_api_key="uat-installment-sx",
            list_api_key="uat-list-sx",
            cancel_refund_api_key="uat-cancel-sx",
            secret_key="uat-secret",
        )
    )

    assert settings.active_environment == "uat"
    assert settings.current.name == "uat"
    assert settings.current.base_url == "https://paynkolaytest.nkolayislem.com.tr/Vpos"
    assert settings.current.callback_base_url == "https://internal.example.com/paynkolay"
    assert settings.current.merchant.api_key.get_secret_value() == "uat-payment-sx"
    assert settings.current.merchant.installment_api_key is not None
    assert (
        settings.current.merchant.installment_api_key.get_secret_value()
        == "uat-installment-sx"
    )
    assert settings.current.merchant.list_api_key is not None
    assert settings.current.merchant.list_api_key.get_secret_value() == "uat-list-sx"
    assert settings.current.merchant.cancel_refund_api_key is not None
    assert (
        settings.current.merchant.cancel_refund_api_key.get_secret_value()
        == "uat-cancel-sx"
    )


def test_extract_paynkolay_uat_values_reads_postman_and_gateway_form(
    tmp_path: Path,
) -> None:
    postman = tmp_path / "paynkolay.postman_collection.json"
    postman.write_text(
        json.dumps(
            {
                "event": [
                    {
                        "script": {
                            "exec": [
                                'pm.collectionVariables.set("sx", "payment-sx");',
                                'pm.collectionVariables.set("sx-list", "list-sx");',
                                'pm.collectionVariables.set("sx-cancel", "cancel-sx");',
                                'pm.collectionVariables.set("merchantSecretKey", "secret");',
                            ]
                        }
                    }
                ],
                "variable": [{"key": "sx", "value": ""}],
            }
        ),
        encoding="utf-8",
    )
    gateway_form = tmp_path / "base64.md"
    gateway_form.write_text(
        """
        <input name="clientid" type="hidden" value="190000300" />
        <input name="SUBMERCHANTID" type="hidden" value="6420371466" />
        """,
        encoding="utf-8",
    )
    installment_service = tmp_path / "servisler.md"
    installment_service.write_text(
        "https://provider.example.test/PaymentInstallments\n"
        "sx:installment-sx\n"
        "paymentListSx:private-list-sx\n"
        "merchantSecretKey:installment-secret\n"
        "amount:1000.00\n",
        encoding="utf-8",
    )

    values = extract_paynkolay_uat_values(
        postman_collection_path=postman,
        gateway_form_path=gateway_form,
        installment_service_path=installment_service,
    )

    assert values.payment_sx == "payment-sx"
    assert values.installment_sx == "installment-sx"
    assert values.list_sx == "private-list-sx"
    assert values.postman_list_sx == "list-sx"
    assert values.cancel_refund_sx == "cancel-sx"
    assert values.secret_key == "installment-secret"
    assert values.postman_secret_key == "secret"
    assert values.merchant_id == "6420371466"
    assert values.terminal_id == "190000300"


def test_build_credential_runtime_config_auto_fills_uat_placeholders(
    tmp_path: Path,
) -> None:
    paynkolay_cards = tmp_path / "paynkolay_merchants.csv"
    paynkolay_cards.write_text(
        "\ufeffBanka Adi,Kart Numarasi,Kart Semasi,Son Kullanma Tarihi,CVC Kodu,Sifre\n"
        "DenizBank,5200190006338608,MasterCard,2030/01,410,123456\n",
        encoding="utf-8",
    )
    postman = tmp_path / "paynkolay.postman_collection.json"
    postman.write_text(
        json.dumps(
            {
                "event": [
                    {
                        "script": {
                            "exec": [
                                'pm.collectionVariables.set("sx", "payment-sx");',
                                'pm.collectionVariables.set("sx-list", "list-sx");',
                                'pm.collectionVariables.set("sx-cancel", "cancel-sx");',
                                'pm.collectionVariables.set("merchantSecretKey", "secret");',
                            ]
                        }
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    gateway_form = tmp_path / "base64.md"
    gateway_form.write_text(
        """
        <input name="clientid" type="hidden" value="190000300" />
        <input name="SUBMERCHANTID" type="hidden" value="6420371466" />
        """,
        encoding="utf-8",
    )
    installment_service = tmp_path / "servisler.md"
    installment_service.write_text(
        "sx:installment-sx\n"
        "paymentListSx:private-list-sx\n"
        "merchantSecretKey:installment-secret\n",
        encoding="utf-8",
    )

    settings = RuntimeSettings.model_validate(
        build_credential_runtime_config_payload(
            paynkolay_cards_path=paynkolay_cards,
            postman_collection_path=postman,
            gateway_form_path=gateway_form,
            installment_service_path=installment_service,
            active_environment="uat",
            base_url="https://paynkolaytest.nkolayislem.com.tr/Vpos",
            callback_base_url="https://internal.example.com/paynkolay",
            merchant_id="replace-with-uat-merchant-id",
            terminal_id="replace-with-uat-terminal-id",
            api_key="replace-with-uat-payment-sx",
            installment_api_key="replace-with-uat-installment-sx",
            list_api_key="replace-with-uat-list-sx",
            cancel_refund_api_key="replace-with-uat-cancel-refund-sx",
            secret_key="replace-with-uat-secret-key",
        )
    )

    assert settings.current.merchant.merchant_id == "6420371466"
    assert settings.current.merchant.terminal_id == "190000300"
    assert settings.current.merchant.api_key.get_secret_value() == "installment-sx"
    assert settings.current.merchant.installment_api_key is not None
    assert (
        settings.current.merchant.installment_api_key.get_secret_value()
        == "installment-sx"
    )
    assert settings.current.merchant.list_api_key is not None
    assert settings.current.merchant.list_api_key.get_secret_value() == "private-list-sx"
    assert settings.current.merchant.cancel_refund_api_key is not None
    assert (
        settings.current.merchant.cancel_refund_api_key.get_secret_value()
        == "cancel-sx"
    )
    assert (
        settings.current.merchant.secret_key.get_secret_value()
        == "installment-secret"
    )

    settings_273 = RuntimeSettings.model_validate(
        build_credential_runtime_config_payload(
            paynkolay_cards_path=paynkolay_cards,
            postman_collection_path=postman,
            gateway_form_path=gateway_form,
            installment_service_path=installment_service,
            active_environment="uat",
            base_url="https://paynkolaytest.nkolayislem.com.tr/Vpos",
            callback_base_url="https://internal.example.com/paynkolay",
            merchant_id="400000273",
            terminal_id="replace-with-uat-terminal-id",
            api_key="replace-with-uat-payment-sx",
            installment_api_key="replace-with-uat-installment-sx",
            list_api_key="replace-with-uat-list-sx",
            cancel_refund_api_key="replace-with-uat-cancel-refund-sx",
            secret_key="replace-with-uat-secret-key",
        )
    )

    assert settings_273.current.merchant.merchant_id == "400000273"
    assert settings_273.current.merchant.api_key.get_secret_value() == "payment-sx"
    assert settings_273.current.merchant.installment_api_key is not None
    assert (
        settings_273.current.merchant.installment_api_key.get_secret_value()
        == "payment-sx"
    )
    assert settings_273.current.merchant.list_api_key is not None
    assert settings_273.current.merchant.list_api_key.get_secret_value() == "list-sx"
    assert settings_273.current.merchant.secret_key.get_secret_value() == "secret"


def test_build_credential_runtime_config_keeps_explicit_uat_values(
    tmp_path: Path,
) -> None:
    paynkolay_cards = tmp_path / "paynkolay_merchants.csv"
    paynkolay_cards.write_text(
        "\ufeffBanka Adi,Kart Numarasi,Kart Semasi,Son Kullanma Tarihi,CVC Kodu,Sifre\n"
        "DenizBank,5200190006338608,MasterCard,2030/01,410,123456\n",
        encoding="utf-8",
    )
    postman = tmp_path / "paynkolay.postman_collection.json"
    postman.write_text(
        json.dumps(
            {
                "event": [
                    {
                        "script": {
                            "exec": [
                                'pm.collectionVariables.set("sx", "payment-sx");',
                                'pm.collectionVariables.set("merchantSecretKey", "secret");',
                            ]
                        }
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    settings = RuntimeSettings.model_validate(
        build_credential_runtime_config_payload(
            paynkolay_cards_path=paynkolay_cards,
            postman_collection_path=postman,
            active_environment="uat",
            base_url="https://paynkolaytest.nkolayislem.com.tr/Vpos",
            callback_base_url="https://internal.example.com/paynkolay",
            merchant_id="explicit-merchant",
            terminal_id="explicit-terminal",
            api_key="explicit-payment-sx",
            secret_key="explicit-secret",
        )
    )

    assert settings.current.merchant.merchant_id == "explicit-merchant"
    assert settings.current.merchant.terminal_id == "explicit-terminal"
    assert settings.current.merchant.api_key.get_secret_value() == "explicit-payment-sx"
    assert settings.current.merchant.secret_key.get_secret_value() == "explicit-secret"


def test_build_credential_runtime_config_rejects_empty_card_set() -> None:
    with pytest.raises(ValueError, match="at least one credential card"):
        build_credential_runtime_config_payload()
