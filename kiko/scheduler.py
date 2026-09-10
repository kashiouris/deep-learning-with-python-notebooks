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
