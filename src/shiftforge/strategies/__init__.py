"""Strategy plugins.

A strategy turns a spec plus a set of slots into a candidate roster. Adding a new
strategy means dropping a module in this package and registering it in
configs/strategy_catalog.json - core code is never edited.
"""

from .base import IScheduleStrategy, StrategyContext, load_strategy

__all__ = ["IScheduleStrategy", "StrategyContext", "load_strategy"]
