"""The afternoon routine and the other scripted moments."""

from __future__ import annotations

from .agent import KikoAgent, Turn
from .config import CH_GEORGE, CH_GROUP, CH_MARKOS, CH_PARENTS


def afternoon_opener(agent: KikoAgent) -> Turn:
    """Kiko starts the one-on-one. The conversation then continues through
    `agent.respond(CH_GEORGE, ...)` as George replies."""
    agent.store.refresh_overdue(agent.rt.today)
    return agent.initiate(
        CH_GEORGE,
        "It is afternoon check-in time. Open the conversation with George: say hi, "
        "ask about his day in one line, then get to what is due. Do not mark anything "
        "yet; he has not answered. Send just the opening message.",
        task="checkin_chat",
    )


def end_of_session(agent: KikoAgent) -> Turn:
    """Close out the day: ledger entry, private report, and the Markos request if earned."""
    agent.store.refresh_overdue(agent.rt.today)
    rec = agent.store.record_day(agent.rt.today)
    turn = agent.initiate(
        CH_PARENTS,
        "The check-in with George is over for today. Write and deliver the private report "
        "to the parents with the report_to_parents tool. Base every fact on the tracker and "
        f"the transcripts above. Ledger for today: due {rec.due_count}, done {rec.done_count}, "
        f"missing {rec.missing_count}.",
        task="parent_report",
    )
    if agent.store.all_clear(agent.rt.today) and agent.store.qustodio_blocked:
        request_unblock(agent)
    return turn


def request_unblock(agent: KikoAgent) -> Turn:
    return agent.initiate(
        CH_MARKOS,
        f"George's tracker is clear. Make the case to {agent.cfg.qustodio_admin} to lift the "
        "Qustodio block, using the message_markos tool. Evidence only, short, with a specific "
        "and reversible proposal.",
        task="markos_request",
    )


def defend_in_group(agent: KikoAgent, sender: str, text: str) -> Turn:
    """Someone posted in the family group; Kiko answers there with the record in hand."""
    return agent.respond(CH_GROUP, sender, text, task="group_defense")


def parents_ask(agent: KikoAgent, sender: str, text: str) -> Turn:
    return agent.respond(CH_PARENTS, sender, text, task="parent_report")


def markos_replies(agent: KikoAgent, text: str) -> Turn:
    return agent.respond(CH_MARKOS, agent.cfg.qustodio_admin, text, task="markos_request")
