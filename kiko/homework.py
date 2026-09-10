"""Assignment tracker and trust ledger, persisted as JSON.

The tracker is the single source of truth Kiko reasons from. It is deliberately
simple: a list of assignments with a status, plus a ledger of daily outcomes so
Kiko can talk about streaks and trends truthfully.
"""

from __future__ import annotations

import csv
import json
import uuid
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Iterable, Optional

STATUS_TODO = "todo"
STATUS_IN_PROGRESS = "in_progress"
STATUS_DONE = "done"
STATUS_MISSING = "missing"   # past due and not done
STATUSES = (STATUS_TODO, STATUS_IN_PROGRESS, STATUS_DONE, STATUS_MISSING)


@dataclass
class Assignment:
    id: str
    subject: str
    title: str
    due: str                      # ISO date
    status: str = STATUS_TODO
    notes: str = ""
    added_on: str = field(default_factory=lambda: date.today().isoformat())
    completed_on: Optional[str] = None
    source: str = "manual"

    @property
    def due_date(self) -> date:
        return date.fromisoformat(self.due)

    def is_overdue(self, today: date) -> bool:
        return self.status != STATUS_DONE and self.due_date < today

    def describe(self, today: date) -> str:
        delta = (self.due_date - today).days
        if delta < 0:
            when = f"{-delta} day(s) overdue"
        elif delta == 0:
            when = "due today"
        elif delta == 1:
            when = "due tomorrow"
        else:
            when = f"due in {delta} days ({self.due})"
        return f"[{self.id}] {self.subject}: {self.title} ({when}) status={self.status}"


@dataclass
class DayRecord:
    """One afternoon's outcome, used for streaks and trends."""

    day: str
    due_count: int
    done_count: int
    missing_count: int
    checked_in: bool = True

    @property
    def clean(self) -> bool:
        return self.missing_count == 0


class HomeworkStore:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.assignments: list[Assignment] = []
        self.ledger: list[DayRecord] = []
        self.qustodio_blocked: bool = True
        self._load()

    # Persistence -----------------------------------------------------------------
    def _load(self) -> None:
        if not self.path.exists():
            return
        raw = json.loads(self.path.read_text())
        self.assignments = [Assignment(**a) for a in raw.get("assignments", [])]
        self.ledger = [DayRecord(**d) for d in raw.get("ledger", [])]
        self.qustodio_blocked = bool(raw.get("qustodio_blocked", True))

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "assignments": [asdict(a) for a in self.assignments],
            "ledger": [asdict(d) for d in self.ledger],
            "qustodio_blocked": self.qustodio_blocked,
        }
        self.path.write_text(json.dumps(payload, indent=2, sort_keys=True))

    # Mutations -------------------------------------------------------------------
    def add(self, subject: str, title: str, due: str, notes: str = "", source: str = "manual") -> Assignment:
        date.fromisoformat(due)  # validate early
        a = Assignment(id=uuid.uuid4().hex[:6], subject=subject.strip(), title=title.strip(), due=due, notes=notes, source=source)
        self.assignments.append(a)
        self.save()
        return a

    def get(self, assignment_id: str) -> Assignment:
        for a in self.assignments:
            if a.id == assignment_id:
                return a
        raise KeyError(assignment_id)

    def set_status(self, assignment_id: str, status: str, today: Optional[date] = None) -> Assignment:
        if status not in STATUSES:
            raise ValueError(f"bad status {status!r}; expected one of {STATUSES}")
        a = self.get(assignment_id)
        a.status = status
        a.completed_on = (today or date.today()).isoformat() if status == STATUS_DONE else None
        self.save()
        return a

    def refresh_overdue(self, today: Optional[date] = None) -> None:
        """Flip anything past due and not done to 'missing'."""
        today = today or date.today()
        for a in self.assignments:
            if a.is_overdue(today) and a.status != STATUS_MISSING:
                a.status = STATUS_MISSING
        self.save()

    def import_csv(self, csv_path: Path, source: str = "csv") -> list[Assignment]:
        """Columns: subject,title,due[,notes]. Skips rows that already exist."""
        added = []
        existing = {(a.subject.lower(), a.title.lower(), a.due) for a in self.assignments}
        with open(csv_path, newline="") as f:
            for row in csv.DictReader(f):
                key = (row["subject"].strip().lower(), row["title"].strip().lower(), row["due"].strip())
                if key in existing:
                    continue
                existing.add(key)
                added.append(self.add(row["subject"], row["title"], row["due"].strip(), row.get("notes", ""), source=source))
        return added

    # Queries ---------------------------------------------------------------------
    def open_items(self, today: Optional[date] = None, horizon_days: int = 7) -> list[Assignment]:
        today = today or date.today()
        cutoff = today + timedelta(days=horizon_days)
        items = [a for a in self.assignments if a.status != STATUS_DONE and a.due_date <= cutoff]
        return sorted(items, key=lambda a: (a.due, a.subject))

    def missing(self, today: Optional[date] = None) -> list[Assignment]:
        today = today or date.today()
        return [a for a in self.assignments if a.is_overdue(today)]

    def done_recently(self, today: Optional[date] = None, days: int = 7) -> list[Assignment]:
        today = today or date.today()
        since = (today - timedelta(days=days)).isoformat()
        return sorted(
            (a for a in self.assignments if a.status == STATUS_DONE and a.completed_on and a.completed_on >= since),
            key=lambda a: a.completed_on or "",
        )

    def all_clear(self, today: Optional[date] = None) -> bool:
        """True when nothing is overdue and nothing due today is still open."""
        today = today or date.today()
        return not any(a.status != STATUS_DONE and a.due_date <= today for a in self.assignments)

    # Ledger ----------------------------------------------------------------------
    def record_day(self, today: Optional[date] = None) -> DayRecord:
        today = today or date.today()
        due_today = [a for a in self.assignments if a.due_date <= today]
        rec = DayRecord(
            day=today.isoformat(),
            due_count=len(due_today),
            done_count=sum(a.status == STATUS_DONE for a in due_today),
            missing_count=sum(a.status != STATUS_DONE for a in due_today),
        )
        self.ledger = [d for d in self.ledger if d.day != rec.day] + [rec]
        self.ledger.sort(key=lambda d: d.day)
        self.save()
        return rec

    def streak(self) -> int:
        """Consecutive most-recent check-in days with nothing missing."""
        n = 0
        for rec in reversed(self.ledger):
            if rec.clean:
                n += 1
            else:
                break
        return n

    def completion_rate(self, today: Optional[date] = None, days: int = 7) -> tuple[int, int]:
        """(done, due) for assignments due in the last `days` days."""
        today = today or date.today()
        since = today - timedelta(days=days)
        due = [a for a in self.assignments if since < a.due_date <= today]
        return sum(a.status == STATUS_DONE for a in due), len(due)

    # Rendering for prompts -------------------------------------------------------
    def snapshot(self, today: Optional[date] = None) -> str:
        today = today or date.today()
        self.refresh_overdue(today)
        lines = [f"Today: {today.isoformat()} ({today.strftime('%A')})", f"Qustodio: {'BLOCKED' if self.qustodio_blocked else 'unblocked'}"]
        open_items = self.open_items(today)
        lines.append(f"Open assignments ({len(open_items)}):")
        lines += [f"  {a.describe(today)}" + (f" notes: {a.notes}" if a.notes else "") for a in open_items] or ["  none"]
        done = self.done_recently(today)
        lines.append(f"Done in the last 7 days ({len(done)}):")
        lines += [f"  [{a.id}] {a.subject}: {a.title} (completed {a.completed_on})" for a in done] or ["  none"]
        d, n = self.completion_rate(today)
        pd, pn = self.completion_rate(today - timedelta(days=7))
        lines.append(f"Completion this week: {d}/{n}; last week: {pd}/{pn}; clean-day streak: {self.streak()}")
        return "\n".join(lines)


def seed_examples(store: HomeworkStore, today: Optional[date] = None) -> Iterable[Assignment]:
    """Demo data so the CLI has something to show on a fresh install."""
    today = today or date.today()
    return [
        store.add("Math", "Worksheet 4.2, fractions", (today + timedelta(days=1)).isoformat()),
        store.add("English", "Read chapter 6 and answer questions 1 to 5", today.isoformat()),
        store.add("Science", "Lab write-up on plant growth", (today - timedelta(days=2)).isoformat()),
    ]
