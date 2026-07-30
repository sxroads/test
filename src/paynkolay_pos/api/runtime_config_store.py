"""Serialized, atomic updates for the private runtime configuration file."""

from __future__ import annotations

import asyncio
import json
import os
import stat
import tempfile
from collections.abc import Callable
from pathlib import Path
from typing import TypeVar

from paynkolay_pos.config import EnvironmentName, RuntimeSettings

CONFIG_FILE_ENV = "PAYNKOLAY_CONFIG_FILE"
ACTIVE_ENVIRONMENT_ENV = "PAYNKOLAY_ENV"

MutationResult = TypeVar("MutationResult")
RuntimeConfigMutation = Callable[[dict[str, object], str], MutationResult]

_runtime_config_lock = asyncio.Lock()


def runtime_config_path() -> Path:
    """Return the configured private runtime file path."""

    config_path_value = os.getenv(CONFIG_FILE_ENV)
    if not config_path_value:
        raise RuntimeError(f"{CONFIG_FILE_ENV} must point to a configuration JSON file")
    config_path = Path(config_path_value).expanduser()
    if not config_path.is_file():
        raise FileNotFoundError(f"configuration file does not exist: {config_path}")
    return config_path


async def mutate_runtime_config(
    mutation: RuntimeConfigMutation[MutationResult],
) -> MutationResult:
    """Apply one validated mutation and atomically replace the runtime config."""

    async with _runtime_config_lock:
        config_path = runtime_config_path()
        payload = json.loads(config_path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("runtime configuration must be a JSON object")

        settings = RuntimeSettings.model_validate(payload)
        active_environment = _active_environment(settings)
        result = mutation(payload, active_environment.value)
        RuntimeSettings.model_validate(payload)
        _write_atomic(config_path, payload)
        return result


def _active_environment(settings: RuntimeSettings) -> EnvironmentName:
    override = os.getenv(ACTIVE_ENVIRONMENT_ENV)
    if override is None:
        return settings.active_environment

    active_environment = EnvironmentName(override)
    if active_environment not in settings.environments:
        raise ValueError(
            f"active environment {active_environment.value!r} is not configured"
        )
    return active_environment


def _write_atomic(config_path: Path, payload: dict[str, object]) -> None:
    existing_mode = stat.S_IMODE(config_path.stat().st_mode)
    temp_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=config_path.parent,
            prefix=f".{config_path.name}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            temp_path = Path(handle.name)
            handle.write(f"{json.dumps(payload, indent=2, ensure_ascii=False)}\n")
            handle.flush()
            os.fsync(handle.fileno())
        temp_path.chmod(existing_mode)
        os.replace(temp_path, config_path)
    except Exception:
        if temp_path is not None:
            temp_path.unlink(missing_ok=True)
        raise
