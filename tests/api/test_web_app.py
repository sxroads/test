from __future__ import annotations

import asyncio
import json
import subprocess
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any, cast

import httpx
import pytest
import pytest_asyncio

from paynkolay_pos.api import payment_list_retry
from paynkolay_pos.api.app import create_app
from paynkolay_pos.api.dependencies import (
    get_external_payment_logger,
    get_installment_provider,
    get_optional_installment_provider,
    get_payment_initializer,
    get_three_ds_automator,
)
from paynkolay_pos.api.installment_provider import InstallmentProviderLookupError
from paynkolay_pos.api.payment_initializer import (
    PaymentInitializationOutcome,
    PaymentProviderInitializationError,
    PaymentProviderStatusVerificationError,
)
from paynkolay_pos.api.routes import parallel_runs, reports
from paynkolay_pos.api.schemas import PaymentFormRequest
from paynkolay_pos.config import (
    build_private_runtime_config_payload,
    load_runtime_settings,
)
from paynkolay_pos.models import (
    Currency,
    PaymentCardInput,
    PaymentInitializeRequest,
    PaymentStatus,
    PaynkolayInstallmentResponse,
    PaynkolayPaymentResult,
    PaynkolayThreeDSInitializeResult,
    TransactionStatusResponse,
)
from paynkolay_pos.reporting import PaymentLogEvent
from paynkolay_pos.scenarios import build_private_scenario_catalog_payload
from paynkolay_pos.testing.card_behaviors import (
    DEFAULT_CARD_BEHAVIOR,
    CardAutomationBehavior,
    CardAutomationStatus,
)
from paynkolay_pos.three_ds import AcsBrowserAutomationResult


@pytest_asyncio.fixture
async def fake_initializer() -> AsyncIterator[FakePaymentInitializer]:
    yield FakePaymentInitializer()


@pytest_asyncio.fixture
async def fake_logger() -> AsyncIterator[FakeExternalPaymentLogger]:
    yield FakeExternalPaymentLogger()


@pytest_asyncio.fixture
async def fake_automator() -> AsyncIterator[FakeThreeDSAutomator]:
    yield FakeThreeDSAutomator()


@pytest_asyncio.fixture
async def client(
    fake_initializer: FakePaymentInitializer,
    fake_logger: FakeExternalPaymentLogger,
    fake_automator: FakeThreeDSAutomator,
) -> AsyncIterator[httpx.AsyncClient]:
    app = create_app()
    app.dependency_overrides[get_payment_initializer] = lambda: fake_initializer
    app.dependency_overrides[get_external_payment_logger] = lambda: fake_logger
    app.dependency_overrides[get_three_ds_automator] = lambda: fake_automator
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport,
        base_url="http://testserver",
    ) as test_client:
        yield test_client


class FakeExternalPaymentLogger:
    def __init__(self) -> None:
        self.events: list[PaymentLogEvent] = []

    async def log(self, event: PaymentLogEvent) -> None:
        self.events.append(event)


class FakeThreeDSAutomator:
    def __init__(self) -> None:
        self.result = AcsBrowserAutomationResult(
            completed=False,
            submitted=False,
            reason="otp_resolution_missing_source",
            screen_classification="sms_manual_required",
            otp_resolution={
                "status": "missing_source",
                "source_type": None,
                "otp_present": False,
                "should_auto_submit": False,
                "reason": "missing source",
            },
        )
        self.calls: list[dict[str, object]] = []
        self.delay_seconds = 0.0
        self.active_calls = 0
        self.max_active_calls = 0

    async def complete(
        self,
        *,
        html: str,
        brand: object,
        configured_otp: object,
        callback_url: str,
    ) -> AcsBrowserAutomationResult:
        self.active_calls += 1
        self.max_active_calls = max(self.max_active_calls, self.active_calls)
        try:
            self.calls.append(
                {
                    "html_length": len(html),
                    "brand": str(brand),
                    "configured_otp_present": configured_otp is not None,
                    "callback_url": callback_url,
                }
            )
            if self.delay_seconds > 0:
                await asyncio.sleep(self.delay_seconds)
            return self.result
        finally:
            self.active_calls -= 1


class FakePaymentInitializer:
    def __init__(
        self,
        *,
        provider_result: PaynkolayThreeDSInitializeResult | PaynkolayPaymentResult | None = None,
        outcomes: list[
            PaynkolayThreeDSInitializeResult | PaynkolayPaymentResult | BaseException
        ] | None = None,
        payment_list_status: TransactionStatusResponse | None = None,
        status_outcomes: list[TransactionStatusResponse | BaseException] | None = None,
        fails: bool = False,
        status_fails: bool = False,
    ) -> None:
        self.provider_result = provider_result or PaynkolayThreeDSInitializeResult.model_validate(
            {"BANK_REQUEST_MESSAGE": "<form>3DS challenge</form>"}
        )
        self.outcomes = outcomes or []
        self.payment_list_status = payment_list_status
        self.status_outcomes = status_outcomes or []
        self.fails = fails
        self.status_fails = status_fails
        self.calls: list[tuple[str, str]] = []
        self.requests: list[PaymentFormRequest] = []
        self.status_calls: list[str] = []

    async def initialize(
        self,
        request: PaymentFormRequest,
        *,
        order_id: str,
        card_holder_ip: str,
    ) -> PaymentInitializationOutcome:
        self.calls.append((order_id, card_holder_ip))
        self.requests.append(request)
        if self.fails:
            raise PaymentProviderInitializationError("provider payment initialization failed")
        provider_result = self.provider_result
        if self.outcomes:
            outcome = self.outcomes.pop(0)
            if isinstance(outcome, BaseException):
                raise outcome
            provider_result = outcome
        return PaymentInitializationOutcome(
            payment_request=_payment_request(request, order_id=order_id),
            provider_result=provider_result,
            success_url="https://merchant.example.test/payments/result/success",
            fail_url="https://merchant.example.test/payments/result/fail",
        )

    async def verify_transaction_status(
        self,
        order_id: str,
        *,
        currency: Currency,
    ) -> TransactionStatusResponse:
        self.status_calls.append(order_id)
        if self.status_outcomes:
            outcome = self.status_outcomes.pop(0)
            if isinstance(outcome, BaseException):
                raise outcome
            return outcome
        if self.status_fails:
            raise PaymentProviderStatusVerificationError(
                "provider payment status verification failed"
            )
        return self.payment_list_status or TransactionStatusResponse(
            order_id=order_id,
            provider_transaction_id="list-ref-1001",
            status=PaymentStatus.CAPTURED,
            amount=Decimal("100.00"),
            currency=currency,
            updated_at=datetime(2026, 7, 7, 12, 0, tzinfo=UTC),
            authorization_code="LISTAUTH",
        )


class FakeInstallmentProvider:
    async def get_options(
        self,
        *,
        amount: Decimal,
        card_number: object,
    ) -> PaynkolayInstallmentResponse:
        return PaynkolayInstallmentResponse.model_validate(
            {
                "PAYMENT_BANK_LIST": [
                    {
                        "INSTALLMENT_AMOUNT": "350.88",
                        "INSTALLMENT": 3,
                        "COMMISION_AMOUNT": "52.63",
                        "COMMISION": "5.00",
                        "TRANSACTION_AMOUNT": amount,
                        "AUTHORIZATION_AMOUNT": "1052.63",
                        "EncodedValue": "opaque-provider-quote",
                        "CURRENCY_CODE": "TRY",
                    }
                ],
                "RESPONSE_DATA": "İşlem Başarılı.",
                "RESPONSE_CODE": 2,
            }
        )


class ParallelInstallmentProvider:
    def __init__(
        self,
        *,
        unavailable_pan_suffixes: set[str] | None = None,
        fail: bool = False,
        delay_seconds: float = 0.0,
    ) -> None:
        self.unavailable_pan_suffixes = unavailable_pan_suffixes or set()
        self.fail = fail
        self.delay_seconds = delay_seconds
        self.calls: list[str] = []
        self.active_calls = 0
        self.max_active_calls = 0

    async def get_options(
        self,
        *,
        amount: Decimal,
        card_number: object,
    ) -> PaynkolayInstallmentResponse:
        pan = cast(Any, card_number).get_secret_value()
        suffix = pan[-4:]
        call_index = len(self.calls) + 1
        self.calls.append(suffix)
        self.active_calls += 1
        self.max_active_calls = max(self.max_active_calls, self.active_calls)
        try:
            if self.delay_seconds:
                await asyncio.sleep(self.delay_seconds)
            if self.fail:
                raise InstallmentProviderLookupError(
                    "provider installment lookup failed"
                )
            installment_count = 2 if suffix in self.unavailable_pan_suffixes else 3
            return PaynkolayInstallmentResponse.model_validate(
                {
                    "PAYMENT_BANK_LIST": [
                        {
                            "INSTALLMENT_AMOUNT": "350.88",
                            "INSTALLMENT": installment_count,
                            "COMMISION_AMOUNT": "52.63",
                            "COMMISION": "5.00",
                            "TRANSACTION_AMOUNT": amount,
                            "AUTHORIZATION_AMOUNT": "1052.63",
                            "EncodedValue": f"opaque-parallel-quote-{call_index}",
                            "CURRENCY_CODE": "TRY",
                        }
                    ],
                    "RESPONSE_DATA": "İşlem Başarılı.",
                    "RESPONSE_CODE": 2,
                }
            )
        finally:
            self.active_calls -= 1


def _payment_request(
    request: PaymentFormRequest,
    *,
    order_id: str,
) -> PaymentInitializeRequest:
    return PaymentInitializeRequest(
        merchant_id="merchant-web",
        terminal_id="terminal-web",
        order_id=order_id,
        amount=request.amount,
        currency=request.currency,
        callback_url="https://merchant.example.test/callbacks/paynkolay",
        card=PaymentCardInput(
            brand=request.card_brand,
            pan=request.card_number,
            expiry_month=request.expiry_month,
            expiry_year=request.expiry_year,
            cvv=request.cvv,
            card_holder=request.card_holder,
        ),
        requires_3ds=request.requires_3ds,
        installment_count=request.installment_count,
        installment_encoded_value=request.installment_encoded_value,
        correlation_id=f"web-{order_id}",
    )


def _payment_result(
    *,
    response_code: str,
    response_data: str,
) -> PaynkolayPaymentResult:
    return PaynkolayPaymentResult.model_validate(
        {
            "RESPONSE_CODE": response_code,
            "RESPONSE_DATA": response_data,
            "USE_3D": "false",
            "RND": "rnd-parallel",
            "MERCHANT_NO": "merchant-web",
            "AUTH_CODE": "AUTHPAR",
            "REFERENCE_CODE": "ref-parallel",
            "CLIENT_REFERENCE_CODE": "parallel-order",
            "TIMESTAMP": "2026-07-07T12:00:00+00:00",
            "TRANSACTION_AMOUNT": "100.00",
            "AUTHORIZATION_AMOUNT": "100.00",
            "INSTALLMENT": 1,
            "CURRENCY_CODE": Currency.TRY,
            "hashDataV2": "hash",
        }
    )


def _runtime_card(
    *,
    alias: str,
    pan: str,
    requires_3ds: bool,
    expected_otp: str | None = None,
) -> dict[str, object]:
    payload: dict[str, object] = {
        "alias": alias,
        "brand": "visa",
        "pan": pan,
        "expiry_month": 12,
        "expiry_year": 2030,
        "cvv": "123",
        "requires_3ds": requires_3ds,
    }
    if expected_otp is not None:
        payload["expected_otp"] = expected_otp
    return payload


def _write_parallel_runtime_config(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    cards: list[dict[str, object]],
) -> Path:
    config_path = tmp_path / "parallel-settings.json"
    config_payload = build_private_runtime_config_payload(card_count=10)
    environments = cast(dict[str, Any], config_payload["environments"])
    dev = cast(dict[str, Any], environments["dev"])
    dev["cards"] = cards
    config_path.write_text(json.dumps(config_payload), encoding="utf-8")
    monkeypatch.setenv("PAYNKOLAY_CONFIG_FILE", str(config_path))
    monkeypatch.setenv("PAYNKOLAY_ENV", "dev")
    return config_path


async def _wait_parallel_run(
    client: httpx.AsyncClient,
    run_id: str,
) -> dict[str, Any]:
    for _ in range(10):
        response = await client.get(f"/api/parallel-runs/{run_id}")
        assert response.status_code == 200
        payload = response.json()
        if payload["status"] != "running":
            return cast(dict[str, Any], payload)
        await asyncio.sleep(0.01)
    raise AssertionError(f"parallel run did not finish: {run_id}")


@pytest.mark.api
@pytest.mark.asyncio
async def test_health_check_returns_ok(client: httpx.AsyncClient) -> None:
    response = await client.get("/health")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "service": "paynkolay-pos-web",
        "version": "0.1.0",
    }


@pytest.mark.api
@pytest.mark.asyncio
async def test_root_renders_payment_screen(client: httpx.AsyncClient) -> None:
    response = await client.get("/")

    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    assert 'id="payment-form"' in response.text
    assert 'rel="icon" href="/static/favicon.svg"' in response.text
    assert 'id="card-list-button"' in response.text
    assert 'id="card-list-body"' in response.text
    assert 'id="card-list-search"' in response.text
    assert 'id="card-list-flow-filter"' in response.text
    assert 'id="card-add-toggle"' in response.text
    assert 'id="card-add-form"' in response.text
    assert 'id="installment-status"' in response.text
    assert 'id="result-payment-list-status"' in response.text
    assert 'id="three-ds-mode-manual"' in response.text
    assert 'id="three-ds-mode-auto"' in response.text


@pytest.mark.api
@pytest.mark.asyncio
async def test_reports_page_renders_dynamic_report_screen(client: httpx.AsyncClient) -> None:
    response = await client.get("/reports")

    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    assert 'id="report-status"' in response.text
    assert 'id="history-status"' in response.text
    assert 'id="credential-run-button"' in response.text
    assert 'id="parallel-evidence-status"' in response.text
    assert 'id="parallel-evidence-runs"' in response.text
    assert 'id="parallel-evidence-detail"' in response.text
    assert "make credential-scenario-report" in response.text
    assert "/static/js/reports.js" in response.text


@pytest.mark.api
@pytest.mark.asyncio
async def test_parallel_page_renders_parallel_run_screen(client: httpx.AsyncClient) -> None:
    response = await client.get("/parallel")

    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    assert 'class="nav-link active" href="/parallel"' in response.text
    assert 'id="parallel-run-button"' in response.text
    assert 'id="parallel-3ds-mode-manual"' not in response.text
    assert 'id="parallel-3ds-mode-auto"' not in response.text
    assert 'id="parallel-selection-body"' in response.text
    assert 'id="parallel-results-body"' in response.text
    assert 'id="parallel-installment-count"' in response.text
    assert 'id="parallel-installment-summary"' in response.text
    assert 'id="parallel-evidence-path"' in response.text
    assert 'id="parallel-success-rate"' in response.text
    assert 'id="parallel-concurrency"' not in response.text
    assert 'name="parallel-profile"' not in response.text
    assert 'id="parallel-acs-concurrency"' not in response.text
    assert 'id="parallel-acs-peak"' in response.text
    assert 'id="parallel-throughput"' in response.text
    assert 'id="parallel-random-count" type="number" min="1" max="150"' in response.text
    assert 'id="parallel-repeat-count" type="number" min="1" max="150"' in response.text
    assert "Parallel 3D Secure runs complete automatically" in response.text
    assert "/static/js/parallel-runs.js?v=parallel-installments-1" in response.text


@pytest.mark.api
@pytest.mark.asyncio
async def test_favicon_redirects_to_static_svg(client: httpx.AsyncClient) -> None:
    response = await client.get("/favicon.ico", follow_redirects=False)

    assert response.status_code == 307
    assert response.headers["location"] == "/static/favicon.svg"


@pytest.mark.api
@pytest.mark.asyncio
async def test_settings_page_renders_dynamic_config_screen(client: httpx.AsyncClient) -> None:
    response = await client.get("/settings")

    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    assert 'id="runtime-status"' in response.text
    assert 'id="settings-cards"' in response.text
    assert 'id="coverage-3ds"' in response.text
    assert 'id="merchant-settings-form"' in response.text
    assert 'id="merchant-no"' in response.text
    assert 'id="payment-sx"' in response.text
    assert "make credential-inputs" in response.text
    assert "/static/js/settings.js" in response.text


@pytest.mark.api
@pytest.mark.asyncio
async def test_result_page_renders_dynamic_lookup_screen(client: httpx.AsyncClient) -> None:
    response = await client.get("/result?order_id=order-web-1001")

    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    assert 'id="result-lookup-form"' in response.text
    assert 'id="lookup-order-id"' in response.text
    assert 'id="result-payment-list-status"' in response.text
    assert 'class="nav-link active" href="/"' in response.text
    assert "/static/js/result.js" in response.text


@pytest.mark.api
@pytest.mark.asyncio
async def test_latest_report_returns_unavailable_when_report_is_missing(
    client: httpx.AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    report_dir = tmp_path / "missing-report"
    monkeypatch.setenv("PAYNKOLAY_ALLURE_REPORT_DIR", str(report_dir))

    response = await client.get("/api/reports/latest")

    assert response.status_code == 200
    assert response.json() == {
        "available": False,
        "report_path": str(report_dir),
        "entrypoint": None,
        "message": "Allure HTML report has not been generated yet.",
    }


@pytest.mark.api
@pytest.mark.asyncio
async def test_latest_report_returns_available_when_index_exists(
    client: httpx.AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    report_dir = tmp_path / "allure-report"
    report_dir.mkdir()
    entrypoint = report_dir / "index.html"
    entrypoint.write_text("<!doctype html><title>Allure</title>", encoding="utf-8")
    monkeypatch.setenv("PAYNKOLAY_ALLURE_REPORT_DIR", str(report_dir))

    response = await client.get("/api/reports/latest")

    assert response.status_code == 200
    assert response.json() == {
        "available": True,
        "report_path": str(report_dir),
        "entrypoint": str(entrypoint),
        "message": "Allure HTML report is available.",
    }


@pytest.mark.api
@pytest.mark.asyncio
async def test_report_history_returns_unavailable_when_results_are_missing(
    client: httpx.AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    results_dir = tmp_path / "missing-results"
    monkeypatch.setenv("PAYNKOLAY_ALLURE_RESULTS_DIR", str(results_dir))

    response = await client.get("/api/reports/history")

    assert response.status_code == 200
    assert response.json() == {
        "available": False,
        "results_path": str(results_dir),
        "latest": None,
        "message": "Allure results have not been generated yet.",
    }


@pytest.mark.api
@pytest.mark.asyncio
async def test_report_history_summarizes_latest_allure_results(
    client: httpx.AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    results_dir = tmp_path / "allure-results"
    results_dir.mkdir()
    monkeypatch.setenv("PAYNKOLAY_ALLURE_RESULTS_DIR", str(results_dir))
    (results_dir / "passed-result.json").write_text(
        json.dumps(
            {
                "name": "test_authorized_payment",
                "status": "passed",
                "start": 1783510684000,
                "stop": 1783510684050,
                "labels": [{"name": "suite", "value": "test_payments"}],
            }
        ),
        encoding="utf-8",
    )
    (results_dir / "failed-result.json").write_text(
        json.dumps(
            {
                "name": "test_invalid_cvv",
                "status": "failed",
                "start": 1783510684100,
                "stop": 1783510684200,
                "labels": [{"name": "suite", "value": "test_payments"}],
            }
        ),
        encoding="utf-8",
    )

    response = await client.get("/api/reports/history")

    assert response.status_code == 200
    payload = response.json()
    assert payload["available"] is True
    assert payload["results_path"] == str(results_dir)
    assert payload["latest"]["total"] == 2
    assert payload["latest"]["passed"] == 1
    assert payload["latest"]["failed"] == 1
    assert payload["latest"]["duration_ms"] == 200
    assert payload["latest"]["recent_tests"][0]["name"] == "test_invalid_cvv"
    assert payload["latest"]["recent_tests"][0]["duration_ms"] == 100


@pytest.mark.api
@pytest.mark.asyncio
async def test_parallel_evidence_returns_unavailable_when_missing(
    client: httpx.AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    evidence_dir = tmp_path / "missing-parallel-runs"
    monkeypatch.setenv("PAYNKOLAY_PARALLEL_EVIDENCE_DIR", str(evidence_dir))

    response = await client.get("/api/reports/parallel-runs")

    assert response.status_code == 200
    assert response.json() == {
        "available": False,
        "evidence_path": str(evidence_dir),
        "runs": [],
        "message": "Parallel run evidence has not been generated yet.",
    }


@pytest.mark.api
@pytest.mark.asyncio
async def test_parallel_evidence_summarizes_persisted_runs(
    client: httpx.AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    evidence_dir = tmp_path / "parallel-runs"
    evidence_dir.mkdir()
    monkeypatch.setenv("PAYNKOLAY_PARALLEL_EVIDENCE_DIR", str(evidence_dir))
    (evidence_dir / "bad.json").write_text("{not-json", encoding="utf-8")
    run_path = evidence_dir / "run-1001.json"
    run_path.write_text(
        json.dumps(
            {
                "event": "parallel_run_evidence",
                "run": {
                    "run_id": "run-1001",
                    "status": "completed",
                    "total": 2,
                    "completed": 2,
                    "failed": 0,
                    "finished_at": "2026-07-16T06:38:44.485024+00:00",
                    "items": [
                        {"classification": "completed"},
                        {"classification": "completed"},
                    ],
                },
            }
        ),
        encoding="utf-8",
    )

    response = await client.get("/api/reports/parallel-runs")

    assert response.status_code == 200
    assert response.json() == {
        "available": True,
        "evidence_path": str(evidence_dir),
        "runs": [
            {
                "run_id": "run-1001",
                "status": "completed",
                "total": 2,
                "completed": 2,
                "failed": 0,
                "finished_at": "2026-07-16T06:38:44.485024+00:00",
                "evidence_path": str(run_path),
                "classifications": {"completed": 2},
            }
        ],
        "message": "Parallel run evidence is available.",
    }


@pytest.mark.api
@pytest.mark.asyncio
async def test_parallel_evidence_detail_returns_sanitized_document(
    client: httpx.AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    evidence_dir = tmp_path / "parallel-runs"
    evidence_dir.mkdir()
    monkeypatch.setenv("PAYNKOLAY_PARALLEL_EVIDENCE_DIR", str(evidence_dir))
    run_path = evidence_dir / "run-1001.json"
    evidence = {
        "event": "parallel_run_evidence",
        "run": {
            "run_id": "run-1001",
            "status": "completed",
            "items": [{"classification": "completed", "masked_pan": "411111******1111"}],
        },
    }
    run_path.write_text(json.dumps(evidence), encoding="utf-8")

    response = await client.get("/api/reports/parallel-runs/run-1001")

    assert response.status_code == 200
    assert response.json() == {
        "run_id": "run-1001",
        "evidence_path": str(run_path),
        "evidence": evidence,
    }
    assert "4111111111111111" not in response.text


@pytest.mark.api
@pytest.mark.asyncio
async def test_parallel_evidence_detail_rejects_unknown_or_invalid_run_id(
    client: httpx.AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    evidence_dir = tmp_path / "parallel-runs"
    evidence_dir.mkdir()
    monkeypatch.setenv("PAYNKOLAY_PARALLEL_EVIDENCE_DIR", str(evidence_dir))

    missing_response = await client.get("/api/reports/parallel-runs/missing-run")
    invalid_response = await client.get("/api/reports/parallel-runs/..%2Fsecret")

    assert missing_response.status_code == 404
    assert invalid_response.status_code == 404


@pytest.mark.api
@pytest.mark.asyncio
async def test_credential_report_run_status_starts_idle(client: httpx.AsyncClient) -> None:
    response = await client.get("/api/reports/credential-run")

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "idle"
    assert payload["command"] == ["make", "credential-scenario-report"]
    assert payload["exit_code"] is None


@pytest.mark.api
@pytest.mark.asyncio
async def test_credential_report_run_executes_fixed_command(
    client: httpx.AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, ...]] = []

    def fake_run_command(command: tuple[str, ...]) -> subprocess.CompletedProcess[str]:
        calls.append(command)
        return subprocess.CompletedProcess(command, 0, stdout="77 passed", stderr="")

    monkeypatch.setattr(reports, "_run_command", fake_run_command)

    response = await client.post("/api/reports/credential-run")

    assert response.status_code == 202
    assert response.json()["status"] == "running"
    status_response = await client.get("/api/reports/credential-run")
    payload = status_response.json()
    assert calls == [("make", "credential-scenario-report")]
    assert payload["status"] == "passed"
    assert payload["exit_code"] == 0
    assert payload["output_tail"] == "77 passed"


@pytest.mark.api
@pytest.mark.asyncio
async def test_config_route_exposes_safe_defaults_without_runtime_settings(
    client: httpx.AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("PAYNKOLAY_CONFIG_FILE", raising=False)

    response = await client.get("/api/config")

    assert response.status_code == 200
    payload = response.json()
    assert payload["runtime_configured"] is False
    assert payload["supported_currencies"] == ["TRY", "USD", "EUR"]
    assert payload["supported_card_brands"] == ["visa", "mastercard", "troy"]
    assert payload["payment_channels"] == ["e_commerce", "moto"]
    assert payload["card_aliases"] == []


@pytest.mark.api
@pytest.mark.asyncio
async def test_cards_route_requires_runtime_settings(
    client: httpx.AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("PAYNKOLAY_CONFIG_FILE", raising=False)

    response = await client.get("/api/cards")

    assert response.status_code == 503
    assert "runtime payment configuration is unavailable" in response.json()["detail"]


@pytest.mark.api
@pytest.mark.asyncio
async def test_cards_route_returns_form_fill_test_cards(
    client: httpx.AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    config_path = tmp_path / "settings.json"
    config_payload = build_private_runtime_config_payload(card_count=10)
    environments = cast(dict[str, Any], config_payload["environments"])
    dev = cast(dict[str, Any], environments["dev"])
    cards = cast(list[dict[str, Any]], dev["cards"])
    cards[0].update(
        {
            "alias": "ui_card_3ds",
            "brand": "visa",
            "pan": "4111111111111111",
            "expiry_month": 1,
            "expiry_year": 2030,
            "cvv": "123",
            "requires_3ds": True,
            "expected_otp": "123456",
        }
    )
    cards[1].update(
        {
            "alias": "ui_card_moto",
            "brand": "mastercard",
            "pan": "5555555555554444",
            "expiry_month": 12,
            "expiry_year": 2031,
            "cvv": "999",
            "requires_3ds": False,
            "expected_otp": None,
        }
    )
    config_path.write_text(json.dumps(config_payload), encoding="utf-8")
    monkeypatch.setenv("PAYNKOLAY_CONFIG_FILE", str(config_path))

    response = await client.get("/api/cards")

    assert response.status_code == 200
    payload = response.json()
    assert payload["environment"] == "dev"
    assert payload["cards"][0] == {
        "alias": "ui_card_3ds",
        "brand": "visa",
        "flow_type": "secure",
        "card_number": "4111111111111111",
        "cvv": "123",
        "expiry_month": 1,
        "expiry_year": 2030,
        "card_holder": "PAYNKOLAY TEST",
        "requires_3ds": True,
        "has_expected_otp": True,
        "automation_status": "unknown",
        "automation_reason": "No live UAT automation behavior has been recorded for this alias.",
        "diagnostic_class": "unknown",
        "automatic_success_candidate": True,
    }
    assert payload["cards"][1]["alias"] == "ui_card_moto"
    assert payload["cards"][1]["flow_type"] == "moto"
    assert payload["cards"][1]["requires_3ds"] is False
    assert payload["cards"][1]["has_expected_otp"] is False
    assert payload["cards"][1]["automation_status"] == "unknown"


@pytest.mark.api
@pytest.mark.asyncio
async def test_cards_route_appends_new_moto_card_to_runtime_config(
    client: httpx.AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    config_path = tmp_path / "settings.json"
    config_payload = build_private_runtime_config_payload(card_count=10)
    config_path.write_text(json.dumps(config_payload), encoding="utf-8")
    monkeypatch.setenv("PAYNKOLAY_CONFIG_FILE", str(config_path))

    response = await client.post(
        "/api/cards",
        json={
            "alias": "manual_moto_card",
            "brand": "visa",
            "card_number": "4111111111111234",
            "expiry_month": 10,
            "expiry_year": 2030,
            "cvv": "321",
            "flow_type": "moto",
        },
    )

    assert response.status_code == 201
    payload = response.json()
    assert payload["alias"] == "manual_moto_card"
    assert payload["flow_type"] == "moto"
    updated = json.loads(config_path.read_text(encoding="utf-8"))
    cards = updated["environments"]["dev"]["cards"]
    assert cards[-1] == {
        "alias": "manual_moto_card",
        "brand": "visa",
        "pan": "4111111111111234",
        "expiry_month": 10,
        "expiry_year": 2030,
        "cvv": "321",
        "requires_3ds": False,
    }


@pytest.mark.api
@pytest.mark.asyncio
async def test_cards_route_appends_new_3ds_card_with_otp(
    client: httpx.AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    config_path = tmp_path / "settings.json"
    config_payload = build_private_runtime_config_payload(card_count=10)
    config_path.write_text(json.dumps(config_payload), encoding="utf-8")
    monkeypatch.setenv("PAYNKOLAY_CONFIG_FILE", str(config_path))

    response = await client.post(
        "/api/cards",
        json={
            "alias": "manual_3ds_card",
            "brand": "mastercard",
            "card_number": "5555555555554444",
            "expiry_month": 11,
            "expiry_year": 2031,
            "cvv": "999",
            "flow_type": "secure",
            "expected_otp": "123456",
        },
    )

    assert response.status_code == 201
    payload = response.json()
    assert payload["alias"] == "manual_3ds_card"
    assert payload["flow_type"] == "secure"
    assert payload["requires_3ds"] is True
    updated = json.loads(config_path.read_text(encoding="utf-8"))
    cards = updated["environments"]["dev"]["cards"]
    assert cards[-1]["expected_otp"] == "123456"


@pytest.mark.api
@pytest.mark.asyncio
async def test_cards_route_rejects_duplicate_alias(
    client: httpx.AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    config_path = tmp_path / "settings.json"
    config_payload = build_private_runtime_config_payload(card_count=10)
    environments = cast(dict[str, Any], config_payload["environments"])
    dev = cast(dict[str, Any], environments["dev"])
    cards = cast(list[dict[str, Any]], dev["cards"])
    duplicate_alias = str(cards[0]["alias"])
    config_path.write_text(json.dumps(config_payload), encoding="utf-8")
    monkeypatch.setenv("PAYNKOLAY_CONFIG_FILE", str(config_path))

    response = await client.post(
        "/api/cards",
        json={
            "alias": duplicate_alias,
            "brand": "visa",
            "card_number": "4111111111111234",
            "expiry_month": 10,
            "expiry_year": 2030,
            "cvv": "321",
            "flow_type": "moto",
        },
    )

    assert response.status_code == 409
    assert "card alias already exists" in response.json()["detail"]


@pytest.mark.api
@pytest.mark.asyncio
async def test_cards_route_appends_new_3ds_card_without_otp(
    client: httpx.AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    config_path = tmp_path / "settings.json"
    config_payload = build_private_runtime_config_payload(card_count=10)
    config_path.write_text(json.dumps(config_payload), encoding="utf-8")
    monkeypatch.setenv("PAYNKOLAY_CONFIG_FILE", str(config_path))

    response = await client.post(
        "/api/cards",
        json={
            "alias": "manual_3ds_without_otp",
            "brand": "visa",
            "card_number": "4111111111111234",
            "expiry_month": 10,
            "expiry_year": 2030,
            "cvv": "321",
            "flow_type": "secure",
        },
    )

    assert response.status_code == 201
    payload = response.json()
    assert payload["alias"] == "manual_3ds_without_otp"
    assert payload["flow_type"] == "secure"
    assert payload["requires_3ds"] is True
    assert payload["has_expected_otp"] is False
    assert payload["automation_status"] == "unknown"
    assert payload["automatic_success_candidate"] is True
    updated = json.loads(config_path.read_text(encoding="utf-8"))
    cards = updated["environments"]["dev"]["cards"]
    assert "expected_otp" not in cards[-1]


@pytest.mark.api
@pytest.mark.asyncio
async def test_cards_route_rejects_non_numeric_otp_for_3ds_card(
    client: httpx.AsyncClient,
) -> None:
    response = await client.post(
        "/api/cards",
        json={
            "alias": "manual_3ds_bad_otp",
            "brand": "visa",
            "card_number": "4111111111111234",
            "expiry_month": 10,
            "expiry_year": 2030,
            "cvv": "321",
            "flow_type": "secure",
            "expected_otp": "12AB56",
        },
    )

    assert response.status_code == 422
    assert "expected_otp must contain digits only" in response.text


@pytest.mark.api
@pytest.mark.asyncio
async def test_parallel_run_manual_mode_repeats_selected_cards(
    client: httpx.AsyncClient,
    fake_initializer: FakePaymentInitializer,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    evidence_dir = tmp_path / "parallel-evidence"
    monkeypatch.setenv("PAYNKOLAY_PARALLEL_EVIDENCE_DIR", str(evidence_dir))
    _write_parallel_runtime_config(
        monkeypatch,
        tmp_path,
        [
            _runtime_card(
                alias="parallel_moto",
                pan="4111111111111111",
                requires_3ds=False,
            ),
        ],
    )
    fake_initializer.provider_result = _payment_result(
        response_code="2",
        response_data="Islem Basarili",
    )

    response = await client.post(
        "/api/parallel-runs",
        json={
            "mode": "manual",
            "amount": "100.00",
            "currency": "TRY",
            "concurrency": 2,
            "manual_cards": [{"alias": "parallel_moto", "repeat_count": 2}],
        },
    )

    assert response.status_code == 202
    payload = await _wait_parallel_run(client, response.json()["run_id"])
    assert payload["status"] == "completed"
    assert payload["total"] == 2
    assert payload["completed"] == 2
    assert payload["failed"] == 0
    assert [item["attempt_index"] for item in payload["items"]] == [1, 2]
    assert {item["classification"] for item in payload["items"]} == {"completed"}
    assert all(item["payment_list_status"] == "captured" for item in payload["items"])
    assert all(item["payment_list"]["status"] == "captured" for item in payload["items"])
    assert all(
        item["payment_list"]["provider_transaction_id"] == "list-ref-1001"
        for item in payload["items"]
    )
    assert all(
        item["payment_list"]["authorization_code"] == "LISTAUTH"
        for item in payload["items"]
    )
    assert all(item["automation_status"] == "unknown" for item in payload["items"])
    assert all(item["diagnostic_class"] == "unknown" for item in payload["items"])
    assert all(item["automatic_success_candidate"] is True for item in payload["items"])
    assert payload["evidence_path"] == str(evidence_dir / f"{payload['run_id']}.json")
    evidence = json.loads(Path(payload["evidence_path"]).read_text(encoding="utf-8"))
    assert evidence["event"] == "parallel_run_evidence"
    assert evidence["run"]["run_id"] == payload["run_id"]
    evidence_item = evidence["run"]["items"][0]
    assert evidence_item["payment_list_status"] == "captured"
    assert evidence_item["payment_list"] == {
        "status": "captured",
        "provider_transaction_id": "list-ref-1001",
        "authorization_code": "LISTAUTH",
        "failure_code": None,
        "updated_at": "2026-07-07T12:00:00+00:00",
        "error": None,
    }
    assert evidence_item["automation_status"] == "unknown"
    assert evidence_item["automation_reason"] == (
        "No live UAT automation behavior has been recorded for this alias."
    )
    assert evidence_item["diagnostic_class"] == "unknown"
    assert evidence_item["automatic_success_candidate"] is True
    assert "4111111111111111" not in json.dumps(evidence)
    assert len(fake_initializer.calls) == 2
    assert "4111111111111111" not in response.text


@pytest.mark.api
@pytest.mark.asyncio
async def test_parallel_installment_run_uses_fresh_quotes_with_bounded_lookup_concurrency(
    fake_initializer: FakePaymentInitializer,
    fake_automator: FakeThreeDSAutomator,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    evidence_dir = tmp_path / "parallel-installment-evidence"
    monkeypatch.setenv("PAYNKOLAY_PARALLEL_EVIDENCE_DIR", str(evidence_dir))
    _write_parallel_runtime_config(
        monkeypatch,
        tmp_path,
        [
            _runtime_card(
                alias="parallel_installment_moto",
                pan="4111111111111111",
                requires_3ds=False,
            ),
        ],
    )
    fake_initializer.provider_result = _payment_result(
        response_code="2",
        response_data="Islem Basarili",
    )
    installment_provider = ParallelInstallmentProvider(delay_seconds=0.02)
    app = create_app()
    app.dependency_overrides[get_payment_initializer] = lambda: fake_initializer
    app.dependency_overrides[get_three_ds_automator] = lambda: fake_automator
    app.dependency_overrides[get_optional_installment_provider] = (
        lambda: installment_provider
    )
    transport = httpx.ASGITransport(app=app)

    async with httpx.AsyncClient(
        transport=transport,
        base_url="http://testserver",
    ) as test_client:
        response = await test_client.post(
            "/api/parallel-runs",
            json={
                "mode": "manual",
                "amount": "1000.00",
                "currency": "TRY",
                "installment_count": 3,
                "concurrency": 10,
                "manual_cards": [
                    {"alias": "parallel_installment_moto", "repeat_count": 8}
                ],
            },
        )
        assert response.status_code == 202
        payload = await _wait_parallel_run(test_client, response.json()["run_id"])

    assert payload["status"] == "completed"
    assert payload["installment_count"] == 3
    assert len(installment_provider.calls) == 8
    assert installment_provider.max_active_calls == 5
    assert len(fake_initializer.requests) == 8
    encoded_values = {
        request.installment_encoded_value.get_secret_value()
        for request in fake_initializer.requests
        if request.installment_encoded_value is not None
    }
    assert len(encoded_values) == 8
    assert all(request.installment_count == 3 for request in fake_initializer.requests)
    assert all(item["installment_count"] == 3 for item in payload["items"])
    assert all(item["installment_source"] == "paynkolay_uat" for item in payload["items"])
    assert all(
        item["stage_timings"]["installment_lookup_ms"] is not None
        for item in payload["items"]
    )
    evidence = Path(payload["evidence_path"]).read_text(encoding="utf-8")
    assert "opaque-parallel-quote" not in evidence
    assert "4111111111111111" not in evidence


@pytest.mark.api
@pytest.mark.asyncio
async def test_parallel_single_payment_does_not_lookup_installments(
    fake_initializer: FakePaymentInitializer,
    fake_automator: FakeThreeDSAutomator,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _write_parallel_runtime_config(
        monkeypatch,
        tmp_path,
        [
            _runtime_card(
                alias="parallel_single_payment",
                pan="4111111111111111",
                requires_3ds=False,
            ),
        ],
    )
    fake_initializer.provider_result = _payment_result(
        response_code="2",
        response_data="Islem Basarili",
    )
    installment_provider = ParallelInstallmentProvider(fail=True)
    app = create_app()
    app.dependency_overrides[get_payment_initializer] = lambda: fake_initializer
    app.dependency_overrides[get_three_ds_automator] = lambda: fake_automator
    app.dependency_overrides[get_optional_installment_provider] = (
        lambda: installment_provider
    )
    transport = httpx.ASGITransport(app=app)

    async with httpx.AsyncClient(
        transport=transport,
        base_url="http://testserver",
    ) as test_client:
        response = await test_client.post(
            "/api/parallel-runs",
            json={
                "mode": "manual",
                "amount": "100.00",
                "currency": "TRY",
                "concurrency": 1,
                "manual_cards": [
                    {"alias": "parallel_single_payment", "repeat_count": 1}
                ],
            },
        )
        payload = await _wait_parallel_run(test_client, response.json()["run_id"])

    assert payload["status"] == "completed"
    assert payload["installment_count"] == 1
    assert payload["items"][0]["stage_timings"]["installment_lookup_ms"] == 0
    assert installment_provider.calls == []


@pytest.mark.api
@pytest.mark.asyncio
async def test_parallel_installment_unavailable_fails_only_affected_item(
    fake_initializer: FakePaymentInitializer,
    fake_automator: FakeThreeDSAutomator,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _write_parallel_runtime_config(
        monkeypatch,
        tmp_path,
        [
            _runtime_card(
                alias="installment_supported",
                pan="4111111111111111",
                requires_3ds=False,
            ),
            _runtime_card(
                alias="installment_unsupported",
                pan="5555555555554444",
                requires_3ds=False,
            ),
        ],
    )
    fake_initializer.provider_result = _payment_result(
        response_code="2",
        response_data="Islem Basarili",
    )
    installment_provider = ParallelInstallmentProvider(
        unavailable_pan_suffixes={"4444"}
    )
    app = create_app()
    app.dependency_overrides[get_payment_initializer] = lambda: fake_initializer
    app.dependency_overrides[get_three_ds_automator] = lambda: fake_automator
    app.dependency_overrides[get_optional_installment_provider] = (
        lambda: installment_provider
    )
    transport = httpx.ASGITransport(app=app)

    async with httpx.AsyncClient(
        transport=transport,
        base_url="http://testserver",
    ) as test_client:
        response = await test_client.post(
            "/api/parallel-runs",
            json={
                "mode": "manual",
                "amount": "1000.00",
                "currency": "TRY",
                "installment_count": 3,
                "concurrency": 2,
                "manual_cards": [
                    {"alias": "installment_supported", "repeat_count": 1},
                    {"alias": "installment_unsupported", "repeat_count": 1},
                ],
            },
        )
        payload = await _wait_parallel_run(test_client, response.json()["run_id"])

    assert payload["status"] == "completed_with_failures"
    assert payload["completed"] == 1
    assert payload["failed"] == 1
    assert [item["classification"] for item in payload["items"]] == [
        "completed",
        "installment_option_unavailable",
    ]
    assert len(fake_initializer.calls) == 1


@pytest.mark.api
@pytest.mark.asyncio
async def test_parallel_installment_lookup_failure_skips_payment_initialization(
    fake_initializer: FakePaymentInitializer,
    fake_automator: FakeThreeDSAutomator,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _write_parallel_runtime_config(
        monkeypatch,
        tmp_path,
        [
            _runtime_card(
                alias="installment_lookup_failure",
                pan="4111111111111111",
                requires_3ds=False,
            ),
        ],
    )
    installment_provider = ParallelInstallmentProvider(fail=True)
    app = create_app()
    app.dependency_overrides[get_payment_initializer] = lambda: fake_initializer
    app.dependency_overrides[get_three_ds_automator] = lambda: fake_automator
    app.dependency_overrides[get_optional_installment_provider] = (
        lambda: installment_provider
    )
    transport = httpx.ASGITransport(app=app)

    async with httpx.AsyncClient(
        transport=transport,
        base_url="http://testserver",
    ) as test_client:
        response = await test_client.post(
            "/api/parallel-runs",
            json={
                "mode": "manual",
                "amount": "1000.00",
                "currency": "TRY",
                "installment_count": 3,
                "concurrency": 1,
                "manual_cards": [
                    {"alias": "installment_lookup_failure", "repeat_count": 1}
                ],
            },
        )
        payload = await _wait_parallel_run(test_client, response.json()["run_id"])

    assert payload["status"] == "completed_with_failures"
    assert payload["items"][0]["classification"] == "installment_lookup_failed"
    assert payload["items"][0]["installment_source"] == "paynkolay_uat"
    assert fake_initializer.calls == []


@pytest.mark.api
@pytest.mark.asyncio
async def test_parallel_run_manual_mode_accepts_twenty_items(
    client: httpx.AsyncClient,
    fake_initializer: FakePaymentInitializer,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _write_parallel_runtime_config(
        monkeypatch,
        tmp_path,
        [
            _runtime_card(
                alias="parallel_moto",
                pan="4111111111111111",
                requires_3ds=False,
            ),
        ],
    )
    fake_initializer.provider_result = _payment_result(
        response_code="2",
        response_data="Islem Basarili",
    )

    response = await client.post(
        "/api/parallel-runs",
        json={
            "mode": "manual",
            "amount": "100.00",
            "currency": "TRY",
            "concurrency": 20,
            "manual_cards": [{"alias": "parallel_moto", "repeat_count": 20}],
        },
    )

    assert response.status_code == 202
    payload = await _wait_parallel_run(client, response.json()["run_id"])
    assert payload["status"] == "completed"
    assert payload["total"] == 20
    assert payload["completed"] == 20
    assert payload["failed"] == 0
    assert len(fake_initializer.calls) == 20


@pytest.mark.api
@pytest.mark.asyncio
async def test_parallel_run_records_3ds_automation_failure_without_stopping_run(
    client: httpx.AsyncClient,
    fake_initializer: FakePaymentInitializer,
    fake_automator: FakeThreeDSAutomator,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _write_parallel_runtime_config(
        monkeypatch,
        tmp_path,
        [
            _runtime_card(
                alias="parallel_3ds",
                pan="5555555555554444",
                requires_3ds=True,
                expected_otp="123456",
            ),
        ],
    )

    response = await client.post(
        "/api/parallel-runs",
        json={
            "mode": "manual",
            "amount": "50.00",
            "currency": "TRY",
            "concurrency": 1,
            "auto_complete_3ds": True,
            "manual_cards": [{"alias": "parallel_3ds", "repeat_count": 1}],
        },
    )

    assert response.status_code == 202
    payload = await _wait_parallel_run(client, response.json()["run_id"])
    assert payload["status"] == "completed_with_failures"
    assert payload["items"][0]["classification"] == "acs_manual_required"
    assert payload["items"][0]["requires_3ds"] is True
    assert payload["items"][0]["three_ds_url"].startswith("/payments/batch-")
    assert payload["items"][0]["three_ds_automation"]["status"] == "failed"
    assert fake_automator.calls == [
        {
            "html_length": len("<form>3DS challenge</form>"),
            "brand": "visa",
            "configured_otp_present": True,
            "callback_url": "https://merchant.example.test/payments/result/success",
        }
    ]
    assert fake_initializer.status_calls == []


@pytest.mark.api
@pytest.mark.asyncio
async def test_parallel_run_leaves_3ds_pending_when_auto_completion_is_disabled(
    client: httpx.AsyncClient,
    fake_automator: FakeThreeDSAutomator,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _write_parallel_runtime_config(
        monkeypatch,
        tmp_path,
        [
            _runtime_card(
                alias="parallel_3ds",
                pan="5555555555554444",
                requires_3ds=True,
                expected_otp="123456",
            ),
        ],
    )

    response = await client.post(
        "/api/parallel-runs",
        json={
            "mode": "manual",
            "amount": "50.00",
            "currency": "TRY",
            "concurrency": 1,
            "manual_cards": [{"alias": "parallel_3ds", "repeat_count": 1}],
        },
    )

    assert response.status_code == 202
    payload = await _wait_parallel_run(client, response.json()["run_id"])
    assert payload["status"] == "completed_with_failures"
    assert payload["items"][0]["classification"] == "pending_3ds"
    assert payload["items"][0]["three_ds_automation"] is None
    assert fake_automator.calls == []


@pytest.mark.api
@pytest.mark.asyncio
async def test_parallel_run_completes_3ds_item_after_automation_submit(
    client: httpx.AsyncClient,
    fake_initializer: FakePaymentInitializer,
    fake_automator: FakeThreeDSAutomator,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _write_parallel_runtime_config(
        monkeypatch,
        tmp_path,
        [
            _runtime_card(
                alias="parallel_3ds",
                pan="5555555555554444",
                requires_3ds=True,
                expected_otp="123456",
            ),
        ],
    )
    fake_automator.result = AcsBrowserAutomationResult(
        completed=True,
        submitted=True,
        returned_to_callback=True,
        reason="otp_submitted",
        screen_classification="static_config_otp",
        otp_resolution={
            "status": "ready",
            "source_type": "static_config",
            "otp_present": True,
            "should_auto_submit": True,
            "reason": "resolved OTP from configured test card metadata",
        },
    )

    response = await client.post(
        "/api/parallel-runs",
        json={
            "mode": "manual",
            "amount": "50.00",
            "currency": "TRY",
            "concurrency": 1,
            "auto_complete_3ds": True,
            "manual_cards": [{"alias": "parallel_3ds", "repeat_count": 1}],
        },
    )

    assert response.status_code == 202
    payload = await _wait_parallel_run(client, response.json()["run_id"])
    assert payload["status"] == "completed"
    assert payload["items"][0]["classification"] == "completed"
    assert payload["items"][0]["payment_list_status"] == "captured"
    assert all(
        value is not None and value >= 0
        for value in payload["items"][0]["stage_timings"].values()
    )
    assert payload["metrics"]["elapsed_ms"] is not None
    assert payload["metrics"]["throughput_per_second"] is not None
    assert payload["metrics"]["peak_active_items"] == 1
    assert payload["acs_scheduler"]["profile"] == "stable"
    assert payload["items"][0]["three_ds_automation"] == {
        "status": "completed",
        "submitted": True,
        "classification": "static_config_otp",
        "reason": "otp_submitted",
        "otp_source_type": "static_config",
        "otp_present": True,
        "should_auto_submit": True,
        "final_url": None,
    }
    assert fake_initializer.status_calls == [payload["items"][0]["order_id"]]


@pytest.mark.api
@pytest.mark.asyncio
async def test_parallel_run_limits_automatic_3ds_browser_concurrency(
    client: httpx.AsyncClient,
    fake_automator: FakeThreeDSAutomator,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(
        "paynkolay_pos.api.acs_scheduler.LOAD_LAUNCH_GAP_SECONDS",
        0.0,
    )
    _write_parallel_runtime_config(
        monkeypatch,
        tmp_path,
        [
            _runtime_card(
                alias="parallel_3ds",
                pan="5555555555554444",
                requires_3ds=True,
                expected_otp="123456",
            ),
        ],
    )
    fake_automator.delay_seconds = 0.01
    fake_automator.result = AcsBrowserAutomationResult(
        completed=True,
        submitted=True,
        returned_to_callback=True,
        reason="otp_submitted",
        screen_classification="static_config_otp",
        otp_resolution={
            "status": "ready",
            "source_type": "static_config",
            "otp_present": True,
            "should_auto_submit": True,
            "reason": "resolved OTP from configured test card metadata",
        },
    )

    response = await client.post(
        "/api/parallel-runs",
        json={
            "mode": "manual",
            "amount": "50.00",
            "currency": "TRY",
            "concurrency": 10,
            "execution_profile": "load",
            "acs_concurrency": 4,
            "auto_complete_3ds": True,
            "manual_cards": [{"alias": "parallel_3ds", "repeat_count": 10}],
        },
    )

    assert response.status_code == 202
    payload = await _wait_parallel_run(client, response.json()["run_id"])
    assert payload["status"] == "completed"
    assert payload["completed"] == 10
    assert len(fake_automator.calls) == 10
    assert 2 <= fake_automator.max_active_calls <= 4
    assert payload["acs_scheduler"]["requested_concurrency"] == 4
    assert payload["acs_scheduler"]["peak_concurrency"] <= 4
    assert payload["acs_scheduler"]["pools"]["card:parallel_3ds"] == {
        "initial_limit": 2,
        "final_limit": 4,
        "maximum_limit": 4,
        "peak_concurrency": fake_automator.max_active_calls,
    }


@pytest.mark.api
@pytest.mark.asyncio
async def test_parallel_run_serializes_diagnostic_3ds_card_repeats(
    client: httpx.AsyncClient,
    fake_automator: FakeThreeDSAutomator,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    def fake_behavior_for_alias(alias: str) -> CardAutomationBehavior:
        if alias == "diagnostic_3ds_card":
            return CardAutomationBehavior(
                status=CardAutomationStatus.AUTOMATION_DIAGNOSTIC,
                reason="test diagnostic behavior",
                diagnostic_class="awaiting_provider_finalization",
            )
        return DEFAULT_CARD_BEHAVIOR

    monkeypatch.setattr(parallel_runs, "behavior_for_alias", fake_behavior_for_alias)
    _write_parallel_runtime_config(
        monkeypatch,
        tmp_path,
        [
            _runtime_card(
                alias="diagnostic_3ds_card",
                pan="5549603469426017",
                requires_3ds=True,
                expected_otp="147852",
            ),
        ],
    )
    fake_automator.delay_seconds = 0.01
    fake_automator.result = AcsBrowserAutomationResult(
        completed=True,
        submitted=True,
        returned_to_callback=True,
        reason="otp_submitted",
        screen_classification="static_config_otp",
        otp_resolution={
            "status": "ready",
            "source_type": "static_config",
            "otp_present": True,
            "should_auto_submit": True,
            "reason": "resolved Garanti OTP from configured test card metadata",
        },
    )

    response = await client.post(
        "/api/parallel-runs",
        json={
            "mode": "manual",
            "amount": "50.00",
            "currency": "TRY",
            "concurrency": 3,
            "auto_complete_3ds": True,
            "manual_cards": [{"alias": "diagnostic_3ds_card", "repeat_count": 3}],
        },
    )

    assert response.status_code == 202
    payload = await _wait_parallel_run(client, response.json()["run_id"])
    assert payload["status"] == "completed"
    assert payload["completed"] == 3
    assert {item["automation_status"] for item in payload["items"]} == {
        "automation_diagnostic"
    }
    assert {item["diagnostic_class"] for item in payload["items"]} == {
        "awaiting_provider_finalization"
    }
    assert {item["automatic_success_candidate"] for item in payload["items"]} == {False}
    assert len(fake_automator.calls) == 3
    assert fake_automator.max_active_calls == 1


@pytest.mark.api
@pytest.mark.asyncio
async def test_parallel_run_retries_payment_list_after_3ds_automation_submit(
    client: httpx.AsyncClient,
    fake_initializer: FakePaymentInitializer,
    fake_automator: FakeThreeDSAutomator,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    sleep_calls: list[float] = []

    async def fake_sleep(delay: float) -> None:
        sleep_calls.append(delay)

    monkeypatch.setattr(payment_list_retry, "async_sleep", fake_sleep)
    _write_parallel_runtime_config(
        monkeypatch,
        tmp_path,
        [
            _runtime_card(
                alias="parallel_3ds",
                pan="5555555555554444",
                requires_3ds=True,
                expected_otp="123456",
            ),
        ],
    )
    fake_automator.result = AcsBrowserAutomationResult(
        completed=True,
        submitted=True,
        returned_to_callback=True,
        reason="otp_submitted",
        screen_classification="static_config_otp",
        otp_resolution={
            "status": "ready",
            "source_type": "static_config",
            "otp_present": True,
            "should_auto_submit": True,
            "reason": "resolved OTP from configured test card metadata",
        },
    )
    fake_initializer.status_outcomes = [
        PaymentProviderStatusVerificationError("provider payment status verification failed"),
        PaymentProviderStatusVerificationError("provider payment status verification failed"),
        PaymentProviderStatusVerificationError("provider payment status verification failed"),
        PaymentProviderStatusVerificationError("provider payment status verification failed"),
        TransactionStatusResponse(
            order_id="filled-by-test",
            provider_transaction_id="list-ref-retry",
            status=PaymentStatus.CAPTURED,
            amount=Decimal("50.00"),
            currency=Currency.TRY,
            updated_at=datetime(2026, 7, 7, 12, 0, tzinfo=UTC),
            authorization_code="LISTRETRY",
        ),
    ]

    response = await client.post(
        "/api/parallel-runs",
        json={
            "mode": "manual",
            "amount": "50.00",
            "currency": "TRY",
            "concurrency": 1,
            "auto_complete_3ds": True,
            "manual_cards": [{"alias": "parallel_3ds", "repeat_count": 1}],
        },
    )

    assert response.status_code == 202
    payload = await _wait_parallel_run(client, response.json()["run_id"])
    assert payload["status"] == "completed"
    assert payload["items"][0]["classification"] == "completed"
    assert payload["items"][0]["payment_list_status"] == "captured"
    assert payload["items"][0]["payment_list_error"] is None
    assert fake_initializer.status_calls == [payload["items"][0]["order_id"]] * 5
    assert sleep_calls == [2.0, 5.0, 10.0, 20.0]


@pytest.mark.api
@pytest.mark.asyncio
async def test_parallel_run_retries_created_payment_list_after_3ds_automation_submit(
    client: httpx.AsyncClient,
    fake_initializer: FakePaymentInitializer,
    fake_automator: FakeThreeDSAutomator,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    sleep_calls: list[float] = []

    async def fake_sleep(delay: float) -> None:
        sleep_calls.append(delay)

    monkeypatch.setattr(payment_list_retry, "async_sleep", fake_sleep)
    _write_parallel_runtime_config(
        monkeypatch,
        tmp_path,
        [
            _runtime_card(
                alias="parallel_3ds",
                pan="5555555555554444",
                requires_3ds=True,
                expected_otp="123456",
            ),
        ],
    )
    fake_automator.result = AcsBrowserAutomationResult(
        completed=True,
        submitted=True,
        returned_to_callback=False,
        reason="otp_submitted",
        screen_classification="static_config_otp",
        final_url="https://gbemv3dsecure-integration-t.garanti.com.tr/web/pinvalidate",
        otp_resolution={
            "status": "ready",
            "source_type": "static_config",
            "otp_present": True,
            "should_auto_submit": True,
            "reason": "resolved OTP from configured test card metadata",
        },
    )
    fake_initializer.status_outcomes = [
        TransactionStatusResponse(
            order_id="filled-by-test",
            provider_transaction_id="list-ref-created",
            status=PaymentStatus.CREATED,
            amount=Decimal("50.00"),
            currency=Currency.TRY,
            updated_at=datetime(2026, 7, 7, 12, 0, tzinfo=UTC),
        ),
        TransactionStatusResponse(
            order_id="filled-by-test",
            provider_transaction_id="list-ref-captured",
            status=PaymentStatus.CAPTURED,
            amount=Decimal("50.00"),
            currency=Currency.TRY,
            updated_at=datetime(2026, 7, 7, 12, 0, tzinfo=UTC),
            authorization_code="LISTRETRY",
        ),
    ]

    response = await client.post(
        "/api/parallel-runs",
        json={
            "mode": "manual",
            "amount": "50.00",
            "currency": "TRY",
            "concurrency": 1,
            "auto_complete_3ds": True,
            "manual_cards": [{"alias": "parallel_3ds", "repeat_count": 1}],
        },
    )

    assert response.status_code == 202
    payload = await _wait_parallel_run(client, response.json()["run_id"])
    assert payload["status"] == "completed"
    assert payload["items"][0]["classification"] == "completed"
    assert payload["items"][0]["payment_list_status"] == "captured"
    assert fake_initializer.status_calls == [payload["items"][0]["order_id"]] * 2
    assert sleep_calls == [2.0]


@pytest.mark.api
@pytest.mark.asyncio
async def test_parallel_run_marks_created_payment_list_as_awaiting_provider_finalization(
    client: httpx.AsyncClient,
    fake_initializer: FakePaymentInitializer,
    fake_automator: FakeThreeDSAutomator,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    sleep_calls: list[float] = []

    async def fake_sleep(delay: float) -> None:
        sleep_calls.append(delay)

    monkeypatch.setattr(payment_list_retry, "async_sleep", fake_sleep)
    _write_parallel_runtime_config(
        monkeypatch,
        tmp_path,
        [
            _runtime_card(
                alias="parallel_3ds",
                pan="5555555555554444",
                requires_3ds=True,
                expected_otp="123456",
            ),
        ],
    )
    fake_automator.result = AcsBrowserAutomationResult(
        completed=True,
        submitted=True,
        returned_to_callback=False,
        reason="otp_submitted",
        screen_classification="static_config_otp",
        final_url="https://gbemv3dsecure-integration-t.garanti.com.tr/web/pinvalidate",
        otp_resolution={
            "status": "ready",
            "source_type": "static_config",
            "otp_present": True,
            "should_auto_submit": True,
            "reason": "resolved OTP from configured test card metadata",
        },
    )
    fake_initializer.payment_list_status = TransactionStatusResponse(
        order_id="filled-by-test",
        provider_transaction_id="list-ref-created",
        status=PaymentStatus.CREATED,
        amount=Decimal("50.00"),
        currency=Currency.TRY,
        updated_at=datetime(2026, 7, 7, 12, 0, tzinfo=UTC),
    )

    response = await client.post(
        "/api/parallel-runs",
        json={
            "mode": "manual",
            "amount": "50.00",
            "currency": "TRY",
            "concurrency": 1,
            "auto_complete_3ds": True,
            "manual_cards": [{"alias": "parallel_3ds", "repeat_count": 1}],
        },
    )

    assert response.status_code == 202
    payload = await _wait_parallel_run(client, response.json()["run_id"])
    assert payload["status"] == "completed_with_failures"
    assert payload["items"][0]["classification"] == "awaiting_provider_finalization"
    assert payload["items"][0]["automation_status"] == "unknown"
    assert payload["items"][0]["automatic_success_candidate"] is True
    assert payload["items"][0]["payment_list_status"] == "created"
    assert payload["items"][0]["payment_list"] == {
        "status": "created",
        "provider_transaction_id": "list-ref-created",
        "authorization_code": None,
        "failure_code": None,
        "updated_at": "2026-07-07T12:00:00+00:00",
        "error": None,
    }
    assert payload["items"][0]["three_ds_automation"]["submitted"] is True
    assert payload["items"][0]["three_ds_automation"]["final_url"].endswith("/web/pinvalidate")
    assert fake_initializer.status_calls == [payload["items"][0]["order_id"]] * 5
    assert sleep_calls == [2.0, 5.0, 10.0, 20.0]


@pytest.mark.api
@pytest.mark.asyncio
async def test_parallel_run_records_failed_payment_list_detail_after_3ds_submit(
    client: httpx.AsyncClient,
    fake_initializer: FakePaymentInitializer,
    fake_automator: FakeThreeDSAutomator,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _write_parallel_runtime_config(
        monkeypatch,
        tmp_path,
        [
            _runtime_card(
                alias="parallel_3ds",
                pan="5555555555554444",
                requires_3ds=True,
                expected_otp="123456",
            ),
        ],
    )
    fake_automator.result = AcsBrowserAutomationResult(
        completed=True,
        submitted=True,
        returned_to_callback=True,
        reason="otp_submitted",
        screen_classification="visible_otp_code",
        otp_resolution={
            "status": "ready",
            "source_type": "static_config",
            "otp_present": True,
            "should_auto_submit": True,
            "reason": "resolved OTP from configured test card metadata",
        },
    )
    fake_initializer.payment_list_status = TransactionStatusResponse(
        order_id="filled-by-test",
        provider_transaction_id="IKSIRPF533461",
        status=PaymentStatus.FAILED,
        amount=Decimal("100.00"),
        currency=Currency.TRY,
        updated_at=datetime(2026, 7, 21, 6, 18, 56, tzinfo=UTC),
        failure_code="ERROR",
    )

    response = await client.post(
        "/api/parallel-runs",
        json={
            "mode": "manual",
            "amount": "100.00",
            "currency": "TRY",
            "concurrency": 1,
            "auto_complete_3ds": True,
            "manual_cards": [{"alias": "parallel_3ds", "repeat_count": 1}],
        },
    )

    assert response.status_code == 202
    payload = await _wait_parallel_run(client, response.json()["run_id"])
    assert payload["status"] == "completed_with_failures"
    assert payload["items"][0]["classification"] == "provider_failed"
    assert payload["items"][0]["payment_list_status"] == "failed"
    assert payload["items"][0]["payment_list"] == {
        "status": "failed",
        "provider_transaction_id": "IKSIRPF533461",
        "authorization_code": None,
        "failure_code": "ERROR",
        "updated_at": "2026-07-21T06:18:56+00:00",
        "error": None,
    }


@pytest.mark.api
@pytest.mark.asyncio
async def test_parallel_run_continues_when_one_item_fails(
    client: httpx.AsyncClient,
    fake_initializer: FakePaymentInitializer,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _write_parallel_runtime_config(
        monkeypatch,
        tmp_path,
        [
            _runtime_card(
                alias="parallel_moto",
                pan="4111111111111111",
                requires_3ds=False,
            ),
        ],
    )
    network_cause = OSError("[Errno 8] nodename nor servname provided")
    initialization_error = PaymentProviderInitializationError(
        "provider payment initialization failed"
    )
    initialization_error.__cause__ = network_cause
    fake_initializer.outcomes = [
        initialization_error,
        _payment_result(response_code="2", response_data="Islem Basarili"),
    ]

    response = await client.post(
        "/api/parallel-runs",
        json={
            "mode": "manual",
            "amount": "100.00",
            "currency": "TRY",
            "concurrency": 2,
            "manual_cards": [{"alias": "parallel_moto", "repeat_count": 2}],
        },
    )

    assert response.status_code == 202
    payload = await _wait_parallel_run(client, response.json()["run_id"])
    assert payload["status"] == "completed_with_failures"
    assert payload["completed"] == 1
    assert payload["failed"] == 1
    assert [item["classification"] for item in payload["items"]] == [
        "network_error",
        "completed",
    ]
    assert len(fake_initializer.calls) == 2


@pytest.mark.api
@pytest.mark.asyncio
async def test_parallel_run_rejects_unknown_manual_card(
    client: httpx.AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _write_parallel_runtime_config(
        monkeypatch,
        tmp_path,
        [
            _runtime_card(
                alias="parallel_moto",
                pan="4111111111111111",
                requires_3ds=False,
            ),
        ],
    )

    response = await client.post(
        "/api/parallel-runs",
        json={
            "mode": "manual",
            "amount": "100.00",
            "currency": "TRY",
            "manual_cards": [{"alias": "missing_card", "repeat_count": 1}],
        },
    )

    assert response.status_code == 422
    assert "unknown card alias" in response.json()["detail"]


@pytest.mark.api
@pytest.mark.asyncio
async def test_parallel_run_random_mode_excludes_synthetic_and_unknown_cards(
    client: httpx.AsyncClient,
    fake_initializer: FakePaymentInitializer,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _write_parallel_runtime_config(
        monkeypatch,
        tmp_path,
        [
            _runtime_card(
                alias="akbank_visa_7068",
                pan="4111111111111111",
                requires_3ds=True,
                expected_otp="123456",
            ),
            _runtime_card(
                alias="unknown_real_moto",
                pan="4000000000000002",
                requires_3ds=False,
            ),
            _runtime_card(
                alias="synthetic_env1_card_0001",
                pan="5555555555554444",
                requires_3ds=False,
            ),
        ],
    )
    fake_initializer.provider_result = _payment_result(
        response_code="2",
        response_data="Islem Basarili",
    )

    response = await client.post(
        "/api/parallel-runs",
        json={
            "mode": "random",
            "amount": "100.00",
            "currency": "TRY",
            "concurrency": 2,
            "random_count": 3,
        },
    )

    assert response.status_code == 202
    payload = await _wait_parallel_run(client, response.json()["run_id"])
    assert {item["card_alias"] for item in payload["items"]} == {"akbank_visa_7068"}
    assert len(fake_initializer.calls) == 3


@pytest.mark.api
@pytest.mark.asyncio
async def test_parallel_run_random_mode_excludes_manual_and_quarantined_cards(
    client: httpx.AsyncClient,
    fake_initializer: FakePaymentInitializer,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _write_parallel_runtime_config(
        monkeypatch,
        tmp_path,
        [
            _runtime_card(
                alias="akbank_visa_7068",
                pan="4111111111111111",
                requires_3ds=True,
                expected_otp="123456",
            ),
            _runtime_card(
                alias="denizbank_mastercard_8608",
                pan="5555555555554444",
                requires_3ds=True,
                expected_otp="123456",
            ),
            _runtime_card(
                alias="yapikredi_visa_9085",
                pan="4000000000000002",
                requires_3ds=True,
                expected_otp="123456",
            ),
            _runtime_card(
                alias="garanti_bankasi_mastercard_6017",
                pan="4000000000000036",
                requires_3ds=True,
                expected_otp="147852",
            ),
            _runtime_card(
                alias="unknown_uat_card",
                pan="4000000000000044",
                requires_3ds=False,
            ),
        ],
    )
    fake_initializer.provider_result = _payment_result(
        response_code="2",
        response_data="Islem Basarili",
    )

    response = await client.post(
        "/api/parallel-runs",
        json={
            "mode": "random",
            "amount": "100.00",
            "currency": "TRY",
            "concurrency": 2,
            "random_count": 5,
        },
    )

    assert response.status_code == 202
    payload = await _wait_parallel_run(client, response.json()["run_id"])
    assert {item["card_alias"] for item in payload["items"]} == {"akbank_visa_7068"}
    assert len(fake_initializer.calls) == 5


@pytest.mark.api
@pytest.mark.asyncio
async def test_parallel_run_manual_mode_allows_quarantined_card(
    client: httpx.AsyncClient,
    fake_initializer: FakePaymentInitializer,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _write_parallel_runtime_config(
        monkeypatch,
        tmp_path,
        [
            _runtime_card(
                alias="denizbank_mastercard_8608",
                pan="5555555555554444",
                requires_3ds=False,
            ),
        ],
    )
    fake_initializer.provider_result = _payment_result(
        response_code="2",
        response_data="Islem Basarili",
    )

    response = await client.post(
        "/api/parallel-runs",
        json={
            "mode": "manual",
            "amount": "100.00",
            "currency": "TRY",
            "concurrency": 1,
            "manual_cards": [{"alias": "denizbank_mastercard_8608", "repeat_count": 1}],
        },
    )

    assert response.status_code == 202
    payload = await _wait_parallel_run(client, response.json()["run_id"])
    assert payload["items"][0]["card_alias"] == "denizbank_mastercard_8608"
    assert payload["status"] == "completed"


@pytest.mark.api
@pytest.mark.asyncio
async def test_parallel_run_validation_limits_manual_items(client: httpx.AsyncClient) -> None:
    response = await client.post(
        "/api/parallel-runs",
        json={
            "mode": "manual",
            "amount": "100.00",
            "currency": "TRY",
            "manual_cards": [
                {"alias": "a", "repeat_count": 76},
                {"alias": "b", "repeat_count": 75},
            ],
        },
    )

    assert response.status_code == 422
    assert "manual mode can create at most 150 test items" in response.text


@pytest.mark.api
@pytest.mark.asyncio
async def test_parallel_installment_run_requires_uat_installment_key(
    client: httpx.AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    config_path = tmp_path / "uat-without-installment-key.json"
    config_payload = build_private_runtime_config_payload(card_count=10)
    environments = cast(dict[str, Any], config_payload["environments"])
    uat = cast(dict[str, Any], environments["uat"])
    uat["cards"] = [
        _runtime_card(
            alias="uat_installment_card",
            pan="4111111111111111",
            requires_3ds=False,
        )
    ]
    merchant = cast(dict[str, Any], uat["merchant"])
    merchant.pop("installment_api_key")
    config_payload["active_environment"] = "uat"
    config_path.write_text(json.dumps(config_payload), encoding="utf-8")
    monkeypatch.setenv("PAYNKOLAY_CONFIG_FILE", str(config_path))
    monkeypatch.setenv("PAYNKOLAY_ENV", "uat")

    response = await client.post(
        "/api/parallel-runs",
        json={
            "mode": "manual",
            "amount": "1000.00",
            "currency": "TRY",
            "installment_count": 3,
            "concurrency": 1,
            "manual_cards": [{"alias": "uat_installment_card", "repeat_count": 1}],
        },
    )

    assert response.status_code == 503
    assert response.json()["detail"] == "runtime installment API key is unavailable"


@pytest.mark.api
@pytest.mark.asyncio
async def test_installment_options_returns_local_stub_options_for_try(
    client: httpx.AsyncClient,
) -> None:
    response = await client.post(
        "/api/installments/options",
        json={
            "amount": "500.00",
            "currency": "TRY",
            "card_brand": "visa",
            "card_number": "4111111111111111",
            "requires_3ds": True,
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["source"] == "local_stub"
    assert payload["default_installment"] == 1
    assert [option["installment_count"] for option in payload["options"]] == [
        1,
        2,
        3,
        6,
        9,
        12,
    ]
    assert payload["options"][0]["label"] == "Tek cekim"
    assert payload["options"][1]["monthly_amount"] == "250.00"


@pytest.mark.api
@pytest.mark.asyncio
async def test_installment_options_returns_single_payment_for_small_or_foreign_amount(
    client: httpx.AsyncClient,
) -> None:
    small_response = await client.post(
        "/api/installments/options",
        json={
            "amount": "20.00",
            "currency": "TRY",
            "card_brand": "visa",
            "card_number": "4111111111111111",
            "requires_3ds": False,
        },
    )
    foreign_response = await client.post(
        "/api/installments/options",
        json={
            "amount": "500.00",
            "currency": "USD",
            "card_brand": "visa",
            "card_number": "4111111111111111",
            "requires_3ds": False,
        },
    )

    assert small_response.status_code == 200
    assert foreign_response.status_code == 200
    assert [option["installment_count"] for option in small_response.json()["options"]] == [1]
    assert [option["installment_count"] for option in foreign_response.json()["options"]] == [1]


@pytest.mark.api
@pytest.mark.asyncio
async def test_installment_options_returns_real_provider_quotes() -> None:
    app = create_app()
    app.dependency_overrides[get_installment_provider] = lambda: FakeInstallmentProvider()
    transport = httpx.ASGITransport(app=app)

    async with httpx.AsyncClient(
        transport=transport,
        base_url="http://testserver",
    ) as test_client:
        response = await test_client.post(
            "/api/installments/options",
            json={
                "amount": "1000.00",
                "currency": "TRY",
                "card_brand": "visa",
                "card_number": "4111111111111111",
                "requires_3ds": True,
            },
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["source"] == "paynkolay_uat"
    assert payload["default_installment"] == 3
    assert payload["options"] == [
        {
            "installment_count": 3,
            "label": "3 taksit",
            "total_amount": "1052.63",
            "monthly_amount": "350.88",
            "commission_amount": "52.63",
            "commission_rate": "5.00",
            "encoded_value": "opaque-provider-quote",
        }
    ]


@pytest.mark.api
@pytest.mark.asyncio
async def test_config_overview_reports_missing_runtime_without_secrets(
    client: httpx.AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("PAYNKOLAY_CONFIG_FILE", raising=False)

    response = await client.get("/api/config/overview")

    assert response.status_code == 200
    payload = response.json()
    assert payload["runtime_configured"] is False
    assert payload["readiness"]["checked"] is False
    assert payload["card_count"] == 0
    assert payload["cards"] == []
    assert "PAYNKOLAY_CONFIG_FILE" in payload["message"]


@pytest.mark.api
@pytest.mark.asyncio
async def test_config_overview_exposes_safe_runtime_metadata(
    client: httpx.AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    config_path = tmp_path / "settings.json"
    scenario_path = tmp_path / "scenarios.json"
    config_payload = build_private_runtime_config_payload(card_count=100)
    environments = cast(dict[str, Any], config_payload["environments"])
    dev = cast(dict[str, Any], environments["dev"])
    dev["callback_base_url"] = "https://merchant-callback.test"
    merchant = cast(dict[str, Any], dev["merchant"])
    merchant.update(
        {
            "merchant_id": "merchant-1001",
            "terminal_id": "terminal-1001",
            "api_key": "payment-api-key-1001",
            "list_api_key": "list-api-key-1001",
            "cancel_refund_api_key": "refund-api-key-1001",
            "secret_key": "merchant-secret-1001",
        }
    )
    config_path.write_text(json.dumps(config_payload), encoding="utf-8")
    scenario_path.write_text(
        json.dumps(build_private_scenario_catalog_payload(card_count=100)),
        encoding="utf-8",
    )
    monkeypatch.setenv("PAYNKOLAY_CONFIG_FILE", str(config_path))
    monkeypatch.setenv("PAYNKOLAY_SCENARIO_CATALOG", str(scenario_path))

    response = await client.get("/api/config/overview")

    assert response.status_code == 200
    payload = response.json()
    assert payload["runtime_configured"] is True
    assert payload["active_environment"] == "dev"
    assert payload["merchant"]["merchant_id"].startswith("me")
    assert payload["merchant"]["has_list_key"] is True
    assert "merchant-1001" not in response.text
    assert "payment-api-key-1001" not in response.text
    assert "list-api-key-1001" not in response.text
    assert "merchant-secret-1001" not in response.text
    assert payload["card_count"] == 100
    assert payload["scenarios"]["scenario_count"] == 109
    assert payload["scenarios"]["coverage"]["three_ds_count"] > 0
    assert payload["scenarios"]["coverage"]["moto_count"] > 0
    assert payload["scenarios"]["coverage"]["single_payment_count"] > 0
    assert payload["scenarios"]["coverage"]["installment_count"] > 0
    assert payload["scenarios"]["coverage"]["negative_count"] > 0
    assert payload["scenarios"]["coverage"]["payment_channel_counts"]["e_commerce"] > 0
    assert payload["scenarios"]["coverage"]["payment_channel_counts"]["moto"] > 0
    assert payload["scenarios"]["coverage"]["final_status_counts"]["failed"] > 0
    assert payload["readiness"]["checked"] is True
    assert payload["readiness"]["ready"] is True
    assert payload["readiness"]["issues"] == []
    assert payload["cards"][0] == {
        "alias": "visa_3ds_success",
        "brand": "visa",
        "requires_3ds": True,
        "has_expected_otp": True,
        "automation_status": "unknown",
        "automation_reason": "No live UAT automation behavior has been recorded for this alias.",
        "diagnostic_class": "unknown",
        "automatic_success_candidate": True,
    }


@pytest.mark.api
@pytest.mark.asyncio
async def test_merchant_settings_update_is_persisted_without_exposing_sx(
    client: httpx.AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    config_path = tmp_path / "settings.json"
    config_payload = build_private_runtime_config_payload(card_count=10)
    environments = cast(dict[str, Any], config_payload["environments"])
    dev = cast(dict[str, Any], environments["dev"])
    merchant = cast(dict[str, Any], dev["merchant"])
    merchant.update(
        {
            "merchant_id": "400000001",
            "terminal_id": "terminal-original",
            "api_key": "payment-sx-original",
            "installment_api_key": "installment-sx-original",
            "list_api_key": "list-sx-original",
            "cancel_refund_api_key": "cancel-sx-original",
            "secret_key": "merchant-secret-original",
        }
    )
    config_path.write_text(json.dumps(config_payload), encoding="utf-8")
    monkeypatch.setenv("PAYNKOLAY_CONFIG_FILE", str(config_path))

    initial_response = await client.get("/api/config/merchant")

    assert initial_response.status_code == 200
    assert initial_response.json() == {
        "environment": "dev",
        "merchant_no": "400000001",
        "payment_sx_configured": True,
        "message": None,
    }
    assert "payment-sx-original" not in initial_response.text

    update_response = await client.patch(
        "/api/config/merchant",
        json={
            "environment": "dev",
            "merchant_no": "400009999",
            "payment_sx": "payment-sx-replacement",
        },
    )

    assert update_response.status_code == 200
    assert update_response.json() == {
        "environment": "dev",
        "merchant_no": "400009999",
        "payment_sx_configured": True,
        "message": "Merchant settings saved for new payment runs.",
    }
    assert "payment-sx-replacement" not in update_response.text

    settings = load_runtime_settings()
    assert settings.current.merchant.merchant_id == "400009999"
    assert (
        settings.current.merchant.api_key.get_secret_value()
        == "payment-sx-replacement"
    )
    assert settings.current.merchant.terminal_id == "terminal-original"
    assert settings.current.merchant.installment_api_key is not None
    assert (
        settings.current.merchant.installment_api_key.get_secret_value()
        == "installment-sx-original"
    )
    assert settings.current.merchant.list_api_key is not None
    assert (
        settings.current.merchant.list_api_key.get_secret_value()
        == "list-sx-original"
    )
    assert settings.current.merchant.cancel_refund_api_key is not None
    assert (
        settings.current.merchant.cancel_refund_api_key.get_secret_value()
        == "cancel-sx-original"
    )
    assert (
        settings.current.merchant.secret_key.get_secret_value()
        == "merchant-secret-original"
    )


@pytest.mark.api
@pytest.mark.asyncio
async def test_merchant_settings_update_preserves_sx_when_omitted(
    client: httpx.AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    config_path = tmp_path / "settings.json"
    config_payload = build_private_runtime_config_payload(card_count=10)
    environments = cast(dict[str, Any], config_payload["environments"])
    dev = cast(dict[str, Any], environments["dev"])
    merchant = cast(dict[str, Any], dev["merchant"])
    merchant["merchant_id"] = "400000001"
    merchant["api_key"] = "payment-sx-preserved"
    config_path.write_text(json.dumps(config_payload), encoding="utf-8")
    monkeypatch.setenv("PAYNKOLAY_CONFIG_FILE", str(config_path))

    response = await client.patch(
        "/api/config/merchant",
        json={"environment": "dev", "merchant_no": "400009999"},
    )

    assert response.status_code == 200
    settings = load_runtime_settings()
    assert settings.current.merchant.merchant_id == "400009999"
    assert (
        settings.current.merchant.api_key.get_secret_value()
        == "payment-sx-preserved"
    )
    assert settings.current.merchant.list_api_key is not None
    assert (
        settings.current.merchant.list_api_key.get_secret_value()
        == "replace-with-dev-list-sx"
    )
    assert "payment-sx-preserved" not in response.text


@pytest.mark.api
@pytest.mark.asyncio
async def test_merchant_settings_rejects_stale_environment_and_invalid_merchant(
    client: httpx.AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    config_path = tmp_path / "settings.json"
    config_payload = build_private_runtime_config_payload(card_count=10)
    config_path.write_text(json.dumps(config_payload), encoding="utf-8")
    monkeypatch.setenv("PAYNKOLAY_CONFIG_FILE", str(config_path))

    stale_response = await client.patch(
        "/api/config/merchant",
        json={
            "environment": "uat",
            "merchant_no": "400009999",
            "payment_sx": "must-not-be-written",
        },
    )
    invalid_response = await client.patch(
        "/api/config/merchant",
        json={"environment": "dev", "merchant_no": "merchant-not-numeric"},
    )

    assert stale_response.status_code == 409
    assert invalid_response.status_code == 422
    settings = load_runtime_settings()
    assert settings.current.merchant.merchant_id == "replace-with-dev-merchant-id"
    assert "must-not-be-written" not in config_path.read_text(encoding="utf-8")


@pytest.mark.api
@pytest.mark.asyncio
async def test_merchant_settings_rejects_invalid_sx_without_echoing_it(
    client: httpx.AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    config_path = tmp_path / "settings.json"
    config_payload = build_private_runtime_config_payload(card_count=10)
    config_path.write_text(json.dumps(config_payload), encoding="utf-8")
    monkeypatch.setenv("PAYNKOLAY_CONFIG_FILE", str(config_path))
    oversized_sx = "private-sx-" + ("x" * 4096)

    response = await client.patch(
        "/api/config/merchant",
        json={
            "environment": "dev",
            "merchant_no": "400009999",
            "payment_sx": oversized_sx,
        },
    )

    assert response.status_code == 422
    assert response.json()["detail"] == (
        "payment_sx must contain between 1 and 4096 characters"
    )
    assert oversized_sx not in response.text
    assert oversized_sx not in config_path.read_text(encoding="utf-8")


@pytest.mark.api
@pytest.mark.asyncio
async def test_merchant_settings_config_errors_do_not_expose_existing_secrets(
    client: httpx.AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    config_path = tmp_path / "settings.json"
    config_payload = build_private_runtime_config_payload(card_count=10)
    environments = cast(dict[str, Any], config_payload["environments"])
    dev = cast(dict[str, Any], environments["dev"])
    merchant = cast(dict[str, Any], dev["merchant"])
    merchant["api_key"] = "private-existing-payment-sx"
    cards = cast(list[dict[str, Any]], dev["cards"])
    cards[1]["alias"] = cards[0]["alias"]
    config_path.write_text(json.dumps(config_payload), encoding="utf-8")
    monkeypatch.setenv("PAYNKOLAY_CONFIG_FILE", str(config_path))

    get_response = await client.get("/api/config/merchant")
    patch_response = await client.patch(
        "/api/config/merchant",
        json={"environment": "dev", "merchant_no": "400009999"},
    )

    assert get_response.status_code == 503
    assert patch_response.status_code == 503
    assert get_response.json()["detail"] == (
        "runtime merchant configuration is unavailable"
    )
    assert patch_response.json()["detail"] == (
        "runtime merchant configuration could not be saved"
    )
    assert "private-existing-payment-sx" not in get_response.text
    assert "private-existing-payment-sx" not in patch_response.text


@pytest.mark.api
@pytest.mark.asyncio
async def test_merchant_and_card_updates_do_not_overwrite_each_other(
    client: httpx.AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    config_path = tmp_path / "settings.json"
    config_payload = build_private_runtime_config_payload(card_count=10)
    config_path.write_text(json.dumps(config_payload), encoding="utf-8")
    monkeypatch.setenv("PAYNKOLAY_CONFIG_FILE", str(config_path))

    merchant_response, card_response = await asyncio.gather(
        client.patch(
            "/api/config/merchant",
            json={
                "environment": "dev",
                "merchant_no": "400009999",
                "payment_sx": "concurrent-payment-sx",
            },
        ),
        client.post(
            "/api/cards",
            json={
                "alias": "concurrent_moto_card",
                "brand": "visa",
                "card_number": "4111111111111234",
                "expiry_month": 10,
                "expiry_year": 2030,
                "cvv": "321",
                "flow_type": "moto",
            },
        ),
    )

    assert merchant_response.status_code == 200
    assert card_response.status_code == 201
    settings = load_runtime_settings()
    assert settings.current.merchant.merchant_id == "400009999"
    assert (
        settings.current.merchant.api_key.get_secret_value()
        == "concurrent-payment-sx"
    )
    assert settings.current.merchant.list_api_key is not None
    assert (
        settings.current.merchant.list_api_key.get_secret_value()
        == "replace-with-dev-list-sx"
    )
    assert settings.current.cards[-1].alias == "concurrent_moto_card"


@pytest.mark.api
@pytest.mark.asyncio
async def test_payment_form_initializes_provider_and_returns_3ds_state(
    client: httpx.AsyncClient,
    fake_initializer: FakePaymentInitializer,
    fake_logger: FakeExternalPaymentLogger,
    fake_automator: FakeThreeDSAutomator,
) -> None:
    response = await client.post(
        "/api/payments",
        json={
            "amount": "100.00",
            "currency": "TRY",
            "card_number": "4111111111111111",
            "card_holder": "PAYNKOLAY TEST",
            "expiry_month": 12,
            "expiry_year": 2030,
            "cvv": "123",
            "requires_3ds": True,
            "installment_count": 1,
        },
    )

    assert response.status_code == 202
    payload = response.json()
    assert payload["order_id"].startswith("web-")
    assert payload["status"] == "pending_3ds"
    assert payload["amount"] == "100.00"
    assert payload["requires_3ds"] is True
    assert payload["masked_pan"] == "411111******1111"
    assert payload["three_ds"] == {"render_url": f"/payments/{payload['order_id']}/three-ds"}
    assert payload["three_ds_automation"] is None
    assert fake_initializer.calls == [(payload["order_id"], "127.0.0.1")]
    assert fake_initializer.status_calls == []
    assert fake_automator.calls == []
    assert "4111111111111111" not in str([event.model_dump() for event in fake_logger.events])
    assert "123" not in str([event.model_dump() for event in fake_logger.events])
    assert "4111111111111111" not in response.text
    assert "123" not in response.text

    three_ds_response = await client.get(payload["three_ds"]["render_url"])

    assert three_ds_response.status_code == 200
    assert "<form>3DS challenge</form>" in three_ds_response.text
    assert [event.event for event in fake_logger.events] == [
        "payment_initialized",
        "three_ds_required",
        "three_ds_rendered",
    ]


@pytest.mark.api
@pytest.mark.asyncio
async def test_payment_form_auto_completes_3ds_when_otp_automation_submits(
    client: httpx.AsyncClient,
    fake_automator: FakeThreeDSAutomator,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _write_parallel_runtime_config(
        monkeypatch,
        tmp_path,
        [
            _runtime_card(
                alias="ui_3ds_static",
                pan="4111111111111111",
                requires_3ds=True,
                expected_otp="123456",
            ),
        ],
    )
    fake_automator.result = AcsBrowserAutomationResult(
        completed=True,
        submitted=True,
        returned_to_callback=True,
        reason="otp_submitted",
        screen_classification="static_config_otp",
        otp_resolution={
            "status": "ready",
            "source_type": "static_config",
            "otp_present": True,
            "should_auto_submit": True,
            "reason": "resolved OTP from configured test card metadata",
        },
    )

    response = await client.post(
        "/api/payments",
        json={
            "order_id": "order-auto-3ds",
            "amount": "100.00",
            "currency": "TRY",
            "card_number": "4111111111111111",
            "card_holder": "PAYNKOLAY TEST",
            "expiry_month": 12,
            "expiry_year": 2030,
            "cvv": "123",
            "requires_3ds": True,
            "installment_count": 1,
            "auto_complete_3ds": True,
        },
    )
    lookup_response = await client.get("/api/payments/order-auto-3ds")

    assert response.status_code == 202
    payload = lookup_response.json()
    assert payload["status"] == "completed"
    assert payload["payment_list"]["status"] == "captured"
    assert payload["three_ds_automation"] == {
        "status": "completed",
        "submitted": True,
        "classification": "static_config_otp",
        "reason": "otp_submitted",
        "otp_source_type": "static_config",
        "otp_present": True,
        "should_auto_submit": True,
        "final_url": None,
    }
    assert fake_automator.calls[0]["configured_otp_present"] is True
    assert "123456" not in lookup_response.text


@pytest.mark.api
@pytest.mark.asyncio
async def test_payment_form_retries_payment_list_after_auto_3ds_submit(
    fake_automator: FakeThreeDSAutomator,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    sleep_calls: list[float] = []

    async def fake_sleep(delay: float) -> None:
        sleep_calls.append(delay)

    monkeypatch.setattr(payment_list_retry, "async_sleep", fake_sleep)
    _write_parallel_runtime_config(
        monkeypatch,
        tmp_path,
        [
            _runtime_card(
                alias="ui_3ds_static",
                pan="4111111111111111",
                requires_3ds=True,
                expected_otp="123456",
            ),
        ],
    )
    fake_automator.result = AcsBrowserAutomationResult(
        completed=True,
        submitted=True,
        returned_to_callback=True,
        reason="otp_submitted",
        screen_classification="static_config_otp",
        otp_resolution={
            "status": "ready",
            "source_type": "static_config",
            "otp_present": True,
            "should_auto_submit": True,
            "reason": "resolved OTP from configured test card metadata",
        },
    )
    fake_initializer = FakePaymentInitializer(
        status_outcomes=[
            PaymentProviderStatusVerificationError(
                "provider payment status verification failed"
            ),
            TransactionStatusResponse(
                order_id="order-auto-3ds-retry",
                provider_transaction_id="list-ref-retry",
                status=PaymentStatus.CAPTURED,
                amount=Decimal("100.00"),
                currency=Currency.TRY,
                updated_at=datetime(2026, 7, 7, 12, 0, tzinfo=UTC),
                authorization_code="LISTRETRY",
            ),
        ],
    )
    app = create_app()
    app.dependency_overrides[get_payment_initializer] = lambda: fake_initializer
    app.dependency_overrides[get_three_ds_automator] = lambda: fake_automator
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.post(
            "/api/payments",
            json={
                "order_id": "order-auto-3ds-retry",
                "amount": "100.00",
                "currency": "TRY",
                "card_number": "4111111111111111",
                "card_holder": "PAYNKOLAY TEST",
                "expiry_month": 12,
                "expiry_year": 2030,
                "cvv": "123",
                "requires_3ds": True,
                "installment_count": 1,
                "auto_complete_3ds": True,
            },
        )
        lookup_response = await client.get("/api/payments/order-auto-3ds-retry")

    assert response.status_code == 202
    payload = lookup_response.json()
    assert payload["status"] == "completed"
    assert payload["payment_list"]["status"] == "captured"
    assert payload["payment_list"]["error"] is None
    assert fake_initializer.status_calls == ["order-auto-3ds-retry", "order-auto-3ds-retry"]
    assert sleep_calls == [2.0]


@pytest.mark.api
@pytest.mark.asyncio
async def test_payment_form_reports_success_return_when_payment_list_is_unavailable(
    fake_automator: FakeThreeDSAutomator,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    async def no_wait(_: float) -> None:
        return None

    monkeypatch.setattr(payment_list_retry, "async_sleep", no_wait)
    _write_parallel_runtime_config(
        monkeypatch,
        tmp_path,
        [
            _runtime_card(
                alias="ui_3ds_static",
                pan="4111111111111111",
                requires_3ds=True,
                expected_otp="123456",
            ),
        ],
    )
    fake_automator.result = AcsBrowserAutomationResult(
        completed=True,
        submitted=True,
        returned_to_callback=True,
        reason="otp_submitted",
        screen_classification="static_config_otp",
        otp_resolution={
            "status": "ready",
            "source_type": "static_config",
            "otp_present": True,
            "should_auto_submit": True,
            "reason": "resolved OTP from configured test card metadata",
        },
    )
    verification_error = PaymentProviderStatusVerificationError(
        "provider payment status verification failed"
    )
    fake_initializer = FakePaymentInitializer(
        status_outcomes=[verification_error] * 4,
    )
    app = create_app()
    app.dependency_overrides[get_payment_initializer] = lambda: fake_initializer
    app.dependency_overrides[get_three_ds_automator] = lambda: fake_automator
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.post(
            "/api/payments",
            json={
                "order_id": "order-auto-3ds-list-unavailable",
                "amount": "100.00",
                "currency": "TRY",
                "card_number": "4111111111111111",
                "card_holder": "PAYNKOLAY TEST",
                "expiry_month": 12,
                "expiry_year": 2030,
                "cvv": "123",
                "requires_3ds": True,
                "installment_count": 1,
                "auto_complete_3ds": True,
            },
        )
        lookup_response = await client.get(
            "/api/payments/order-auto-3ds-list-unavailable"
        )

    assert response.status_code == 202
    payload = lookup_response.json()
    assert payload["status"] == "success_returned"
    assert payload["payment_list"]["status"] is None
    assert (
        payload["payment_list"]["error"]
        == "provider payment status verification failed"
    )
    assert payload["three_ds_automation"]["submitted"] is True
    assert fake_initializer.status_calls == [
        "order-auto-3ds-list-unavailable"
    ] * 4


@pytest.mark.api
@pytest.mark.asyncio
async def test_payment_form_keeps_status_verified_when_created_payment_list_persists(
    fake_automator: FakeThreeDSAutomator,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    sleep_calls: list[float] = []

    async def fake_sleep(delay: float) -> None:
        sleep_calls.append(delay)

    monkeypatch.setattr(payment_list_retry, "async_sleep", fake_sleep)
    _write_parallel_runtime_config(
        monkeypatch,
        tmp_path,
        [
            _runtime_card(
                alias="ui_3ds_static",
                pan="4111111111111111",
                requires_3ds=True,
                expected_otp="123456",
            ),
        ],
    )
    fake_automator.result = AcsBrowserAutomationResult(
        completed=True,
        submitted=True,
        returned_to_callback=False,
        reason="otp_submitted",
        screen_classification="static_config_otp",
        final_url="https://gbemv3dsecure-integration-t.garanti.com.tr/web/pinvalidate",
        otp_resolution={
            "status": "ready",
            "source_type": "static_config",
            "otp_present": True,
            "should_auto_submit": True,
            "reason": "resolved OTP from configured test card metadata",
        },
    )
    fake_initializer = FakePaymentInitializer(
        payment_list_status=TransactionStatusResponse(
            order_id="order-auto-3ds-created",
            provider_transaction_id="list-ref-created",
            status=PaymentStatus.CREATED,
            amount=Decimal("100.00"),
            currency=Currency.TRY,
            updated_at=datetime(2026, 7, 7, 12, 0, tzinfo=UTC),
        ),
    )
    app = create_app()
    app.dependency_overrides[get_payment_initializer] = lambda: fake_initializer
    app.dependency_overrides[get_three_ds_automator] = lambda: fake_automator
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.post(
            "/api/payments",
            json={
                "order_id": "order-auto-3ds-created",
                "amount": "100.00",
                "currency": "TRY",
                "card_number": "4111111111111111",
                "card_holder": "PAYNKOLAY TEST",
                "expiry_month": 12,
                "expiry_year": 2030,
                "cvv": "123",
                "requires_3ds": True,
                "installment_count": 1,
                "auto_complete_3ds": True,
            },
        )
        lookup_response = await client.get("/api/payments/order-auto-3ds-created")

    assert response.status_code == 202
    payload = lookup_response.json()
    assert payload["status"] == "status_verified"
    assert payload["payment_list"]["status"] == "created"
    assert payload["three_ds_automation"]["submitted"] is True
    assert payload["three_ds_automation"]["final_url"].endswith("/web/pinvalidate")
    assert fake_initializer.status_calls == ["order-auto-3ds-created"] * 4
    assert sleep_calls == [2.0, 5.0, 10.0]


@pytest.mark.api
@pytest.mark.asyncio
async def test_payment_lookup_returns_stored_session(client: httpx.AsyncClient) -> None:
    create_response = await client.post(
        "/api/payments",
        json={
            "order_id": "order-web-1001",
            "amount": "250.50",
            "currency": "TRY",
            "card_number": "4111111111111111",
            "card_holder": "PAYNKOLAY TEST",
            "expiry_month": 12,
            "expiry_year": 2030,
            "cvv": "123",
            "requires_3ds": True,
            "installment_count": 2,
        },
    )
    assert create_response.status_code == 202

    response = await client.get("/api/payments/order-web-1001")

    assert response.status_code == 200
    payload = response.json()
    assert payload["order_id"] == "order-web-1001"
    assert payload["status"] == "pending_3ds"
    assert payload["amount"] == "250.50"
    assert payload["masked_pan"] == "411111******1111"
    assert payload["card_holder"] == "PAYNKOLAY TEST"
    assert payload["requires_3ds"] is True
    assert payload["installment_count"] == 2
    assert payload["links"]["three_ds"] == "/payments/order-web-1001/three-ds"
    assert "4111111111111111" not in response.text
    assert "123" not in response.text


@pytest.mark.api
@pytest.mark.asyncio
async def test_payment_lookup_returns_completed_session_for_result_screen() -> None:
    final_result = PaynkolayPaymentResult.model_validate(
        {
            "RESPONSE_CODE": "2",
            "RESPONSE_DATA": "Islem Basarili",
            "USE_3D": "false",
            "RND": "rnd-lookup",
            "MERCHANT_NO": "merchant-web",
            "AUTH_CODE": "AUTHLOOKUP",
            "REFERENCE_CODE": "ref-lookup",
            "CLIENT_REFERENCE_CODE": "order-result-lookup",
            "TIMESTAMP": "2026-07-07T12:00:00+00:00",
            "TRANSACTION_AMOUNT": "100.00",
            "AUTHORIZATION_AMOUNT": "100.00",
            "INSTALLMENT": 1,
            "CURRENCY_CODE": Currency.TRY,
            "hashDataV2": "hash",
        }
    )
    app = create_app()
    app.dependency_overrides[get_payment_initializer] = lambda: FakePaymentInitializer(
        provider_result=final_result
    )
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        create_response = await client.post(
            "/api/payments",
            json={
                "order_id": "order-result-lookup",
                "amount": "100.00",
                "currency": "TRY",
                "card_number": "4111111111111111",
                "card_holder": "PAYNKOLAY TEST",
                "expiry_month": 12,
                "expiry_year": 2030,
                "cvv": "123",
                "requires_3ds": False,
                "installment_count": 1,
            },
        )
        lookup_response = await client.get("/api/payments/order-result-lookup")

    assert create_response.status_code == 202
    assert lookup_response.status_code == 200
    payload = lookup_response.json()
    assert payload["status"] == "completed"
    assert payload["provider_transaction_id"] == "ref-lookup"
    assert payload["payment_list"] == {
        "status": "captured",
        "provider_transaction_id": "list-ref-1001",
        "authorization_code": "LISTAUTH",
        "failure_code": None,
        "updated_at": "2026-07-07T12:00:00+00:00",
        "error": None,
    }
    assert payload["failure_reason"] is None
    assert payload["links"] == {"result": "/result?order_id=order-result-lookup"}
    assert "4111111111111111" not in lookup_response.text
    assert "123" not in lookup_response.text


@pytest.mark.api
@pytest.mark.asyncio
async def test_payment_form_records_final_provider_result() -> None:
    final_result = PaynkolayPaymentResult.model_validate(
        {
            "RESPONSE_CODE": "2",
            "RESPONSE_DATA": "Islem Basarili",
            "USE_3D": "false",
            "RND": "rnd-1001",
            "MERCHANT_NO": "merchant-web",
            "AUTH_CODE": "AUTH1001",
            "REFERENCE_CODE": "ref-1001",
            "CLIENT_REFERENCE_CODE": "order-web-final",
            "TIMESTAMP": "2026-07-07T12:00:00+00:00",
            "TRANSACTION_AMOUNT": "100.00",
            "AUTHORIZATION_AMOUNT": "100.00",
            "INSTALLMENT": 1,
            "CURRENCY_CODE": Currency.TRY,
            "hashDataV2": "hash",
        }
    )
    app = create_app()
    app.dependency_overrides[get_payment_initializer] = lambda: FakePaymentInitializer(
        provider_result=final_result
    )
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.post(
            "/api/payments",
            json={
                "order_id": "order-web-final",
                "amount": "100.00",
                "currency": "TRY",
                "card_number": "4111111111111111",
                "card_holder": "PAYNKOLAY TEST",
                "expiry_month": 12,
                "expiry_year": 2030,
                "cvv": "123",
                "requires_3ds": False,
                "installment_count": 1,
            },
        )

    assert response.status_code == 202
    payload = response.json()
    assert payload["status"] == "completed"
    assert payload["provider_transaction_id"] == "ref-1001"
    assert payload["payment_list"] == {
        "status": "captured",
        "provider_transaction_id": "list-ref-1001",
        "authorization_code": "LISTAUTH",
        "failure_code": None,
        "updated_at": "2026-07-07T12:00:00+00:00",
        "error": None,
    }
    assert payload["three_ds"] is None


@pytest.mark.api
@pytest.mark.asyncio
async def test_payment_form_records_paynkolay_moto_provider_result_variant() -> None:
    final_result = PaynkolayPaymentResult.model_validate(
        {
            "RESPONSE_CODE": 2,
            "RESPONSE_DATA": "İşlem Başarılı",
            "USE_3D": "false",
            "RND": "1783940656135",
            "MERCHANT_NO": "400000273",
            "AUTH_CODE": "462514",
            "REFERENCE_CODE": "IKSIRPF530362",
            "CLIENT_REFERENCE_CODE": "order-web-moto-variant",
            "TimeStamp": None,
            "TRANSACTION_AMOUNT": "22.00",
            "AUTHORIZATION_AMOUNT": "22.00",
            "INSTALLMENT": "1",
            "CURRENCY_CODE": Currency.TRY,
            "BANK_REQUEST_MESSAGE": None,
            "hashDatav2": "hash",
        }
    )
    app = create_app()
    app.dependency_overrides[get_payment_initializer] = lambda: FakePaymentInitializer(
        provider_result=final_result
    )
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.post(
            "/api/payments",
            json={
                "order_id": "order-web-moto-variant",
                "amount": "22.00",
                "currency": "TRY",
                "card_number": "4546711234567894",
                "card_holder": "PAYNKOLAY TEST",
                "expiry_month": 12,
                "expiry_year": 2026,
                "cvv": "000",
                "requires_3ds": False,
                "installment_count": 1,
            },
        )

    assert response.status_code == 202
    payload = response.json()
    assert payload["status"] == "completed"
    assert payload["requires_3ds"] is False
    assert payload["provider_transaction_id"] == "IKSIRPF530362"
    assert payload["three_ds"] is None


@pytest.mark.api
@pytest.mark.asyncio
async def test_payment_form_records_provider_declined_init_result(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    declined_result = PaynkolayPaymentResult.model_validate(
        {
            "RESPONSE_CODE": 0,
            "RESPONSE_DATA": "İşlem Başarısız.",
            "TRANSACTION_AMOUNT": "22,00",
            "TimeStamp": "7/13/2026 2:05:18 PM",
            "BANK_REQUEST_MESSAGE": None,
            "hashDatav2": "declined-hash",
        }
    )

    async def fake_sleep(delay: float) -> None:
        return None

    monkeypatch.setattr(payment_list_retry, "async_sleep", fake_sleep)
    app = create_app()
    app.dependency_overrides[get_payment_initializer] = lambda: FakePaymentInitializer(
        provider_result=declined_result,
        status_fails=True,
    )
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.post(
            "/api/payments",
            json={
                "order_id": "order-web-provider-declined",
                "amount": "22.00",
                "currency": "TRY",
                "card_number": "6501738564461396",
                "card_holder": "PAYNKOLAY TEST",
                "expiry_month": 12,
                "expiry_year": 2026,
                "cvv": "000",
                "requires_3ds": True,
                "installment_count": 1,
            },
        )

    assert response.status_code == 202
    payload = response.json()
    assert payload["status"] == "failed"
    assert payload["provider_request"] == {
        "client_ref_code": "order-web-provider-declined",
        "amount": "22.00",
        "currency": "TRY",
        "use_3d": True,
        "installment_no": 1,
        "card_brand": "visa",
        "masked_pan": "650173******1396",
        "expiry_month": 12,
        "expiry_year": 2026,
        "transaction_type": "SALES",
        "payment_channel": "e_commerce",
        "success_url": "https://merchant.example.test/payments/result/success",
        "fail_url": "https://merchant.example.test/payments/result/fail",
    }
    assert payload["provider_response_code"] == "0"
    assert payload["provider_response_data"] == "İşlem Başarısız."
    assert payload["failure_reason"] == "İşlem Başarısız."
    assert "Provider code=0" in payload["message"]
    assert "provider message=İşlem Başarısız." in payload["message"]
    assert "VISA 650173******1396" in payload["message"]
    assert payload["three_ds"] is None
    assert "6501738564461396" not in response.text
    assert "000" not in response.text


@pytest.mark.api
@pytest.mark.asyncio
async def test_payment_form_keeps_final_result_when_payment_list_verification_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    final_result = PaynkolayPaymentResult.model_validate(
        {
            "RESPONSE_CODE": "2",
            "RESPONSE_DATA": "Islem Basarili",
            "USE_3D": "false",
            "RND": "rnd-1001",
            "MERCHANT_NO": "merchant-web",
            "AUTH_CODE": "AUTH1001",
            "REFERENCE_CODE": "ref-1001",
            "CLIENT_REFERENCE_CODE": "order-web-final",
            "TIMESTAMP": "2026-07-07T12:00:00+00:00",
            "TRANSACTION_AMOUNT": "100.00",
            "AUTHORIZATION_AMOUNT": "100.00",
            "INSTALLMENT": 1,
            "CURRENCY_CODE": Currency.TRY,
            "hashDataV2": "hash",
        }
    )

    async def fake_sleep(delay: float) -> None:
        return None

    monkeypatch.setattr(payment_list_retry, "async_sleep", fake_sleep)
    app = create_app()
    app.dependency_overrides[get_payment_initializer] = lambda: FakePaymentInitializer(
        provider_result=final_result,
        status_fails=True,
    )
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.post(
            "/api/payments",
            json={
                "order_id": "order-web-final",
                "amount": "100.00",
                "currency": "TRY",
                "card_number": "4111111111111111",
                "card_holder": "PAYNKOLAY TEST",
                "expiry_month": 12,
                "expiry_year": 2030,
                "cvv": "123",
                "requires_3ds": False,
                "installment_count": 1,
            },
        )

    assert response.status_code == 202
    payload = response.json()
    assert payload["status"] == "completed"
    assert payload["provider_transaction_id"] == "ref-1001"
    assert payload["provider_response_code"] == "2"
    assert payload["provider_response_data"] == "Islem Basarili"
    assert "Provider code=2" in payload["message"]
    assert "provider message=Islem Basarili" in payload["message"]
    assert payload["payment_list"] == {
        "status": None,
        "provider_transaction_id": None,
        "authorization_code": None,
        "failure_code": None,
        "updated_at": None,
        "error": "provider payment status verification failed",
    }


@pytest.mark.api
@pytest.mark.asyncio
async def test_payment_form_marks_session_failed_when_provider_initializer_fails() -> None:
    app = create_app()
    app.dependency_overrides[get_payment_initializer] = lambda: FakePaymentInitializer(fails=True)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.post(
            "/api/payments",
            json={
                "order_id": "order-provider-fails",
                "amount": "100.00",
                "currency": "TRY",
                "card_number": "4111111111111111",
                "card_holder": "PAYNKOLAY TEST",
                "expiry_month": 12,
                "expiry_year": 2030,
                "cvv": "123",
                "requires_3ds": True,
                "installment_count": 1,
            },
        )
        lookup_response = await client.get("/api/payments/order-provider-fails")

    assert response.status_code == 502
    assert lookup_response.status_code == 200
    assert lookup_response.json()["status"] == "failed"


@pytest.mark.api
@pytest.mark.asyncio
async def test_payment_form_rejects_duplicate_order_id(client: httpx.AsyncClient) -> None:
    payload = {
        "order_id": "order-web-duplicate",
        "amount": "100.00",
        "currency": "TRY",
        "card_number": "4111111111111111",
        "card_holder": "PAYNKOLAY TEST",
        "expiry_month": 12,
        "expiry_year": 2030,
        "cvv": "123",
        "requires_3ds": True,
        "installment_count": 1,
    }

    first_response = await client.post("/api/payments", json=payload)
    duplicate_response = await client.post("/api/payments", json=payload)

    assert first_response.status_code == 202
    assert duplicate_response.status_code == 409


@pytest.mark.api
@pytest.mark.asyncio
async def test_payment_lookup_returns_404_for_unknown_order(client: httpx.AsyncClient) -> None:
    response = await client.get("/api/payments/missing-order")

    assert response.status_code == 404


@pytest.mark.api
@pytest.mark.asyncio
async def test_payment_form_returns_503_without_runtime_config(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("PAYNKOLAY_CONFIG_FILE", raising=False)
    app = create_app()
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.post(
            "/api/payments",
            json={
                "amount": "100.00",
                "currency": "TRY",
                "card_number": "4111111111111111",
                "card_holder": "PAYNKOLAY TEST",
                "expiry_month": 12,
                "expiry_year": 2030,
                "cvv": "123",
                "requires_3ds": True,
                "installment_count": 1,
            },
        )

    assert response.status_code == 503


@pytest.mark.api
@pytest.mark.asyncio
async def test_payment_form_rejects_non_numeric_card_number(
    client: httpx.AsyncClient,
) -> None:
    response = await client.post(
        "/api/payments",
        json={
            "amount": "100.00",
            "currency": "TRY",
            "card_number": "41111111111x1111",
            "card_holder": "PAYNKOLAY TEST",
            "expiry_month": 12,
            "expiry_year": 2030,
            "cvv": "123",
            "requires_3ds": True,
            "installment_count": 1,
        },
    )

    assert response.status_code == 422
