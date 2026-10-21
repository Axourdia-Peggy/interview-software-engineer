"""Coverage-first strategy.

Fills the hardest slots first. A slot is "hard" when few employees hold the role
it requires, so scheduling it early avoids painting the roster into a corner.
Used as the fallback when the preference-driven strategies leave seats unfilled.

Opts into the composable eligibility gates rather than the monolithic one.
"""

from __future__ import annotations

from datetime import date

from ..models import Roster, ScheduleSpec, Slot
from .base import RestGate, StrategyContext, UnavailabilityGate


def _role_scarcity(spec: ScheduleSpec, role: str) -> int:
    """How many employees can perform this role at all. Lower means scarcer."""
    return sum(1 for e in spec.employees if e.can_perform(role))


class CoverageFirstStrategy(UnavailabilityGate, RestGate):
    strategy_id = "coverage_first"

    def build(self, slots: list[Slot], context: StrategyContext) -> Roster:
        spec = context.spec
        roster = Roster(strategy_id=self.strategy_id)

        taken_days = self.ledger()
        shift_history: dict[str, dict[date, str]] = {}
        load: dict[str, int] = {e.employee_id: 0 for e in spec.employees}

        ordered = sorted(
            slots,
            key=lambda s: (
                _role_scarcity(spec, s.role),
                s.day,
                s.shift_type_id,
                s.seat,
            ),
        )

        max_run = context.max_consecutive_days()
        rest = context.forbidden_transitions()

        for slot in ordered:
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

            # Prefer specialists-last: someone who can cover many roles is kept
            # free for the slots nobody else can take.
            candidates.sort(
                key=lambda eid: (
                    load[eid],
                    len(spec.employee_by_id(eid).skills),
                    eid,
                )
            )
            chosen = candidates[0]

            self.commit(roster, slot, chosen, taken_days, shift_history)
            load[chosen] += 1

        return roster
