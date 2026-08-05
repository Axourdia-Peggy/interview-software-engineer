"""Config catalog loading.

The three JSON catalogs under configs/ are the single source of truth for rules,
strategies and shift types. Code must not hard-code any value that already lives
in a catalog.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .models import ShiftType

DEFAULT_CONFIG_DIR = Path(__file__).resolve().parents[2] / "configs"

SUPPORTED_SCHEMA_VERSION = "1.2"


class ConfigError(RuntimeError):
    """Raised when a catalog is missing, malformed, or of an unsupported version."""


@dataclass(frozen=True)
class RuleDef:
    rule_id: str
    name: str
    severity: str
    description: str
    params: dict[str, Any]


@dataclass(frozen=True)
class StrategyDef:
    strategy_id: str
    display_name: str
    priority: int
    plugin: str
    selection_rules: dict[str, Any]
    tuning: dict[str, Any]


@dataclass(frozen=True)
class CatalogBundle:
    rules: tuple[RuleDef, ...]
    strategies: tuple[StrategyDef, ...]
    shift_types: tuple[ShiftType, ...]

    def shift_type(self, shift_type_id: str) -> ShiftType:
        for shift_type in self.shift_types:
            if shift_type.shift_type_id == shift_type_id:
                return shift_type
        raise ConfigError(f"unknown shift_type_id: {shift_type_id}")

    def rule(self, name: str) -> RuleDef:
        for rule in self.rules:
            if rule.name == name:
                return rule
        raise ConfigError(f"unknown rule name: {name}")


def _read_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise ConfigError(f"catalog not found: {path}")
    try:
        with path.open(encoding="utf-8") as handle:
            return json.load(handle)
    except json.JSONDecodeError as exc:
        raise ConfigError(f"catalog is not valid JSON: {path}: {exc}") from exc


def _check_version(payload: dict[str, Any], path: Path) -> None:
    version = payload.get("schema_version")
    if version != SUPPORTED_SCHEMA_VERSION:
        raise ConfigError(
            f"{path.name} declares schema_version {version!r}, "
            f"this build supports {SUPPORTED_SCHEMA_VERSION!r}"
        )


def load_catalogs(config_dir: Path | None = None) -> CatalogBundle:
    """Load all three catalogs and return them as one immutable bundle."""
    base = config_dir or DEFAULT_CONFIG_DIR

    rules_payload = _read_json(base / "rule_catalog.json")
    _check_version(rules_payload, base / "rule_catalog.json")
    rules = tuple(
        RuleDef(
            rule_id=entry["rule_id"],
            name=entry["name"],
            severity=entry["severity"],
            description=entry["description"],
            params=entry.get("params", {}),
        )
        for entry in rules_payload["rules"]
    )

    strategy_payload = _read_json(base / "strategy_catalog.json")
    _check_version(strategy_payload, base / "strategy_catalog.json")
    strategies = tuple(
        sorted(
            (
                StrategyDef(
                    strategy_id=entry["strategy_id"],
                    display_name=entry["display_name"],
                    priority=entry["priority"],
                    plugin=entry["plugin"],
                    selection_rules=entry.get("selection_rules", {}),
                    tuning=entry.get("tuning", {}),
                )
                for entry in strategy_payload["strategies"]
            ),
            key=lambda item: item.priority,
        )
    )

    shift_payload = _read_json(base / "shift_types.json")
    _check_version(shift_payload, base / "shift_types.json")
    shift_types = tuple(
        ShiftType(
            shift_type_id=entry["shift_type_id"],
            display_name=entry["display_name"],
            start_hour=entry["start_hour"],
            end_hour=entry["end_hour"],
            duration_hours=entry["duration_hours"],
        )
        for entry in shift_payload["shift_types"]
    )

    return CatalogBundle(rules=rules, strategies=strategies, shift_types=shift_types)
