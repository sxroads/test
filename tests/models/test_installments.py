from __future__ import annotations

from decimal import Decimal

import pytest

from paynkolay_pos.models import PaynkolayInstallmentResponse


@pytest.mark.api
def test_paynkolay_installment_response_parses_real_provider_shape() -> None:
    response = PaynkolayInstallmentResponse.model_validate(
        {
            "PAYMENT_BANK_LIST": [
                {
                    "INSTALLMENT_AMOUNT": 350.88,
                    "INSTALLMENT": 3,
                    "COMMISION_AMOUNT": 52.63,
                    "COMMISION": 5,
                    "TRANSACTION_AMOUNT": 1000,
                    "AUTHORIZATION_AMOUNT": 1052.63,
                    "EncodedValue": "opaque-provider-quote",
                    "CURRENCY_CODE": "TRY",
                }
            ],
            "RESPONSE_DATA": "İşlem Başarılı.",
            "RESPONSE_CODE": 2,
            "CARD_SCOPE": "I",
        }
    )

    assert response.successful is True
    assert response.response_data == "İşlem Başarılı."
    assert len(response.quotes) == 1
    quote = response.quotes[0]
    assert quote.installment_count == 3
    assert quote.installment_amount == Decimal("350.88")
    assert quote.authorization_amount == Decimal("1052.63")
    assert quote.commission_rate == Decimal("5.00")
    assert quote.encoded_value.get_secret_value() == "opaque-provider-quote"
    assert "opaque-provider-quote" not in repr(quote)


@pytest.mark.api
def test_paynkolay_installment_response_marks_provider_error_unsuccessful() -> None:
    response = PaynkolayInstallmentResponse.model_validate(
        {
            "PAYMENT_BANK_LIST": [],
            "RESPONSE_DATA": "Kart için taksit bulunamadı.",
            "RESPONSE_CODE": 99,
        }
    )

    assert response.successful is False
    assert response.quotes == []
