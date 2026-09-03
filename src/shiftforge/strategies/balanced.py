"""Balanced rotation strategy.

Spreads work as evenly as possible: for each slot it picks the eligible employee
with the fewest assignments so far, breaking ties on who worked least recently.
"""

from __future__ import annotations

from datetime import date

from ..models import Roster, Slot
from .base import IScheduleStrategy, StrategyContext


class BalancedRotationStrategy(IScheduleStrategy):
    strategy_id = "balanced_rotation"

    def build(self, slots: list[Slot], context: StrategyContext) -> Roster:
        spec = context.spec
        roster = Roster(strategy_id=self.strategy_id)

        taken_days = self.ledger()
        shift_history: dict[str, dict[date, str]] = {}
        load: dict[str, int] = {e.employee_id: 0 for e in spec.employees}
        last_day: dict[str, date | None] = {e.employee_id: None for e in spec.employees}
        max_run = context.max_consecutive_days()

        for slot in sorted(slots, key=lambda s: (s.day, s.shift_type_id, s.role, s.seat)):
            candidates = [
                e.employee_id
                for e in spec.employees
                if self.eligible(e.employee_id, slot, spec, taken_days, shift_history, max_run)
            ]
            if not candidates:
                roster.unfilled.append(slot)
                continue

            candidates.sort(
                key=lambda eid: (
                    load[eid],
                    last_day[eid].toordinal() if last_day[eid] else 0,
                    eid,
                )
            )
            chosen = candidates[0]

            self.commit(roster, slot, chosen, taken_days, shift_history)
            load[chosen] += 1
            last_day[chosen] = slot.day

        return roster
