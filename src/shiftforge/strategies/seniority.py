"""Seniority-first strategy.

Offers each slot to the most senior eligible employee first. Under rising
pressure it progressively ignores seniority so that coverage still wins.
"""

from __future__ import annotations

from datetime import date

from ..models import Roster, Slot
from .base import IScheduleStrategy, StrategyContext


class SeniorityFirstStrategy(IScheduleStrategy):
    strategy_id = "seniority_first"

    def build(self, slots: list[Slot], context: StrategyContext) -> Roster:
        spec = context.spec
        roster = Roster(strategy_id=self.strategy_id)

        taken_days = self.ledger()
        shift_history: dict[str, dict[date, str]] = {}
        load: dict[str, int] = {e.employee_id: 0 for e in spec.employees}

        # The higher the pressure, the less seniority is allowed to matter.
        seniority_weight = max(0, 3 - context.pressure)
        max_run = context.max_consecutive_days()
        rest = context.forbidden_transitions()

        for slot in sorted(slots, key=lambda s: (s.day, s.shift_type_id, s.role, s.seat)):
            candidates = [
                e.employee_id
                for e in spec.employees
                if self.eligible(
                    e.employee_id, slot, spec, taken_days, shift_history, max_run, rest
                )
            ]
            if not candidates:
                roster.unfilled.append(slot)
                continue

            candidates.sort(
                key=lambda eid: (
                    -spec.employee_by_id(eid).seniority * seniority_weight,
                    load[eid],
                    eid,
                )
            )
            chosen = candidates[0]

            self.commit(roster, slot, chosen, taken_days, shift_history)
            load[chosen] += 1

        return roster
