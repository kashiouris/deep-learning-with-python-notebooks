"""Run the afternoon check-in every day at the configured time.

This is a plain loop so it works anywhere Python runs. For production use a
cron entry (see README) that calls `python -m kiko checkin` instead.
"""

from __future__ import annotations

import time
from datetime import datetime, timedelta

from .agent import KikoAgent
from .checkin import afternoon_opener


def next_run(now: datetime, hhmm: str) -> datetime:
    hour, minute = (int(x) for x in hhmm.split(":"))
    target = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if target <= now:
        target += timedelta(days=1)
    return target


def run_forever(agent: KikoAgent) -> None:
    while True:
        target = next_run(datetime.now(), agent.cfg.checkin_time)
        print(f"Next check-in at {target:%Y-%m-%d %H:%M}")
        time.sleep(max((target - datetime.now()).total_seconds(), 0))
        afternoon_opener(agent)


def run_imessage_loop(agent: KikoAgent, addresses, db_path, poll_seconds: float = 5.0) -> None:
    """Poll chat.db, answer new messages, and open the check-in once a day."""
    from .imessage import Cursor, handle_incoming, read_new_messages

    cursor = Cursor(agent.cfg.data_dir / "imessage_cursor.json")
    cursor.start_from_latest(db_path)
    hour, minute = (int(x) for x in agent.cfg.checkin_time.split(":"))
    now = datetime.now()
    # If we start more than an hour after today's check-in time, do not fire a late opener.
    last_checkin_day = now.date() if now > now.replace(hour=hour, minute=minute) + timedelta(hours=1) else None
    print(f"Kiko listening on iMessage; check-in daily at {agent.cfg.checkin_time}")
    while True:
        now = datetime.now()
        target_today = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
        if last_checkin_day != now.date() and now >= target_today:
            last_checkin_day = now.date()
            afternoon_opener(agent)
        batch = read_new_messages(db_path, cursor.rowid, addresses)
        if batch:
            handle_incoming(agent, batch)
            cursor.advance(batch[-1].rowid)
        time.sleep(poll_seconds)
