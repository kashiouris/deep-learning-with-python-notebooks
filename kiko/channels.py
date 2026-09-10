"""Message transport and chat history.

Kiko talks in four places (see config.ALL_CHANNELS). A Transport delivers a
message to a channel; the ChatLog is the durable transcript Kiko reads back so
it "understands the group chat" across sessions. The default transport writes
to the log and prints, which is enough to drive Kiko from the CLI. Wire a real
chat bot by implementing Transport and passing it to KikoAgent.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Callable, Protocol

from .config import ALL_CHANNELS


@dataclass
class Message:
    channel: str
    sender: str
    text: str
    at: str = field(default_factory=lambda: datetime.now().isoformat(timespec="seconds"))

    def render(self) -> str:
        return f"[{self.at[:16]}] {self.sender}: {self.text}"


class ChatLog:
    """Append-only JSONL transcript per channel."""

    def __init__(self, directory: Path):
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)

    def _path(self, channel: str) -> Path:
        if channel not in ALL_CHANNELS:
            raise ValueError(f"unknown channel {channel!r}")
        return self.directory / f"{channel}.jsonl"

    def append(self, msg: Message) -> Message:
        with open(self._path(msg.channel), "a") as f:
            f.write(json.dumps(asdict(msg)) + "\n")
        return msg

    def recent(self, channel: str, n: int = 40) -> list[Message]:
        p = self._path(channel)
        if not p.exists():
            return []
        lines = p.read_text().splitlines()[-n:]
        return [Message(**json.loads(line)) for line in lines if line.strip()]

    def render(self, channel: str, n: int = 40) -> str:
        msgs = self.recent(channel, n)
        return "\n".join(m.render() for m in msgs) if msgs else "(no messages yet)"


class Transport(Protocol):
    def send(self, channel: str, text: str) -> None: ...


class ConsoleTransport:
    """Prints outgoing messages. Good enough for the CLI and for tests."""

    def __init__(self, printer: Callable[[str], None] = print):
        self.printer = printer
        self.sent: list[tuple[str, str]] = []

    def send(self, channel: str, text: str) -> None:
        self.sent.append((channel, text))
        self.printer(f"\n>>> Kiko -> {channel}\n{text}\n")


class Outbox:
    """Combines the transport with the log so every outgoing message is recorded once."""

    def __init__(self, log: ChatLog, transport: Transport):
        self.log = log
        self.transport = transport

    def send(self, channel: str, text: str, sender: str = "Kiko") -> Message:
        msg = self.log.append(Message(channel=channel, sender=sender, text=text))
        self.transport.send(channel, text)
        return msg

    def receive(self, channel: str, sender: str, text: str) -> Message:
        """Record an incoming human message without transmitting anything."""
        return self.log.append(Message(channel=channel, sender=sender, text=text))
