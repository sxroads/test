"""Runtime configuration models for Sanal POS automation.

The framework keeps environment-specific payment data outside test code. A test chooses
DEV, UAT, or TEST at runtime, then this module validates the selected provider endpoint,
merchant profile, and card data before any transaction is attempted.
"""

from __future__ import annotations

import os
from enum import StrEnum
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field, SecretStr


class StrictConfigModel(BaseModel):
    """Base model that rejects unknown config keys and trims string values."""

    model_config = {"extra": "forbid", "str_strip_whitespace": True}


class EnvironmentName(StrEnum):
    """Supported execution environments for the payment test suite."""

    DEV = "dev"
    UAT = "uat"
    TEST = "test"


class CardBrand(StrEnum):
    """Card schemes commonly used in Sanal POS test scenarios."""

    VISA = "visa"
    MASTERCARD = "mastercard"
    TROY = "troy"


class MerchantProfile(StrictConfigModel):
    """Merchant credentials used to authenticate and sign payment requests."""

    merchant_id: str = Field(min_length=1)
    terminal_id: str = Field(min_length=1)
    api_key: SecretStr = Field(min_length=1)
    installment_api_key: SecretStr | None = Field(default=None, min_length=1)
    list_api_key: SecretStr | None = Field(default=None, min_length=1)
    cancel_refund_api_key: SecretStr | None = Field(default=None, min_length=1)
    secret_key: SecretStr = Field(min_length=1)


class TestCard(StrictConfigModel):
    """Validated test card metadata for data-driven payment scenarios."""

    alias: str = Field(min_length=1)
    brand: CardBrand
    pan: SecretStr = Field(min_length=12, max_length=19)
    expiry_month: int = Field(ge=1, le=12)
    expiry_year: int = Field(ge=2026, le=2100)
    cvv: SecretStr = Field(min_length=3, max_length=4)
    requires_3ds: bool
    expected_otp: SecretStr | None = None

    def model_post_init(self, __context: Any) -> None:
        """Validate card digits and 3DS OTP consistency after Pydantic parsing."""

        pan = self.pan.get_secret_value()
        if not pan.isdigit():
            raise ValueError("card PAN must contain digits only")

        cvv = self.cvv.get_secret_value()
        if not cvv.isdigit():
            raise ValueError("card CVV must contain digits only")

        if not self.requires_3ds and self.expected_otp is not None:
            raise ValueError("non-3DS test cards must not define expected_otp")


class PaymentEnvironment(StrictConfigModel):
    """Endpoint, merchant, and card set for one runtime environment."""

    name: EnvironmentName
    base_url: str = Field(pattern=r"^https://", min_length=12)
    callback_base_url: str = Field(pattern=r"^https://", min_length=12)
    merchant: MerchantProfile
    cards: list[TestCard] = Field(min_length=1)

    def model_post_init(self, __context: Any) -> None:
        """Prevent ambiguous data-driven tests by requiring unique card aliases."""

        aliases = [card.alias for card in self.cards]
        if len(aliases) != len(set(aliases)):
            raise ValueError("card aliases must be unique within an environment")


class RuntimeSettings(StrictConfigModel):
    """Top-level settings document containing every configured payment environment."""

    active_environment: EnvironmentName
    environments: dict[EnvironmentName, PaymentEnvironment] = Field(min_length=1)

    def model_post_init(self, __context: Any) -> None:
        """Ensure the selected environment has a matching configuration block."""

        if self.active_environment not in self.environments:
            raise ValueError(
                f"active environment {self.active_environment!s} is not configured"
            )
        configured_environment = self.environments[self.active_environment]
        if configured_environment.name != self.active_environment:
            raise ValueError("environment key and environment.name must match")

    @property
    def current(self) -> PaymentEnvironment:
        """Return the selected payment environment after validation."""

        return self.environments[self.active_environment]


def load_runtime_settings(
    *,
    config_file_env: str = "PAYNKOLAY_CONFIG_FILE",
    active_environment_env: str = "PAYNKOLAY_ENV",
) -> RuntimeSettings:
    """Load and validate runtime settings from a JSON file and environment variables.

    The JSON file holds the environment catalogue. The active environment can be changed
    without editing the file by setting PAYNKOLAY_ENV to dev, uat, or test.
    """

    config_path_value = os.getenv(config_file_env)
    if not config_path_value:
        raise RuntimeError(f"{config_file_env} must point to a configuration JSON file")

    config_path = Path(config_path_value).expanduser()
    if not config_path.is_file():
        raise FileNotFoundError(f"configuration file does not exist: {config_path}")

    raw_payload = config_path.read_text(encoding="utf-8")
    settings = RuntimeSettings.model_validate_json(raw_payload)

    active_environment_value = os.getenv(active_environment_env)
    if active_environment_value:
        settings = settings.model_copy(
            update={"active_environment": EnvironmentName(active_environment_value)}
        )
        settings = RuntimeSettings.model_validate(settings.model_dump())

    return settings
