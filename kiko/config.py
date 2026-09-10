"""Configuration for Kiko. Everything is overridable through environment variables."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

# Channel identifiers. Every message Kiko sends or receives lives in exactly one of these.
CH_GEORGE = "george_dm"        # one-on-one with George
CH_GROUP = "family_group"      # George, the parents, and Kiko
CH_PARENTS = "parents_private"  # parents only, George never sees this
CH_MARKOS = "markos_dm"        # Kiko's requests to the Qustodio admin

ALL_CHANNELS = (CH_GEORGE, CH_GROUP, CH_PARENTS, CH_MARKOS)


def _env_list(name: str, default: str) -> list[str]:
    return [x.strip() for x in os.environ.get(name, default).split(",") if x.strip()]


@dataclass
class KikoConfig:
    """Who is who, which models to use, and where state is kept."""

    # People
    kid_name: str = field(default_factory=lambda: os.environ.get("KIKO_KID_NAME", "George"))
    kid_age: int = field(default_factory=lambda: int(os.environ.get("KIKO_KID_AGE", "12")))
    kiko_age: int = field(default_factory=lambda: int(os.environ.get("KIKO_AGE", "14")))
    parent_names: list[str] = field(default_factory=lambda: _env_list("KIKO_PARENT_NAMES", "Markos,Tina"))
    qustodio_admin: str = field(default_factory=lambda: os.environ.get("KIKO_QUSTODIO_ADMIN", "Markos"))

    # Models. Sonnet is the everyday, uncapped model; the top tier is capped per day.
    everyday_model: str = field(default_factory=lambda: os.environ.get("KIKO_EVERYDAY_MODEL", "claude-sonnet-5"))
    top_model: str = field(default_factory=lambda: os.environ.get("KIKO_TOP_MODEL", "claude-opus-5"))
    top_calls_per_day: int = field(default_factory=lambda: int(os.environ.get("KIKO_TOP_CALLS_PER_DAY", "30")))
    # Server-side refusal fallbacks (Opus 5 / Fable 5.1). Set KIKO_FALLBACKS=0 to disable.
    use_fallbacks: bool = field(default_factory=lambda: os.environ.get("KIKO_FALLBACKS", "1") != "0")
    max_tokens: int = 16000
    max_iterations: int = 12

    # Schedule
    checkin_time: str = field(default_factory=lambda: os.environ.get("KIKO_CHECKIN_TIME", "16:30"))

    # Storage
    data_dir: Path = field(default_factory=lambda: Path(os.environ.get("KIKO_DATA_DIR", "~/.kiko")).expanduser())

    # How much recent chat Kiko sees from each channel when composing a reply.
    context_messages: int = 40

    @property
    def group_members(self) -> list[str]:
        return [self.kid_name, *self.parent_names, "Kiko"]

    def ensure_dirs(self) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)
