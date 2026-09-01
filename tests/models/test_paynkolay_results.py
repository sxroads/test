from __future__ import annotations

import json
from datetime import UTC, datetime
from decimal import Decimal

import pytest
from pydantic import SecretStr, ValidationError

from paynkolay_pos.models import (
    Currency,
    PaymentStatus,
    PaynkolayCancelRefundResult,
    PaynkolayCancelRefundType,
    PaynkolayPaymentListResponse,
    PaynkolayPaymentListRow,
    PaynkolayPaymentResult,
    PaynkolayProviderStatus,
    PaynkolayThreeDSInitializeResult,
    parse_paynkolay_payment_result,
)

PAYMENT_RESULT_HASH = (
    "38SwgQiVN8mLKWAp8FBikefhiWPm+8qu+w83hxgqrGEVS+7I+V6T2KoWoaUtVCES8knU5Uu/GatucjiZe/zqLA=="
)


def successful_result_payload(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "RESPONSE_CODE": "2",
        "RESPONSE_DATA": "Islem Basarili",
        "USE_3D": "true",
        "RND": "1630051651137",
        "MERCHANT_NO": "400000001",
        "AUTH_CODE": "S00586",
        "REFERENCE_CODE": "IKSIRPF102168",
        "CLIENT_REFERENCE_CODE": "order-1001",
        "TIMESTAMP": "2026-07-03 09:45:00.000",
        "TRANSACTION_AMOUNT": "1.00",
        "AUTHORIZATION_AMOUNT": "1.00",
        "COMMISION": "0.00",
        "COMMISION_RATE": "0.0000",
        "INSTALLMENT": "1",
        "CURRENCY_CODE": "TRY",
        "hashData": "legacy-hash",
        "hashDataV2": PAYMENT_RESULT_HASH,
    }
    payload.update(overrides)
    return payload


@pytest.mark.api
def test_parse_paynkolay_3ds_initialize_result() -> None:
    result = parse_paynkolay_payment_result(
        {"BANK_REQUEST_MESSAGE": "<form>3DS challenge</form>"}
    )

    assert isinstance(result, PaynkolayThreeDSInitializeResult)
    assert result.status is PaymentStatus.PENDING_3DS
    assert result.bank_request_message == "<form>3DS challenge</form>"


@pytest.mark.api
def test_payment_result_verifies_hash_and_maps_success_status() -> None:
    result = PaynkolayPaymentResult.model_validate(successful_result_payload())

    assert result.response_code == "2"
    assert result.auth_code == "S00586"
    assert result.authorization_amount == Decimal("1.00")
    assert result.currency_code is Currency.TRY
    assert result.successful is True
    assert result.status is PaymentStatus.CAPTURED
    assert result.expected_hash(SecretStr("merchant-secret")) == PAYMENT_RESULT_HASH
    assert result.verify_hash(SecretStr("merchant-secret"))
    assert not result.verify_hash(SecretStr("wrong-secret"))


@pytest.mark.api
def test_payment_result_accepts_numeric_response_code() -> None:
    result = PaynkolayPaymentResult.model_validate(
        successful_result_payload(RESPONSE_CODE=2)
    )

    assert result.response_code == "2"
    assert result.successful is True
    assert result.expected_hash(SecretStr("merchant-secret")) == PAYMENT_RESULT_HASH


@pytest.mark.api
def test_payment_result_converts_success_to_transaction_status_response() -> None:
    result = PaynkolayPaymentResult.model_validate(successful_result_payload())

    status = result.to_transaction_status_response()

    assert status.order_id == "order-1001"
    assert status.provider_transaction_id == "IKSIRPF102168"
    assert status.status is PaymentStatus.CAPTURED
    assert status.amount == Decimal("1.00")
    assert status.currency is Currency.TRY
    assert status.updated_at == datetime(2026, 7, 3, 9, 45, tzinfo=UTC)
    assert status.authorization_code == "S00586"
    assert status.failure_code is None


@pytest.mark.api
def test_payment_result_converts_failure_to_transaction_status_response() -> None:
    result = PaynkolayPaymentResult.model_validate(
        successful_result_payload(
            RESPONSE_CODE="99",
            RESPONSE_DATA="Bank declined",
            AUTH_CODE="",
        )
    )

    status = result.to_transaction_status_response()

    assert status.status is PaymentStatus.FAILED
    assert status.authorization_code is None
    assert status.failure_code == "99"


@pytest.mark.api
@pytest.mark.parametrize("auth_code", ["", "0", "00"])
def test_payment_result_requires_real_auth_code_for_success(auth_code: str) -> None:
    result = PaynkolayPaymentResult.model_validate(
        successful_result_payload(AUTH_CODE=auth_code)
    )

    assert result.successful is False
    assert result.status is PaymentStatus.FAILED


@pytest.mark.api
def test_payment_result_treats_non_success_response_code_as_failed() -> None:
    result = PaynkolayPaymentResult.model_validate(
        successful_result_payload(RESPONSE_CODE="99")
    )

    assert result.successful is False
    assert result.status is PaymentStatus.FAILED


@pytest.mark.negative
def test_payment_result_requires_hash_data_v2() -> None:
    payload = successful_result_payload()
    del payload["hashDataV2"]

    with pytest.raises(ValidationError, match="hashDataV2"):
        PaynkolayPaymentResult.model_validate(payload)


@pytest.mark.api
def test_parse_paynkolay_payment_result_uses_result_payload_when_no_3ds_html() -> None:
    result = parse_paynkolay_payment_result(successful_result_payload())

    assert isinstance(result, PaynkolayPaymentResult)
    assert result.reference_code == "IKSIRPF102168"


@pytest.mark.api
def test_parse_paynkolay_moto_result_ignores_null_3ds_form_field() -> None:
    result = parse_paynkolay_payment_result(
        successful_result_payload(
            BANK_REQUEST_MESSAGE=None,
            USE_3D="false",
            TimeStamp=None,
            hashDataV2=None,
            hashDatav2=PAYMENT_RESULT_HASH,
        )
    )

    assert isinstance(result, PaynkolayPaymentResult)
    assert result.status is PaymentStatus.CAPTURED
    assert result.use_3d == "false"
    assert result.hash_data_v2 == PAYMENT_RESULT_HASH


@pytest.mark.api
def test_parse_paynkolay_declined_init_result_with_null_provider_fields() -> None:
    result = parse_paynkolay_payment_result(
        {
            "BANK_REQUEST_MESSAGE": None,
            "RESPONSE_CODE": 0,
            "RESPONSE_DATA": "İşlem Başarısız.",
            "TRANSACTION_AMOUNT": "22,00",
            "TimeStamp": "7/13/2026 2:05:18 PM",
            "hashDatav2": "declined-hash",
        }
    )

    assert isinstance(result, PaynkolayPaymentResult)
    assert result.status is PaymentStatus.FAILED
    assert result.response_code == "0"
    assert result.response_data == "İşlem Başarısız."


def payment_list_row_payload(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "REFERENCE_CODE": "IKSIRPF102168",
        "AUTH_CODE": "S00586",
        "AUTHORIZATION_AMOUNT": "1.00",
        "TRANSACTION_AMOUNT": "1.00",
        "CLIENT_REFERENCE_CODE": "order-1001",
        "STATUS": "SUCCESS",
        "TRANSACTION_TYPE": "SALES",
        "TRX_DATE": "03.07.2026 09:45:00",
        "CARD_HOLDER_NAME": "TEST-AUTOMATION",
        "IS_3D": True,
        "INSTALLMENT_COUNT": "1",
        "DESCRIPTION": "",
    }
    payload.update(overrides)
    return payload


@pytest.mark.api
def test_payment_list_row_maps_success_to_transaction_status_response() -> None:
    row = PaynkolayPaymentListRow.model_validate(payment_list_row_payload())

    status = row.to_transaction_status_response()

    assert row.status is PaynkolayProviderStatus.SUCCESS
    assert row.payment_status is PaymentStatus.CAPTURED
    assert status.order_id == "order-1001"
    assert status.provider_transaction_id == "IKSIRPF102168"
    assert status.status is PaymentStatus.CAPTURED
    assert status.amount == Decimal("1.00")
    assert status.currency is Currency.TRY
    assert status.authorization_code == "S00586"


@pytest.mark.api
def test_payment_list_row_ignores_documented_extra_provider_fields() -> None:
    row = PaynkolayPaymentListRow.model_validate(
        payment_list_row_payload(
            CORE_TRX_ID_RESERVED="E74D",
            COMMISION="0.0100",
            CARD_BANK_CODE="010",
            USER_EMAIL="hayalevi",
            OID="0769CE1-31C607C",
            POS_TYPE="Sanal POS",
            TERMINAL_NAME="ZIRAATBANK",
            CARD_BANK_NAME="T.C.ZIRAAT BANKASI",
            MERCHANT_COMMISSION_AMOUNT="0.00",
            VALOR_DATE="20241226",
        )
    )

    assert row.reference_code == "IKSIRPF102168"
    assert row.payment_status is PaymentStatus.CAPTURED


@pytest.mark.api
def test_payment_list_row_accepts_iso_transaction_date() -> None:
    row = PaynkolayPaymentListRow.model_validate(
        payment_list_row_payload(TRX_DATE="2026-07-03T09:45:00+03:00")
    )

    status = row.to_transaction_status_response()

    assert status.updated_at == datetime(2026, 7, 3, 6, 45, tzinfo=UTC)


@pytest.mark.api
@pytest.mark.parametrize(
    ("provider_status", "payment_status"),
    [
        ("ERROR", PaymentStatus.FAILED),
        ("NEW", PaymentStatus.CREATED),
    ],
)
def test_payment_list_row_maps_non_success_statuses(
    provider_status: str,
    payment_status: PaymentStatus,
) -> None:
    row = PaynkolayPaymentListRow.model_validate(
        payment_list_row_payload(
            STATUS=provider_status,
            AUTH_CODE="",
            DESCRIPTION="Provider status detail",
        )
    )

    assert row.payment_status is payment_status


@pytest.mark.api
def test_payment_list_row_uses_provider_status_as_failed_fallback_code() -> None:
    row = PaynkolayPaymentListRow.model_validate(
        payment_list_row_payload(
            STATUS="ERROR",
            AUTH_CODE="",
            DESCRIPTION="",
        )
    )

    status = row.to_transaction_status_response()

    assert status.status is PaymentStatus.FAILED
    assert status.failure_code == "ERROR"


@pytest.mark.api
def test_payment_list_response_filters_rows_by_client_reference_code() -> None:
    response = PaynkolayPaymentListResponse.model_validate(
        {
            "id": "",
            "result": {
                "RESPONSE_CODE": "2",
                "RESPONSE_DATA": "Islem basarili",
                "LIST": [
                    payment_list_row_payload(CLIENT_REFERENCE_CODE="order-1001"),
                    payment_list_row_payload(
                        REFERENCE_CODE="IKSIRPF102169",
                        CLIENT_REFERENCE_CODE="order-2002",
                    ),
                ],
            },
        }
    )

    assert response.result.successful is True
    assert len(response.result.rows) == 2
    assert response.rows_for_client_ref("order-1001")[0].reference_code == "IKSIRPF102168"


@pytest.mark.api
def test_payment_list_response_accepts_numeric_response_code() -> None:
    response = PaynkolayPaymentListResponse.model_validate(
        {
            "id": "",
            "result": {
                "RESPONSE_CODE": 2,
                "RESPONSE_DATA": "Islem basarili",
                "LIST": [],
            },
        }
    )

    assert response.result.response_code == "2"
    assert response.result.successful is True


@pytest.mark.api
def test_payment_list_response_accepts_flat_live_provider_payload() -> None:
    response = PaynkolayPaymentListResponse.model_validate(
        {
            "RESPONSE_CODE": "2",
            "RESPONSE_DATA": "Islem basarili",
            "LIST": [payment_list_row_payload()],
            "TimeStamp": None,
        }
    )

    assert response.result.successful is True
    assert response.rows_for_client_ref("order-1001")[0].reference_code == "IKSIRPF102168"


@pytest.mark.api
def test_payment_list_response_accepts_json_string_result_envelope() -> None:
    response = PaynkolayPaymentListResponse.model_validate(
        {
            "id": "",
            "result": json.dumps(
                {
                    "RESPONSE_CODE": "2",
                    "RESPONSE_DATA": "Islem basarili",
                    "LIST": [payment_list_row_payload()],
                }
            ),
        }
    )

    assert response.result.successful is True
    assert response.rows_for_client_ref("order-1001")[0].reference_code == "IKSIRPF102168"


@pytest.mark.api
@pytest.mark.parametrize(
    ("transaction_type", "expected_status"),
    [
        (PaynkolayCancelRefundType.CANCEL, PaymentStatus.CANCELLED),
        (PaynkolayCancelRefundType.REFUND, PaymentStatus.REFUNDED),
    ],
)
def test_cancel_refund_result_maps_success_to_operation_status(
    transaction_type: PaynkolayCancelRefundType,
    expected_status: PaymentStatus,
) -> None:
    result = PaynkolayCancelRefundResult.model_validate(
        {
            "responseCode": 2,
            "responseData": "Islem basarili",
            "type": transaction_type.value,
        }
    )

    assert result.response_code == "2"
    assert result.response_data == "Islem basarili"
    assert result.transaction_type is transaction_type
    assert result.successful is True
    assert result.status is expected_status


@pytest.mark.api
def test_cancel_refund_result_maps_non_success_to_failed() -> None:
    result = PaynkolayCancelRefundResult.model_validate(
        {
            "RESPONSE_CODE": "99",
            "RESPONSE_DATA": "Islem basarisiz",
            "type": "refund",
        }
    )

    assert result.successful is False
    assert result.status is PaymentStatus.FAILED
