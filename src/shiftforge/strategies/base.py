"""Strategy plugin contract and loader."""

from __future__ import annotations

import importlib
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import date
from typing import Any

from ..config import CatalogBundle, ConfigError, StrategyDef
from ..models import Assignment, Roster, ScheduleSpec, Slot


@dataclass
class StrategyContext:
    """Everything a strategy is allowed to see, plus the knobs the loop turns.

    `pressure` is raised by the decision loop on every retry within the same
    strategy. A strategy is expected to relax its own preferences as pressure
    grows, without ever breaking a hard rule.
    """

    spec: ScheduleSpec
    catalogs: CatalogBundle
    tuning: dict[str, Any]
    pressure: int = 0
    notes: list[str] = field(default_factory=list)


class IScheduleStrategy(ABC):
    """Contract every schedule strategy must satisfy."""

    strategy_id: str = "unnamed"

    @abstractmethod
    def build(self, slots: list[Slot], context: StrategyContext) -> Roster:
        """Assign employees to slots and return a candidate roster."""

    # --- helpers shared by all strategies -------------------------------

    @staticmethod
    def eligible(
        employee_id: str,
        slot: Slot,
        spec: ScheduleSpec,
        taken_days: dict[str, set[date]],
        shift_history: dict[str, dict[date, str]],
    ) -> bool:
        """Hard-rule gate applied before any preference ordering.

        Mirrors R002 (qualification), R003 (no double booking), R004 (rest) and
        the per-employee max_shifts ceiling. Strategies must call this so a
        candidate roster never violates a hard rule by construction.
        """
        employee = spec.employee_by_id(employee_id)

        if not employee.can_perform(slot.role):
            return False
        if not spec.is_available(employee_id, slot.day):
            return False
        if slot.day in taken_days.get(employee_id, set()):
            return False
        if len(taken_days.get(employee_id, set())) >= employee.max_shifts:
            return False

        # R004: a night shift must not be followed by a morning shift.
        from datetime import timedelta

        previous_day = slot.day - timedelta(days=1)
        previous_shift = shift_history.get(employee_id, {}).get(previous_day)
        return not (previous_shift == "night" and slot.shift_type_id == "morning")

    @staticmethod
    def commit(
        roster: Roster,
        slot: Slot,
        employee_id: str,
        taken_days: dict[str, set[date]],
        shift_history: dict[str, dict[date, str]],
    ) -> None:
        """Record an assignment and update the running bookkeeping."""
        roster.assignments.append(Assignment(slot=slot, employee_id=employee_id))
        taken_days.setdefault(employee_id, set()).add(slot.day)
        shift_history.setdefault(employee_id, {})[slot.day] = slot.shift_type_id


def load_strategy(definition: StrategyDef) -> IScheduleStrategy:
    """Instantiate a strategy from its 'module:ClassName' plugin path."""
    target = definition.plugin
    if ":" not in target:
        raise ConfigError(f"plugin path must be 'module:ClassName', got {target!r}")

    module_name, class_name = target.split(":", 1)
    try:
        module = importlib.import_module(module_name)
    except ImportError as exc:
        raise ConfigError(f"cannot import strategy module {module_name!r}: {exc}") from exc

    try:
        cls = getattr(module, class_name)
    except AttributeError as exc:
        raise ConfigError(f"module {module_name!r} has no class {class_name!r}") from exc

    instance = cls()
    instance.strategy_id = definition.strategy_id
    return instance
