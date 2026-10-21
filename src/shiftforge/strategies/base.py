"""Strategy plugin contract and loader."""

from __future__ import annotations

import importlib
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import date, timedelta
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

    def max_consecutive_days(self) -> int | None:
        """The R005 limit as declared by the rule catalog, or None if absent."""
        try:
            rule = self.catalogs.rule("max_consecutive_days")
        except ConfigError:
            return None
        return rule.params.get("max_days")

    def forbidden_transitions(self) -> frozenset[tuple[str, str]]:
        """The R004 (previous day, next day) shift pairs declared by the rule catalog.

        Empty when the catalog declares no R004 rule, in which case the validator
        does not check it either.
        """
        try:
            rule = self.catalogs.rule("rest_between_shifts")
        except ConfigError:
            return frozenset()
        if "forbidden_transitions" not in rule.params:
            raise ConfigError(
                f"rule {rule.rule_id} ({rule.name!r}) is missing required param "
                f"'forbidden_transitions' in the rule catalog"
            )
        return frozenset(tuple(pair) for pair in rule.params["forbidden_transitions"])


class IScheduleStrategy(ABC):
    """Contract every schedule strategy must satisfy."""

    strategy_id: str = "unnamed"

    @abstractmethod
    def build(self, slots: list[Slot], context: StrategyContext) -> Roster:
        """Assign employees to slots and return a candidate roster."""

    # --- bookkeeping -----------------------------------------------------

    def ledger(self) -> dict[str, set[date]]:
        """A fresh booking ledger: which calendar days each employee is committed to.

        Every build starts from an empty roster, so the ledger must not be shared
        across builds or across strategy instances. Call it once per build.
        """
        return {}

    # --- helpers shared by all strategies -------------------------------

    def eligible(
        self,
        employee_id: str,
        slot: Slot,
        spec: ScheduleSpec,
        taken_days: dict[str, set[date]],
        shift_history: dict[str, dict[date, str]],
        max_consecutive_days: int | None,
        forbidden_transitions: frozenset[tuple[str, str]],
    ) -> bool:
        """Hard-rule gate applied before any preference ordering.

        Mirrors R002 (qualification), R003 (no double booking), R004 (rest),
        R005 (consecutive days), the unavailability list and the per-employee
        max_shifts ceiling. Strategies must call this so a candidate roster
        never violates a hard rule by construction.
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

        # R004: the previous day's shift and this one must not be a forbidden pair.
        previous_day = slot.day - timedelta(days=1)
        previous_shift = shift_history.get(employee_id, {}).get(previous_day)
        if (previous_shift, slot.shift_type_id) in forbidden_transitions:
            return False

        # R005: taking this slot must not create an over-long consecutive run.
        if max_consecutive_days is not None:
            booked = taken_days.get(employee_id, set())
            run = 1
            cursor = slot.day - timedelta(days=1)
            while cursor in booked:
                run += 1
                cursor -= timedelta(days=1)
            cursor = slot.day + timedelta(days=1)
            while cursor in booked:
                run += 1
                cursor += timedelta(days=1)
            if run > max_consecutive_days:
                return False

        return True

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


# --- composable eligibility gates ---------------------------------------
#
# Being pulled out of the monolithic gate above one rule at a time, so a
# strategy can opt into exactly the checks it needs.
#
# Gates are stacked through the MRO, so every gate must end by delegating to
# super().eligible(). A gate that returns on its own cuts off every check
# behind it, including the full hard-rule gate on IScheduleStrategy.


class UnavailabilityGate(IScheduleStrategy):
    """Rejects a slot the employee has declared themselves unavailable for."""

    def eligible(
        self,
        employee_id: str,
        slot: Slot,
        spec: ScheduleSpec,
        taken_days: dict[str, set[date]],
        shift_history: dict[str, dict[date, str]],
        max_consecutive_days: int | None,
        forbidden_transitions: frozenset[tuple[str, str]],
    ) -> bool:
        if not spec.is_available(employee_id, slot.day):
            return False
        return super().eligible(
            employee_id,
            slot,
            spec,
            taken_days,
            shift_history,
            max_consecutive_days,
            forbidden_transitions,
        )


class RestGate(IScheduleStrategy):
    """Rejects a slot that would break the rest rule (R004)."""

    def eligible(
        self,
        employee_id: str,
        slot: Slot,
        spec: ScheduleSpec,
        taken_days: dict[str, set[date]],
        shift_history: dict[str, dict[date, str]],
        max_consecutive_days: int | None,
        forbidden_transitions: frozenset[tuple[str, str]],
    ) -> bool:
        previous_day = slot.day - timedelta(days=1)
        previous_shift = shift_history.get(employee_id, {}).get(previous_day)
        if (previous_shift, slot.shift_type_id) in forbidden_transitions:
            return False
        return super().eligible(
            employee_id,
            slot,
            spec,
            taken_days,
            shift_history,
            max_consecutive_days,
            forbidden_transitions,
        )


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
