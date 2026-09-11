"""Kiko: a homework aid agent for George.

Kiko is a 14-year-old-style companion built on the Claude API. Every afternoon
Kiko checks in one-on-one with George (12), keeps his assignment list honest,
reports privately to his parents, stands up for him in the family group chat,
and, when the work is actually done, asks Markos to lift the Qustodio block.
"""

from .agent import KikoAgent
from .config import KikoConfig
from .homework import HomeworkStore

__all__ = ["KikoAgent", "KikoConfig", "HomeworkStore"]
