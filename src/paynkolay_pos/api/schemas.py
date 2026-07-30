"""Pydantic schemas used by the FastAPI web layer."""

from __future__ import annotations

from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel, Field, SecretStr, field_validator, model_validator

from paynkolay_pos.api.session_models import (
    PaymentSession,
    PaymentSessionStatus,
    ProviderRequestSummary,
    ThreeDSAutomationSummary,
)
from paynkolay_pos.config import CardBrand
from paynkolay_pos.models import Currency


class HealthResponse(BaseModel):
    """Health check payload returned by the web app."""

    status: Literal["ok"]
    service: str
    version: str


class ConfigResponse(BaseModel):
    """Safe runtime metadata exposed to the browser."""

    runtime_configured: bool
    active_environment: str | None = None
    supported_currencies: list[str]
    supported_card_brands: list[str]
    payment_channels: list[str]
    card_aliases: list[str] = Field(default_factory=list)
    message: str | None = None


class TestCardFormFill(BaseModel):
    """Local tester UI card data used to prefill the payment form."""

    alias: str
    brand: str
    flow_type: Literal["secure", "moto"]
    card_number: str
    cvv: str
    expiry_month: int
    expiry_year: int
    card_holder: str = "PAYNKOLAY TEST"
    requires_3ds: bool
    has_expected_otp: bool
    automation_status: Literal[
        "success_auto",
        "automation_diagnostic",
        "manual_only",
        "quarantined",
        "unknown",
    ]
    automation_reason: str
    diagnostic_class: str
    automatic_success_candidate: bool


class TestCardListResponse(BaseModel):
    """Runtime test cards available for browser form-fill selection."""

    environment: str
    cards: list[TestCardFormFill]


class TestCardCreateRequest(BaseModel):
    """Browser payload for adding a local runtime test card."""

    alias: str = Field(min_length=1, max_length=80, pattern=r"^[a-z0-9][a-z0-9_-]*$")
    brand: CardBrand
    card_number: SecretStr = Field(min_length=12, max_length=19)
    cvv: SecretStr = Field(min_length=3, max_length=4)
    expiry_month: int = Field(ge=1, le=12)
    expiry_year: int = Field(ge=2026, le=2100)
    flow_type: Literal["secure", "moto"]
    expected_otp: SecretStr | None = Field(default=None, min_length=1, max_length=12)

    @model_validator(mode="after")
    def validate_card_data(self) -> TestCardCreateRequest:
        """Keep UI-created card data compatible with runtime TestCard validation."""

        card_number = self.card_number.get_secret_value()
        if not card_number.isdigit():
            raise ValueError("card_number must contain digits only")

        cvv = self.cvv.get_secret_value()
        if not cvv.isdigit():
            raise ValueError("cvv must contain digits only")

        if self.flow_type == "secure" and self.expected_otp is not None:
            otp = self.expected_otp.get_secret_value()
            if not otp.isdigit():
                raise ValueError("expected_otp must contain digits only")
        if self.flow_type == "moto" and self.expected_otp is not None:
            raise ValueError("MoTo cards must not define expected_otp")
        return self


class InstallmentOptionsRequest(BaseModel):
    """Browser request for available installment options."""

    amount: Decimal = Field(gt=Decimal("0"), max_digits=12, decimal_places=2)
    currency: Currency = Currency.TRY
    card_brand: CardBrand
    card_number: SecretStr = Field(min_length=12, max_length=19)
    requires_3ds: bool

    @field_validator("amount")
    @classmethod
    def normalize_amount(cls, amount: Decimal) -> Decimal:
        """Keep installment amount calculations deterministic."""

        return amount.quantize(Decimal("0.01"))

    def model_post_init(self, __context: object) -> None:
        """Validate sensitive numeric fields after SecretStr parsing."""

        card_number = self.card_number.get_secret_value()
        if not card_number.isdigit():
            raise ValueError("card_number must contain digits only")

    @property
    def canonical_amount(self) -> str:
        """Return the exact amount string shown in installment options."""

        return f"{self.amount:.2f}"


class InstallmentOption(BaseModel):
    """One selectable installment option returned to the browser."""

    installment_count: int = Field(ge=1, le=12)
    label: str
    total_amount: str
    monthly_amount: str
    commission_amount: str = "0.00"
    commission_rate: str = "0.00"
    encoded_value: str | None = Field(default=None, repr=False)


class InstallmentOptionsResponse(BaseModel):
    """Installment options for a card/amount pair."""

    default_installment: int = 1
    source: Literal["local_stub", "paynkolay_uat"]
    options: list[InstallmentOption]


class ConfigCardSummary(BaseModel):
    """Safe test card metadata for tester visibility."""

    alias: str
    brand: str
    requires_3ds: bool
    has_expected_otp: bool
    automation_status: Literal[
        "success_auto",
        "automation_diagnostic",
        "manual_only",
        "quarantined",
        "unknown",
    ]
    automation_reason: str
    diagnostic_class: str
    automatic_success_candidate: bool


class ConfigMerchantSummary(BaseModel):
    """Masked merchant metadata for tester visibility."""

    merchant_id: str
    terminal_id: str
    has_list_key: bool
    has_cancel_refund_key: bool


class MerchantSettingsResponse(BaseModel):
    """Editable merchant metadata that never returns the configured SX value."""

    environment: str
    merchant_no: str
    payment_sx_configured: bool
    message: str | None = None


class MerchantSettingsUpdateRequest(BaseModel):
    """Safe browser request for updating active payment credentials."""

    model_config = {"str_strip_whitespace": True}

    environment: str = Field(min_length=1, max_length=16)
    merchant_no: str = Field(min_length=1, max_length=32, pattern=r"^\d+$")
    payment_sx: SecretStr | None = Field(default=None, repr=False)


class ConfigScenarioCoverage(BaseModel):
    """Aggregate scenario coverage counts safe for browser display."""

    three_ds_count: int = 0
    moto_count: int = 0
    single_payment_count: int = 0
    installment_count: int = 0
    negative_count: int = 0
    payment_channel_counts: dict[str, int] = Field(default_factory=dict)
    final_status_counts: dict[str, int] = Field(default_factory=dict)
    installment_counts: dict[str, int] = Field(default_factory=dict)
    error_code_counts: dict[str, int] = Field(default_factory=dict)


class ConfigScenarioSummary(BaseModel):
    """Safe scenario catalogue metadata for tester visibility."""

    configured: bool
    source: str
    scenario_count: int = 0
    tags: list[str] = Field(default_factory=list)
    coverage: ConfigScenarioCoverage = Field(default_factory=ConfigScenarioCoverage)
    message: str | None = None


class ConfigReadinessIssueSummary(BaseModel):
    """One safe readiness issue exposed to the browser."""

    code: str
    message: str


class ConfigReadinessSummary(BaseModel):
    """Sandbox readiness metadata for tester visibility."""

    checked: bool
    ready: bool = False
    issue_count: int = 0
    issues: list[ConfigReadinessIssueSummary] = Field(default_factory=list)
    message: str | None = None


class ConfigOverviewResponse(BaseModel):
    """Safe operational overview for the tester UI."""

    runtime_configured: bool
    active_environment: str | None = None
    config_source: str | None = None
    base_url_configured: bool = False
    callback_configured: bool = False
    merchant: ConfigMerchantSummary | None = None
    card_count: int = 0
    cards: list[ConfigCardSummary] = Field(default_factory=list)
    scenarios: ConfigScenarioSummary
    readiness: ConfigReadinessSummary
    message: str | None = None


class PaymentFormRequest(BaseModel):
    """Payment form payload accepted from the browser."""

    order_id: str | None = Field(default=None, min_length=1, max_length=64)
    amount: Decimal = Field(gt=Decimal("0"), max_digits=12, decimal_places=2)
    currency: Currency = Currency.TRY
    card_brand: CardBrand = CardBrand.VISA
    card_number: SecretStr = Field(min_length=12, max_length=19)
    card_holder: str = Field(min_length=1, max_length=64)
    expiry_month: int = Field(ge=1, le=12)
    expiry_year: int = Field(ge=2026, le=2100)
    cvv: SecretStr = Field(min_length=3, max_length=4)
    requires_3ds: bool = True
    installment_count: int = Field(default=1, ge=1, le=12)
    installment_encoded_value: SecretStr | None = Field(
        default=None,
        min_length=1,
        max_length=4096,
        repr=False,
    )
    auto_complete_3ds: bool = False

    @field_validator("amount")
    @classmethod
    def normalize_amount(cls, amount: Decimal) -> Decimal:
        """Keep browser-submitted amounts in provider-friendly two-decimal format."""

        return amount.quantize(Decimal("0.01"))

    def model_post_init(self, __context: object) -> None:
        """Validate sensitive numeric fields after SecretStr parsing."""

        card_number = self.card_number.get_secret_value()
        if not card_number.isdigit():
            raise ValueError("card_number must contain digits only")

        cvv = self.cvv.get_secret_value()
        if not cvv.isdigit():
            raise ValueError("cvv must contain digits only")

    @property
    def canonical_amount(self) -> str:
        """Return the exact amount string used in UI responses."""

        return f"{self.amount:.2f}"


class PaymentFormResponse(BaseModel):
    """Payment creation response returned to the browser."""

    order_id: str
    status: PaymentSessionStatus
    amount: str
    currency: Currency
    masked_pan: str
    requires_3ds: bool
    provider_request: ProviderRequestSummary | None = None
    provider_transaction_id: str | None = None
    provider_response_code: str | None = None
    provider_response_data: str | None = None
    failure_reason: str | None = None
    payment_list: PaymentListStatusSummary | None = None
    three_ds_automation: ThreeDSAutomationSummary | None = None
    three_ds: dict[str, str] | None = None
    message: str
    links: dict[str, str]

    @classmethod
    def from_session(
        cls,
        session: PaymentSession,
        *,
        message: str = "Payment session created; provider execution will be attached in phase 3.",
        three_ds: dict[str, str] | None = None,
    ) -> PaymentFormResponse:
        """Build a browser response from sanitized session state."""

        links = {
            "status": f"/api/payments/{session.order_id}",
            "result": f"/result?order_id={session.order_id}",
        }
        if three_ds is not None:
            links["three_ds"] = three_ds["render_url"]
        return cls(
            order_id=session.order_id,
            status=session.status,
            amount=session.canonical_amount,
            currency=session.currency,
            masked_pan=session.masked_pan,
            requires_3ds=session.requires_3ds,
            provider_request=session.provider_request,
            provider_transaction_id=session.provider_transaction_id,
            provider_response_code=session.provider_response_code,
            provider_response_data=session.provider_response_data,
            failure_reason=session.failure_reason,
            payment_list=PaymentListStatusSummary.from_session(session),
            three_ds_automation=session.three_ds_automation,
            three_ds=three_ds,
            message=message,
            links=links,
        )


class PaymentListStatusSummary(BaseModel):
    """Sanitized PaymentList verification evidence shown in the browser."""

    status: str | None = None
    provider_transaction_id: str | None = None
    authorization_code: str | None = None
    failure_code: str | None = None
    updated_at: str | None = None
    error: str | None = None

    @classmethod
    def from_session(cls, session: PaymentSession) -> PaymentListStatusSummary | None:
        """Build PaymentList evidence from a session when verification was attempted."""

        if session.payment_list_status is None and session.payment_list_error is None:
            return None
        return cls(
            status=session.payment_list_status.value
            if session.payment_list_status is not None
            else None,
            provider_transaction_id=session.payment_list_provider_transaction_id,
            authorization_code=session.payment_list_authorization_code,
            failure_code=session.payment_list_failure_code,
            updated_at=session.payment_list_updated_at.isoformat()
            if session.payment_list_updated_at is not None
            else None,
            error=session.payment_list_error,
        )


class PaymentLookupResponse(BaseModel):
    """Sanitized payment session state returned by lookup routes."""

    order_id: str
    status: PaymentSessionStatus
    amount: str
    currency: Currency
    masked_pan: str
    card_holder: str
    requires_3ds: bool
    installment_count: int
    provider_transaction_id: str | None = None
    failure_reason: str | None = None
    payment_list: PaymentListStatusSummary | None = None
    three_ds_automation: ThreeDSAutomationSummary | None = None
    created_at: str
    updated_at: str
    links: dict[str, str]

    @classmethod
    def from_session(cls, session: PaymentSession) -> PaymentLookupResponse:
        """Build a lookup response from sanitized session state."""

        links = {
            "result": f"/result?order_id={session.order_id}",
        }
        if session.status in {
            PaymentSessionStatus.PENDING_3DS,
            PaymentSessionStatus.THREE_DS_RENDERED,
        }:
            links["three_ds"] = f"/payments/{session.order_id}/three-ds"
        return cls(
            order_id=session.order_id,
            status=session.status,
            amount=session.canonical_amount,
            currency=session.currency,
            masked_pan=session.masked_pan,
            card_holder=session.card_holder,
            requires_3ds=session.requires_3ds,
            installment_count=session.installment_count,
            provider_transaction_id=session.provider_transaction_id,
            failure_reason=session.failure_reason,
            payment_list=PaymentListStatusSummary.from_session(session),
            three_ds_automation=session.three_ds_automation,
            created_at=session.created_at.isoformat(),
            updated_at=session.updated_at.isoformat(),
            links=links,
        )


class ParallelRunManualCardSelection(BaseModel):
    """One card selection for a manual parallel run."""

    alias: str = Field(min_length=1, max_length=120)
    repeat_count: int = Field(ge=1, le=150)


class ParallelRunCreateRequest(BaseModel):
    """Browser request to start a parallel payment initialization run."""

    mode: Literal["manual", "random"]
    execution_profile: Literal["stable", "load"] = "stable"
    concurrency: int = Field(default=10, ge=1, le=150)
    acs_concurrency: int | None = Field(default=None, ge=1, le=150)
    amount: Decimal = Field(gt=Decimal("0"), max_digits=12, decimal_places=2)
    currency: Currency = Currency.TRY
    installment_count: int = Field(default=1, ge=1, le=12)
    auto_complete_3ds: bool = False
    manual_cards: list[ParallelRunManualCardSelection] = Field(default_factory=list)
    random_count: int | None = Field(default=None, ge=1, le=150)

    @field_validator("amount")
    @classmethod
    def normalize_amount(cls, amount: Decimal) -> Decimal:
        """Keep batch amounts in provider-friendly two-decimal format."""

        return amount.quantize(Decimal("0.01"))

    @model_validator(mode="after")
    def validate_mode_inputs(self) -> ParallelRunCreateRequest:
        """Require exactly the selection input needed by the selected mode."""

        if self.mode == "manual":
            if not self.manual_cards:
                raise ValueError("manual mode requires at least one card selection")
            if sum(item.repeat_count for item in self.manual_cards) > 150:
                raise ValueError("manual mode can create at most 150 test items")
            if self.random_count is not None:
                raise ValueError("manual mode must not define random_count")
        if self.mode == "random":
            if self.random_count is None:
                raise ValueError("random mode requires random_count")
            if self.manual_cards:
                raise ValueError("random mode must not define manual_cards")
        if self.execution_profile == "stable" and self.acs_concurrency is not None:
            raise ValueError("stable profile manages acs_concurrency automatically")
        return self

    @property
    def effective_acs_concurrency(self) -> int:
        """Return the scheduler ceiling selected for this run."""

        return self.acs_concurrency or self.concurrency


ParallelRunItemAutomationStatus = Literal[
    "success_auto",
    "automation_diagnostic",
    "manual_only",
    "quarantined",
    "unknown",
]


class ParallelRunStageTimings(BaseModel):
    """Per-stage timings for one parallel payment item."""

    installment_lookup_ms: int | None = Field(default=None, ge=0)
    initialization_ms: int | None = Field(default=None, ge=0)
    acs_wait_ms: int | None = Field(default=None, ge=0)
    acs_duration_ms: int | None = Field(default=None, ge=0)
    payment_list_ms: int | None = Field(default=None, ge=0)


class ParallelRunItemResponse(BaseModel):
    """One item result in a parallel payment initialization run."""

    item_id: str
    card_alias: str
    attempt_index: int
    order_id: str
    status: Literal["pending", "running", "completed", "failed"]
    classification: str
    requires_3ds: bool
    installment_count: int = Field(ge=1, le=12)
    installment_source: Literal["local_stub", "paynkolay_uat"] | None = None
    automation_status: ParallelRunItemAutomationStatus
    automation_reason: str
    diagnostic_class: str
    automatic_success_candidate: bool
    provider_request: ProviderRequestSummary | None = None
    provider_response_code: str | None = None
    provider_response_data: str | None = None
    payment_list: PaymentListStatusSummary | None = None
    payment_list_status: str | None = None
    payment_list_error: str | None = None
    three_ds_automation: ThreeDSAutomationSummary | None = None
    error_message: str | None = None
    duration_ms: int | None = None
    stage_timings: ParallelRunStageTimings = Field(default_factory=ParallelRunStageTimings)
    three_ds_url: str | None = None


class AcsPoolMetrics(BaseModel):
    """Observed adaptive capacity for one provider/card ACS lane."""

    initial_limit: int = Field(ge=1)
    final_limit: int = Field(ge=1)
    maximum_limit: int = Field(ge=1)
    peak_concurrency: int = Field(ge=0)


class AcsSchedulerMetrics(BaseModel):
    """Requested and observed browser automation concurrency."""

    profile: Literal["stable", "load"]
    requested_concurrency: int = Field(ge=1)
    peak_concurrency: int = Field(ge=0)
    pools: dict[str, AcsPoolMetrics] = Field(default_factory=dict)


class ParallelRunMetrics(BaseModel):
    """Aggregate performance metrics for a parallel run."""

    elapsed_ms: int | None = Field(default=None, ge=0)
    throughput_per_second: float | None = Field(default=None, ge=0)
    p50_duration_ms: int | None = Field(default=None, ge=0)
    p95_duration_ms: int | None = Field(default=None, ge=0)
    peak_active_items: int = Field(default=0, ge=0)
    classifications: dict[str, int] = Field(default_factory=dict)


class ParallelRunResponse(BaseModel):
    """Summary response for a parallel payment initialization run."""

    run_id: str
    mode: Literal["manual", "random"]
    execution_profile: Literal["stable", "load"]
    status: Literal["pending", "running", "completed", "completed_with_failures", "failed"]
    concurrency: int
    acs_concurrency: int
    installment_count: int = Field(ge=1, le=12)
    total: int
    completed: int
    failed: int
    started_at: str | None = None
    finished_at: str | None = None
    evidence_path: str | None = None
    message: str
    acs_scheduler: AcsSchedulerMetrics
    metrics: ParallelRunMetrics
    items: list[ParallelRunItemResponse] = Field(default_factory=list)


class ReportStatusResponse(BaseModel):
    """Local Allure report status exposed to the browser."""

    available: bool
    report_path: str
    entrypoint: str | None = None
    message: str


class ReportTestResultSummary(BaseModel):
    """Safe summary of one local Allure test result."""

    name: str
    status: str
    suite: str | None = None
    duration_ms: int | None = None
    started_at: str | None = None


class ReportRunSummary(BaseModel):
    """Aggregate summary of the latest local Allure result directory."""

    total: int = 0
    passed: int = 0
    failed: int = 0
    broken: int = 0
    skipped: int = 0
    unknown: int = 0
    started_at: str | None = None
    finished_at: str | None = None
    duration_ms: int | None = None
    recent_tests: list[ReportTestResultSummary] = Field(default_factory=list)


class ReportHistoryResponse(BaseModel):
    """Local test result history exposed to the browser."""

    available: bool
    results_path: str
    latest: ReportRunSummary | None = None
    message: str


class ParallelEvidenceRunSummary(BaseModel):
    """Safe summary of one persisted parallel run evidence file."""

    run_id: str
    status: str
    total: int
    completed: int
    failed: int
    finished_at: str | None = None
    evidence_path: str
    classifications: dict[str, int] = Field(default_factory=dict)


class ParallelEvidenceResponse(BaseModel):
    """Persisted parallel run evidence exposed to the browser."""

    available: bool
    evidence_path: str
    runs: list[ParallelEvidenceRunSummary] = Field(default_factory=list)
    message: str


class ParallelEvidenceDetailResponse(BaseModel):
    """One persisted parallel run evidence document."""

    run_id: str
    evidence_path: str
    evidence: dict[str, Any]


class ReportCommandRunResponse(BaseModel):
    """Status of a local tester-triggered report command."""

    status: Literal["idle", "running", "passed", "failed"]
    command: list[str]
    started_at: str | None = None
    finished_at: str | None = None
    exit_code: int | None = None
    output_tail: str | None = None
    message: str
