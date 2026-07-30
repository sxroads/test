"""Async HTTP client boundary for Paynkolay Sanal POS API calls."""

from __future__ import annotations

import json
from collections.abc import Mapping
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Any
from urllib.parse import quote

import httpx
from pydantic import SecretStr

from paynkolay_pos.config import PaymentEnvironment
from paynkolay_pos.models import (
    Currency,
    PaymentInitializeRequest,
    PaymentInitializeResponse,
    PaynkolayCancelRefundResult,
    PaynkolayCancelRefundType,
    PaynkolayInstallmentResponse,
    PaynkolayPaymentListResponse,
    TransactionStatusResponse,
)
from paynkolay_pos.security import (
    canonicalize_fields,
    generate_cancel_refund_hash,
    generate_hmac_signature,
    generate_payment_list_hash,
    generate_payment_request_hash,
)

PAYNKOLAY_PAYMENT_PATH = "/v1/Payment"
PAYNKOLAY_INSTALLMENTS_PATH = "/Payment/PaymentInstallments"
PAYNKOLAY_PAYMENT_LIST_PATH = "/Payment/PaymentList"
PAYNKOLAY_CANCEL_REFUND_PATH = "/v1/CancelRefundPayment"

PAYNKOLAY_CURRENCY_NUMBERS = {
    Currency.TRY: "949",
    Currency.USD: "840",
    Currency.EUR: "978",
}

PAYMENT_INITIALIZE_SIGNATURE_FIELDS = (
    "merchant_id",
    "terminal_id",
    "order_id",
    "amount",
    "currency",
    "callback_url",
    "requires_3ds",
    "installment_count",
    "payment_channel",
    "moto",
    "correlation_id",
)


class PaynkolayClient:
    """Small wrapper around HTTPX that centralizes provider HTTP behavior."""

    def __init__(
        self,
        environment: PaymentEnvironment,
        *,
        timeout: httpx.Timeout | float = 10.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._environment = environment
        self._client = httpx.AsyncClient(
            base_url=environment.base_url,
            timeout=timeout,
            transport=transport,
            headers={
                "Accept": "application/json",
                "X-Merchant-Id": environment.merchant.merchant_id,
                "X-Terminal-Id": environment.merchant.terminal_id,
            },
        )

    @property
    def base_url(self) -> str:
        """Return the provider base URL selected by runtime configuration."""

        return str(self._client.base_url)

    async def post_json(
        self,
        path: str,
        payload: Mapping[str, Any],
    ) -> dict[str, Any]:
        """POST JSON to a provider endpoint and return the decoded object body."""

        response = await self._client.post(path, json=payload)
        response.raise_for_status()
        return _decode_json_object(response.json())

    async def post_form(
        self,
        path: str,
        payload: Mapping[str, object],
    ) -> dict[str, Any]:
        """POST multipart form-data to a provider endpoint and return a JSON object body."""

        files = {
            key: (None, _form_value(value))
            for key, value in payload.items()
        }
        response = await self._client.post(path, files=files)
        response.raise_for_status()
        return _decode_json_object(response.json())

    async def get_json(self, path: str) -> dict[str, Any]:
        """GET JSON from a provider endpoint and return the decoded object body."""

        response = await self._client.get(path)
        response.raise_for_status()
        return _decode_json_object(response.json())

    async def initialize_payment(
        self,
        request: PaymentInitializeRequest,
    ) -> PaymentInitializeResponse:
        """Sign, send, and validate a payment initialization request."""

        canonical_payload = canonicalize_fields(
            request.signature_payload(),
            PAYMENT_INITIALIZE_SIGNATURE_FIELDS,
        )
        signature = generate_hmac_signature(
            secret_key=self._environment.merchant.secret_key,
            canonical_payload=canonical_payload,
        )
        outbound_payload: dict[str, Any] = {
            "merchant_id": request.merchant_id,
            "terminal_id": request.terminal_id,
            "order_id": request.order_id,
            "amount": request.canonical_amount,
            "currency": request.currency.value,
            "callback_url": request.callback_url,
            "card": {
                "brand": request.card.brand.value,
                "pan": request.card.pan.get_secret_value(),
                "expiry_month": request.card.expiry_month,
                "expiry_year": request.card.expiry_year,
                "cvv": request.card.cvv.get_secret_value(),
                "card_holder": request.card.card_holder,
            },
            "requires_3ds": request.requires_3ds,
            "installment_count": request.installment_count,
            "payment_channel": request.payment_channel.value,
            "moto": request.moto,
            "correlation_id": request.correlation_id,
            "signature": signature,
        }
        card_payload = outbound_payload["card"]
        if not isinstance(card_payload, dict):
            raise TypeError("payment request card payload must be a JSON object")
        response_payload = await self.post_json(
            "/payments/initialize",
            outbound_payload,
        )
        return PaymentInitializeResponse(**response_payload)

    def payment_form_payload(
        self,
        request: PaymentInitializeRequest,
        *,
        success_url: str,
        fail_url: str,
        card_holder_ip: str,
        rnd: str,
        customer_key: str = "",
        merchant_customer_no: str = "",
        transaction_type: str = "SALES",
        environment: str = "API",
    ) -> dict[str, str]:
        """Build Paynkolay API v1 multipart form fields for a payment request."""

        if not success_url.startswith("https://"):
            raise ValueError("success_url must use https")
        if not fail_url.startswith("https://"):
            raise ValueError("fail_url must use https")
        if not card_holder_ip.strip():
            raise ValueError("card_holder_ip must not be empty")
        if not rnd.strip():
            raise ValueError("rnd must not be empty")
        if request.installment_count > 1 and request.installment_encoded_value is None:
            raise ValueError(
                "provider installment encoded value is required for installment payments"
            )

        sx = self._environment.merchant.api_key
        merchant_secret_key = self._environment.merchant.secret_key
        hash_data_v2 = generate_payment_request_hash(
            sx=sx,
            client_ref_code=request.order_id,
            amount=request.canonical_amount,
            success_url=success_url,
            fail_url=fail_url,
            rnd=rnd,
            customer_key=customer_key,
            merchant_secret_key=merchant_secret_key,
        )
        return {
            "sx": sx.get_secret_value(),
            "clientRefCode": request.order_id,
            "successUrl": success_url,
            "failUrl": fail_url,
            "amount": request.canonical_amount,
            "installmentNo": str(request.installment_count),
            "cardHolderName": request.card.card_holder,
            "month": f"{request.card.expiry_month:02d}",
            "year": str(request.card.expiry_year),
            "cvv": request.card.cvv.get_secret_value(),
            "cardNumber": request.card.pan.get_secret_value(),
            "use3D": _bool_value(request.requires_3ds),
            "transactionType": transaction_type,
            "cardHolderIP": card_holder_ip.strip(),
            "rnd": rnd,
            "hashDatav2": hash_data_v2,
            "environment": environment,
            "currencyNumber": PAYNKOLAY_CURRENCY_NUMBERS[request.currency],
            "MerchantCustomerNo": merchant_customer_no,
            **(
                {
                    "EncodedValue": (
                        request.installment_encoded_value.get_secret_value()
                    )
                }
                if request.installment_encoded_value is not None
                else {}
            ),
        }

    def installment_form_payload(
        self,
        *,
        amount: Decimal | str,
        card_number: SecretStr | str,
        is_card_valid: bool = True,
    ) -> dict[str, str]:
        """Build Paynkolay installment lookup multipart fields."""

        installment_sx = self._environment.merchant.installment_api_key
        if installment_sx is None:
            raise ValueError("installment API key is not configured")

        canonical_amount = _canonical_amount(amount)
        pan = _secret_value(card_number).strip()
        if not pan.isdigit() or len(pan) not in {8, *range(12, 20)}:
            raise ValueError("installment card number must be an 8-digit BIN or full PAN")
        if is_card_valid and len(pan) < 12:
            raise ValueError("full card PAN is required when is_card_valid is true")

        return {
            "sx": installment_sx.get_secret_value(),
            "amount": canonical_amount,
            "cardNumber": pan,
            "iscardvalid": _bool_value(is_card_valid),
        }

    async def get_installment_options(
        self,
        *,
        amount: Decimal | str,
        card_number: SecretStr | str,
        is_card_valid: bool = True,
    ) -> PaynkolayInstallmentResponse:
        """Fetch card/amount-specific installment quotes from Paynkolay."""

        payload = self.installment_form_payload(
            amount=amount,
            card_number=card_number,
            is_card_valid=is_card_valid,
        )
        response_payload = await self.post_form(PAYNKOLAY_INSTALLMENTS_PATH, payload)
        return PaynkolayInstallmentResponse.model_validate(response_payload)

    async def initialize_payment_form(
        self,
        request: PaymentInitializeRequest,
        *,
        success_url: str,
        fail_url: str,
        card_holder_ip: str,
        rnd: str | None = None,
        customer_key: str = "",
        merchant_customer_no: str = "",
    ) -> dict[str, Any]:
        """Send a Paynkolay API v1 payment request as multipart form-data."""

        effective_rnd = rnd if rnd is not None else datetime.now().strftime("%d-%m-%Y %H:%M:%S")
        payload = self.payment_form_payload(
            request,
            success_url=success_url,
            fail_url=fail_url,
            card_holder_ip=card_holder_ip,
            rnd=effective_rnd,
            customer_key=customer_key,
            merchant_customer_no=merchant_customer_no,
        )
        return await self.post_form(PAYNKOLAY_PAYMENT_PATH, payload)

    def payment_list_form_payload(
        self,
        *,
        start_date: str,
        end_date: str,
        client_ref_code: str,
    ) -> dict[str, str]:
        """Build Paynkolay PaymentList multipart form fields."""

        if not start_date.strip():
            raise ValueError("start_date must not be empty")
        if not end_date.strip():
            raise ValueError("end_date must not be empty")

        sx = self._environment.merchant.api_key
        merchant_secret_key = self._environment.merchant.secret_key
        hash_data_v2 = generate_payment_list_hash(
            sx=sx,
            start_date=start_date,
            end_date=end_date,
            client_ref_code=client_ref_code,
            merchant_secret_key=merchant_secret_key,
        )
        return {
            "sx": sx.get_secret_value(),
            "startDate": start_date,
            "endDate": end_date,
            "clientRefCode": client_ref_code,
            "hashDatav2": hash_data_v2,
        }

    def cancel_refund_form_payload(
        self,
        *,
        reference_code: str,
        transaction_type: PaynkolayCancelRefundType | str,
        amount: Decimal | str,
        trx_date: str,
        sx: SecretStr | str | None = None,
    ) -> dict[str, str]:
        """Build Paynkolay cancel/refund multipart form fields."""

        normalized_reference_code = reference_code.strip()
        if not normalized_reference_code:
            raise ValueError("reference_code must not be empty")
        if not trx_date.strip():
            raise ValueError("trx_date must not be empty")

        normalized_type = PaynkolayCancelRefundType(transaction_type)
        effective_sx = (
            sx
            if sx is not None
            else (
                self._environment.merchant.cancel_refund_api_key
                or self._environment.merchant.api_key
            )
        )
        merchant_secret_key = self._environment.merchant.secret_key
        hash_data_v2 = generate_cancel_refund_hash(
            sx=effective_sx,
            reference_code=normalized_reference_code,
            transaction_type=normalized_type,
            amount=amount,
            trx_date=trx_date,
            merchant_secret_key=merchant_secret_key,
        )
        return {
            "sx": _secret_value(effective_sx),
            "referenceCode": normalized_reference_code,
            "type": normalized_type.value,
            "amount": _form_value(amount),
            "trxDate": trx_date,
            "hashDatav2": hash_data_v2,
        }

    async def cancel_refund_payment(
        self,
        *,
        reference_code: str,
        transaction_type: PaynkolayCancelRefundType | str,
        amount: Decimal | str,
        trx_date: str,
        sx: SecretStr | str | None = None,
    ) -> PaynkolayCancelRefundResult:
        """Send a Paynkolay cancel/refund request and parse the provider result."""

        normalized_type = PaynkolayCancelRefundType(transaction_type)
        payload = self.cancel_refund_form_payload(
            reference_code=reference_code,
            transaction_type=normalized_type,
            amount=amount,
            trx_date=trx_date,
            sx=sx,
        )
        response_payload = await self.post_form(PAYNKOLAY_CANCEL_REFUND_PATH, payload)
        return PaynkolayCancelRefundResult.model_validate(
            {**response_payload, "type": normalized_type.value}
        )

    async def cancel_payment(
        self,
        *,
        reference_code: str,
        amount: Decimal | str,
        trx_date: str,
        sx: SecretStr | str | None = None,
    ) -> PaynkolayCancelRefundResult:
        """Cancel a same-day Paynkolay payment by provider reference code."""

        return await self.cancel_refund_payment(
            reference_code=reference_code,
            transaction_type=PaynkolayCancelRefundType.CANCEL,
            amount=amount,
            trx_date=trx_date,
            sx=sx,
        )

    async def refund_payment(
        self,
        *,
        reference_code: str,
        amount: Decimal | str,
        trx_date: str,
        sx: SecretStr | str | None = None,
    ) -> PaynkolayCancelRefundResult:
        """Refund a Paynkolay payment by provider reference code."""

        return await self.cancel_refund_payment(
            reference_code=reference_code,
            transaction_type=PaynkolayCancelRefundType.REFUND,
            amount=amount,
            trx_date=trx_date,
            sx=sx,
        )

    async def get_transaction_status_from_payment_list(
        self,
        order_id: str,
        *,
        start_date: str,
        end_date: str,
        currency: Currency = Currency.TRY,
    ) -> TransactionStatusResponse:
        """Fetch transaction status through Paynkolay's PaymentList service."""

        normalized_order_id = order_id.strip()
        if not normalized_order_id:
            raise ValueError("order_id must not be empty")

        payload = self.payment_list_form_payload(
            start_date=start_date,
            end_date=end_date,
            client_ref_code=normalized_order_id,
        )
        response_payload = await self.post_form(PAYNKOLAY_PAYMENT_LIST_PATH, payload)
        payment_list = PaynkolayPaymentListResponse.model_validate(response_payload)
        if not payment_list.result.successful:
            raise RuntimeError(
                "Paynkolay PaymentList service failed: "
                f"response_code={payment_list.result.response_code!r}, "
                f"response_data={payment_list.result.response_data!r}"
            )
        matching_rows = payment_list.rows_for_client_ref(normalized_order_id)
        if not matching_rows:
            raise LookupError(
                "Paynkolay PaymentList response did not include "
                f"clientRefCode={normalized_order_id!r}"
            )
        return matching_rows[-1].to_transaction_status_response(currency=currency)

    async def get_transaction_status(self, order_id: str) -> TransactionStatusResponse:
        """Fetch and validate the provider status for one merchant order."""

        normalized_order_id = order_id.strip()
        if not normalized_order_id:
            raise ValueError("order_id must not be empty")

        response_payload = await self.get_json(
            f"/payments/{quote(normalized_order_id, safe='')}/status"
        )
        return TransactionStatusResponse(**response_payload)

    async def aclose(self) -> None:
        """Close the underlying HTTPX connection pool."""

        await self._client.aclose()

    async def __aenter__(self) -> PaynkolayClient:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: object,
    ) -> None:
        await self.aclose()


def _bool_value(value: bool) -> str:
    return "true" if value else "false"


def _form_value(value: object) -> str:
    if isinstance(value, SecretStr):
        return value.get_secret_value()
    if isinstance(value, Decimal):
        return f"{value:.2f}"
    if isinstance(value, bool):
        return _bool_value(value)
    return str(value)


def _canonical_amount(value: Decimal | str) -> str:
    try:
        amount = Decimal(str(value)).quantize(Decimal("0.01"))
    except InvalidOperation as exc:
        raise ValueError("amount must be a valid decimal") from exc
    if amount <= 0:
        raise ValueError("amount must be greater than zero")
    return f"{amount:.2f}"


def _secret_value(value: SecretStr | str) -> str:
    if isinstance(value, SecretStr):
        return value.get_secret_value()
    return value


def _decode_json_object(decoded: Any) -> dict[str, Any]:
    if isinstance(decoded, str):
        try:
            decoded = json.loads(decoded)
        except json.JSONDecodeError as exc:
            raise TypeError("provider response must be a JSON object") from exc
    if not isinstance(decoded, dict):
        raise TypeError("provider response must be a JSON object")
    return decoded
