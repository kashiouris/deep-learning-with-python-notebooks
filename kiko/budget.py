"""Model routing under a daily cap on top-tier calls.

Sonnet is unlimited and handles the everyday back-and-forth. The top-tier model
(Opus 5 by default) is reserved for the moments that matter, up to a fixed
number of calls per day; after that everything falls back to Sonnet.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Optional

from .config import KikoConfig

# Tasks that deserve the top model, in priority order. When only a few calls are
# left for the day they go to the highest-priority tasks first.
TOP_TIER_TASKS: dict[str, int] = {
    "safety_escalation": 0,   # always top tier if any call is left
    "markos_request": 1,      # the negotiation to lift Qustodio
    "parent_report": 2,       # the private report
    "group_defense": 3,       # standing up for George in front of the family
    "hard_explanation": 4,    # George is stuck on something Sonnet fumbled
}
EVERYDAY_TASKS = {"checkin_chat", "small_talk", "status"}


@dataclass
class ModelChoice:
    model: str
    effort: str
    top_tier: bool
    reason: str


class TopTierBudget:
    """Persistent counter of top-tier calls used today."""

    def __init__(self, path: Path, per_day: int):
        self.path = Path(path)
        self.per_day = per_day
        self.day = date.today().isoformat()
        self.used = 0
        self._load()

    def _load(self) -> None:
        if self.path.exists():
            raw = json.loads(self.path.read_text())
            if raw.get("day") == self.day:
                self.used = int(raw.get("used", 0))

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps({"day": self.day, "used": self.used}))

    def _roll(self) -> None:
        today = date.today().isoformat()
        if today != self.day:
            self.day, self.used = today, 0
            self._save()

    @property
    def remaining(self) -> int:
        self._roll()
        return max(self.per_day - self.used, 0)

    def try_consume(self, priority: int) -> bool:
        """Reserve one call. Low-priority tasks are refused first as the budget runs down."""
        self._roll()
        remaining = self.per_day - self.used
        if remaining <= 0:
            return False
        # Keep a small reserve for the most important tasks late in the day.
        reserve = {0: 0, 1: 1, 2: 2, 3: 4, 4: 6}.get(priority, 6)
        if remaining <= reserve:
            return False
        self.used += 1
        self._save()
        return True


class ModelRouter:
    def __init__(self, cfg: KikoConfig, budget: TopTierBudget):
        self.cfg = cfg
        self.budget = budget

    def choose(self, task: str) -> ModelChoice:
        if task in TOP_TIER_TASKS:
            if self.budget.try_consume(TOP_TIER_TASKS[task]):
                return ModelChoice(self.cfg.top_model, "high", True, f"{task}: top tier ({self.budget.remaining} left today)")
            return ModelChoice(self.cfg.everyday_model, "high", False, f"{task}: top-tier budget exhausted, using everyday model")
        effort = "medium" if task in EVERYDAY_TASKS else "high"
        return ModelChoice(self.cfg.everyday_model, effort, False, f"{task}: everyday model")


def default_budget(cfg: KikoConfig, path: Optional[Path] = None) -> TopTierBudget:
    return TopTierBudget(path or cfg.data_dir / "budget.json", cfg.top_calls_per_day)
