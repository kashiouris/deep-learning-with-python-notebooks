"""Tools Kiko can call. Each is a closure over the shared runtime so the
@beta_tool signatures stay simple (strings and ints only)."""

from __future__ import annotations

from datetime import date
from typing import TYPE_CHECKING

from anthropic import beta_tool

from .config import CH_GEORGE, CH_GROUP, CH_MARKOS, CH_PARENTS
from .homework import STATUS_DONE, STATUS_IN_PROGRESS, STATUS_TODO

if TYPE_CHECKING:
    from .agent import KikoRuntime


def build_tools(rt: "KikoRuntime", channel: str) -> list:
    """Return the tool set for a channel. Reading tools are universal; the
    posting tools are limited so Kiko cannot, say, post to the group while
    writing the parents' report."""

    @beta_tool
    def list_assignments() -> str:
        """List every open assignment plus what was finished recently, the weekly
        completion rate, the clean-day streak, and whether Qustodio is blocked."""
        return rt.store.snapshot(rt.today)

    @beta_tool
    def add_assignment(subject: str, title: str, due: str, notes: str = "") -> str:
        """Add an assignment George mentioned that is not in the tracker yet.

        Args:
            subject: School subject, for example "Math".
            title: Short description of the work.
            due: Due date in ISO format, YYYY-MM-DD.
            notes: Anything useful, such as page numbers.
        """
        a = rt.store.add(subject, title, due, notes, source="kiko")
        return f"Added {a.describe(rt.today)}"

    @beta_tool
    def mark_assignment(assignment_id: str, status: str, evidence: str = "") -> str:
        """Update an assignment's status after George reports on it.

        Only mark "done" after asking George one concrete check question and
        getting a plausible answer; put that answer in `evidence`.

        Args:
            assignment_id: The id shown in brackets by list_assignments.
            status: One of "todo", "in_progress", "done".
            evidence: What George said that supports the status.
        """
        if status not in (STATUS_TODO, STATUS_IN_PROGRESS, STATUS_DONE):
            return f"Error: status must be todo, in_progress, or done, not {status!r}"
        if status == STATUS_DONE and not evidence.strip():
            return "Error: give the check question and George's answer as evidence before marking done."
        try:
            a = rt.store.set_status(assignment_id, status, rt.today)
        except KeyError:
            return f"Error: no assignment with id {assignment_id!r}"
        if evidence:
            a.notes = (a.notes + " | " if a.notes else "") + f"{rt.today.isoformat()}: {evidence.strip()}"
            rt.store.save()
        return f"Updated {a.describe(rt.today)}"

    @beta_tool
    def report_to_parents(report: str, urgent: bool = False) -> str:
        """Send a private report to the parents. George never sees this channel.

        Args:
            report: The full report text, plain sentences.
            urgent: True only for safety concerns; it is delivered with an alert prefix.
        """
        text = ("URGENT. " if urgent else "") + report.strip()
        rt.outbox.send(CH_PARENTS, text)
        return "Report delivered to the parents' private channel."

    @beta_tool
    def post_in_group(text: str) -> str:
        """Post a message in the family group chat, where George and the parents all read it.

        Args:
            text: What to say. Keep it short.
        """
        rt.outbox.send(CH_GROUP, text.strip())
        return "Posted to the family group."

    @beta_tool
    def message_markos(text: str) -> str:
        """Message the Qustodio admin to ask for the block to be lifted or loosened.

        This is refused by the system unless the tracker shows nothing missing and
        nothing due today still open, so check list_assignments first.

        Args:
            text: Your case, with the evidence from the tracker.
        """
        if not rt.store.all_clear(rt.today):
            missing = ", ".join(a.describe(rt.today) for a in rt.store.open_items(rt.today, horizon_days=0))
            return f"Refused: the tracker still shows open work due today or overdue: {missing}. Get that done first."
        rt.outbox.send(CH_MARKOS, text.strip())
        return f"Sent to {rt.cfg.qustodio_admin}. Only they can change Qustodio; tell George you asked, not that it is lifted."

    @beta_tool
    def set_qustodio_state(blocked: bool) -> str:
        """Record that the admin has changed the Qustodio block, so the tracker stays truthful.

        Args:
            blocked: True if George's games and apps are blocked, False if lifted.
        """
        rt.store.qustodio_blocked = blocked
        rt.store.save()
        return f"Recorded Qustodio as {'blocked' if blocked else 'unblocked'}."

    reading = [list_assignments]
    by_channel = {
        CH_GEORGE: [add_assignment, mark_assignment, report_to_parents, message_markos],
        CH_GROUP: [post_in_group, report_to_parents],
        CH_PARENTS: [report_to_parents, set_qustodio_state],
        CH_MARKOS: [message_markos, set_qustodio_state],
    }
    return reading + by_channel[channel]
