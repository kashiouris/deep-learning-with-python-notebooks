"""iMessage transport tests against a synthetic chat.db; no macOS needed."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from kiko.config import CH_GEORGE, CH_GROUP, CH_MARKOS, CH_PARENTS
from kiko.imessage import (
    Cursor,
    IMessageAddresses,
    IMessageTransport,
    apple_time,
    decode_attributed_body,
    read_new_messages,
)

GROUP = "iMessage;+;chat111"
PARENTS = "iMessage;+;chat222"
ADDR = IMessageAddresses(
    group=GROUP, george="+15550001", parents=PARENTS, markos="+15550002",
    contacts={"+15550001": "George", "+15550002": "Markos", "tina@icloud.com": "Tina"},
)


def make_db(path: Path) -> None:
    conn = sqlite3.connect(path)
    conn.executescript("""
        CREATE TABLE handle (ROWID INTEGER PRIMARY KEY, id TEXT);
        CREATE TABLE chat (ROWID INTEGER PRIMARY KEY, guid TEXT, display_name TEXT);
        CREATE TABLE chat_handle_join (chat_id INTEGER, handle_id INTEGER);
        CREATE TABLE message (ROWID INTEGER PRIMARY KEY, text TEXT, attributedBody BLOB, is_from_me INTEGER, date INTEGER, handle_id INTEGER);
        CREATE TABLE chat_message_join (chat_id INTEGER, message_id INTEGER);
        INSERT INTO handle VALUES (1, '+15550001'), (2, '+15550002'), (3, 'tina@icloud.com');
        INSERT INTO chat VALUES (10, 'iMessage;+;chat111', 'Family'), (11, 'iMessage;-;+15550001', NULL),
                               (12, 'iMessage;+;chat222', 'Parents'), (13, 'iMessage;-;+15550002', NULL);
        INSERT INTO chat_handle_join VALUES (10,1),(10,2),(10,3),(11,1),(12,2),(12,3),(13,2);
    """)
    rows = [
        # rowid, text, body, from_me, date(ns), handle, chat
        (1, "Kiko list the homework due for today with George", None, 0, 780000000000000000, 2, 10),
        (2, "George: nothing I can confirm is due today.", None, 1, 780000001000000000, None, 10),   # Kiko's own
        (3, "i finished the lab", None, 0, 780000002000000000, 1, 11),
        (4, None, b"junk NSString\x01\x94\x84\x01+\x0chello there!\x86", 0, 780000003000000000, 3, 12),
        (5, "ok lifted for tonight", None, 0, 780000004000000000, 2, 13),
        (6, "spam", None, 0, 780000005000000000, 2, 99),  # a chat we do not know
    ]
    for rowid, text, body, from_me, when, handle, chat in rows:
        conn.execute("INSERT INTO message VALUES (?,?,?,?,?,?)", (rowid, text, body, from_me, when, handle))
        conn.execute("INSERT INTO chat_message_join VALUES (?,?)", (chat, rowid))
    conn.commit()
    conn.close()


def test_routing_and_skipping(tmp_path):
    db = tmp_path / "chat.db"
    make_db(db)
    got = read_new_messages(db, 0, ADDR)
    assert [(m.rowid, m.channel, m.sender) for m in got] == [
        (1, CH_GROUP, "Markos"),
        (3, CH_GEORGE, "George"),
        (4, CH_PARENTS, "Tina"),
        (5, CH_MARKOS, "Markos"),
    ]
    assert got[2].text == "hello there!"
    assert read_new_messages(db, 5, ADDR) == []
    assert got[0].at.year == 2025


def test_cursor_starts_from_latest(tmp_path):
    db = tmp_path / "chat.db"
    make_db(db)
    c = Cursor(tmp_path / "cursor.json")
    c.start_from_latest(db)
    assert c.rowid == 6
    c.advance(4)
    assert Cursor(tmp_path / "cursor.json").rowid == 6


def test_transport_builds_applescript_for_group_and_handle():
    scripts = []
    t = IMessageTransport(ADDR, runner=scripts.append)
    t.send(CH_GROUP, 'yo "George"')
    t.send(CH_GEORGE, "nice one")
    assert 'send "yo \\"George\\"" to chat id "iMessage;+;chat111"' in scripts[0]
    assert 'to participant "+15550001" of svc' in scripts[1]


def test_decode_attributed_body_edge_cases():
    assert decode_attributed_body(None) == ""
    assert decode_attributed_body(b"no marker here") == ""
    assert apple_time(0).year == 2001


def test_addresses_from_env(monkeypatch):
    monkeypatch.setenv("KIKO_IMSG_GROUP", GROUP)
    monkeypatch.setenv("KIKO_IMSG_GEORGE", "+15550001")
    monkeypatch.setenv("KIKO_IMSG_CONTACTS", "+15550001=George, +15550002=Markos")
    a = IMessageAddresses.from_env()
    assert a.name_for("+15550002") == "Markos"
    assert a.channel_for(GROUP, "+15550002", True) == CH_GROUP
    assert a.channel_for("", "+15550001", False) == CH_GEORGE
    assert a.channel_for("", "+19999999", False) is None
