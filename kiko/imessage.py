"""iMessage transport for Kiko (macOS only).

Kiko needs its own Apple ID signed into Messages.app on a Mac that stays on.
Outgoing messages go through AppleScript; incoming ones are read from
~/Library/Messages/chat.db (grant the terminal Full Disk Access).

Chats are addressed by iMessage chat GUID for groups (for example
"iMessage;+;chat123456789012345678", found in chat.db's `chat.guid`) or by a
handle (phone number or email) for one-on-one chats.
"""

from __future__ import annotations

import json
import os
import sqlite3
import subprocess
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Iterable, Optional

from .config import CH_GEORGE, CH_GROUP, CH_MARKOS, CH_PARENTS

APPLE_EPOCH = datetime(2001, 1, 1)
DEFAULT_CHAT_DB = Path("~/Library/Messages/chat.db").expanduser()


@dataclass
class IMessageAddresses:
    """Where each Kiko channel lives on iMessage, plus a handle-to-name map."""

    group: str                      # chat GUID of the family group
    george: str                     # George's handle
    parents: str = ""               # chat GUID of the parents' chat (or a parent's handle)
    markos: str = ""                # the Qustodio admin's handle
    contacts: dict[str, str] = None  # handle -> display name

    def __post_init__(self):
        self.contacts = {k.strip(): v.strip() for k, v in (self.contacts or {}).items()}

    @classmethod
    def from_env(cls) -> "IMessageAddresses":
        contacts = {}
        for pair in os.environ.get("KIKO_IMSG_CONTACTS", "").split(","):
            if "=" in pair:
                handle, name = pair.split("=", 1)
                contacts[handle.strip()] = name.strip()
        return cls(
            group=os.environ.get("KIKO_IMSG_GROUP", ""),
            george=os.environ.get("KIKO_IMSG_GEORGE", ""),
            parents=os.environ.get("KIKO_IMSG_PARENTS", ""),
            markos=os.environ.get("KIKO_IMSG_MARKOS", ""),
            contacts=contacts,
        )

    def target_for(self, channel: str) -> str:
        return {CH_GROUP: self.group, CH_GEORGE: self.george, CH_PARENTS: self.parents, CH_MARKOS: self.markos}[channel]

    def channel_for(self, chat_guid: str, handle: str, is_group: bool) -> Optional[str]:
        """Map an incoming message to a Kiko channel, or None if it is not one of ours."""
        if chat_guid and chat_guid in (self.group, self.parents):
            return CH_GROUP if chat_guid == self.group else CH_PARENTS
        if not is_group and handle:
            if handle == self.george:
                return CH_GEORGE
            if handle and handle == self.markos:
                return CH_MARKOS
            if handle == self.parents:
                return CH_PARENTS
        return None

    def name_for(self, handle: str) -> str:
        return self.contacts.get(handle, handle)


# Sending -----------------------------------------------------------------------
def _applescript(script: str) -> None:
    subprocess.run(["osascript", "-e", script], check=True, capture_output=True, text=True)


def _quote(text: str) -> str:
    return '"' + text.replace("\\", "\\\\").replace('"', '\\"') + '"'


class IMessageTransport:
    """Kiko's Transport implementation for Messages.app."""

    def __init__(self, addresses: IMessageAddresses, runner=_applescript):
        self.addresses = addresses
        self.runner = runner

    def send(self, channel: str, text: str) -> None:
        target = self.addresses.target_for(channel)
        if not target:
            raise RuntimeError(f"no iMessage target configured for channel {channel}")
        if ";" in target:  # chat GUID
            script = f'tell application "Messages"\n  send {_quote(text)} to chat id {_quote(target)}\nend tell'
        else:  # handle
            script = (
                'tell application "Messages"\n'
                "  set svc to 1st account whose service type = iMessage\n"
                f"  send {_quote(text)} to participant {_quote(target)} of svc\n"
                "end tell"
            )
        self.runner(script)


# Receiving ---------------------------------------------------------------------
@dataclass
class Incoming:
    rowid: int
    channel: str
    sender: str
    text: str
    at: datetime


def decode_attributed_body(blob: Optional[bytes]) -> str:
    """Best-effort text extraction from the typedstream blob newer macOS uses
    when `message.text` is NULL."""
    if not blob:
        return ""
    try:
        rest = blob.split(b"NSString", 1)[1][5:]
        if rest[0] == 0x81:
            n = int.from_bytes(rest[1:3], "little")
            rest = rest[3:]
        else:
            n, rest = rest[0], rest[1:]
        return rest[:n].decode("utf-8", "ignore")
    except (IndexError, ValueError):
        return ""


def apple_time(value: int) -> datetime:
    seconds = value / 1e9 if value > 1e11 else value
    return APPLE_EPOCH + timedelta(seconds=seconds)


_QUERY = """
SELECT m.ROWID, m.text, m.attributedBody, m.is_from_me, m.date,
       h.id AS handle, c.guid AS chat_guid,
       (SELECT COUNT(*) FROM chat_handle_join chj WHERE chj.chat_id = c.ROWID) AS participants
FROM message m
JOIN chat_message_join cmj ON cmj.message_id = m.ROWID
JOIN chat c ON c.ROWID = cmj.chat_id
LEFT JOIN handle h ON h.ROWID = m.handle_id
WHERE m.ROWID > ?
ORDER BY m.ROWID
"""


def read_new_messages(db_path: Path, since_rowid: int, addresses: IMessageAddresses) -> list[Incoming]:
    """Return messages newer than `since_rowid` that belong to a Kiko channel.
    Kiko's own messages (is_from_me) are skipped."""
    uri = f"file:{db_path}?mode=ro"
    out: list[Incoming] = []
    with sqlite3.connect(uri, uri=True) as conn:
        for rowid, text, body, is_from_me, when, handle, chat_guid, participants in conn.execute(_QUERY, (since_rowid,)):
            if is_from_me:
                continue
            message = (text or "").strip() or decode_attributed_body(body).strip()
            if not message:
                continue
            channel = addresses.channel_for(chat_guid or "", handle or "", bool(participants and participants > 1))
            if channel is None:
                continue
            out.append(Incoming(rowid, channel, addresses.name_for(handle or ""), message, apple_time(when or 0)))
    return out


class Cursor:
    """Remembers the last chat.db row Kiko has handled."""

    def __init__(self, path: Path):
        self.path = Path(path)
        self.rowid = 0
        if self.path.exists():
            self.rowid = int(json.loads(self.path.read_text()).get("rowid", 0))

    def advance(self, rowid: int) -> None:
        if rowid > self.rowid:
            self.rowid = rowid
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(json.dumps({"rowid": self.rowid}))

    def start_from_latest(self, db_path: Path) -> None:
        """On first run, ignore history so Kiko does not answer old messages."""
        if self.rowid == 0 and db_path.exists():
            with sqlite3.connect(f"file:{db_path}?mode=ro", uri=True) as conn:
                self.advance(conn.execute("SELECT COALESCE(MAX(ROWID), 0) FROM message").fetchone()[0])


# Routing -----------------------------------------------------------------------
TASK_BY_CHANNEL = {
    CH_GEORGE: "checkin_chat",
    CH_GROUP: "group_defense",
    CH_PARENTS: "parent_report",
    CH_MARKOS: "markos_request",
}


def handle_incoming(agent, messages: Iterable[Incoming]) -> None:
    """Feed incoming iMessages to the agent, one reply per message."""
    for m in messages:
        agent.respond(m.channel, m.sender, m.text, task=TASK_BY_CHANNEL[m.channel])
