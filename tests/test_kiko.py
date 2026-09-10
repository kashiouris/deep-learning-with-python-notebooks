"""Offline tests for Kiko. The Claude client is faked; tools and state are real."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path

import pytest

from kiko.agent import KikoAgent
from kiko.budget import ModelRouter, TopTierBudget
from kiko.channels import ConsoleTransport
from kiko.checkin import afternoon_opener, defend_in_group, end_of_session
from kiko.config import CH_GEORGE, CH_GROUP, CH_MARKOS, CH_PARENTS, KikoConfig
from kiko.homework import STATUS_DONE, STATUS_MISSING, HomeworkStore
from kiko.persona import system_prompt

TODAY = date(2026, 9, 10)


# A minimal stand-in for the SDK's tool runner ------------------------------------
@dataclass
class Block:
    type: str
    text: str = ""
    name: str = ""
    input: dict = field(default_factory=dict)
    id: str = "tu_1"


@dataclass
class Msg:
    content: list
    stop_reason: str = "end_turn"


class FakeRunner:
    """Executes a scripted list of (tool_name, kwargs) then ends with `final_text`."""

    def __init__(self, tools, script, final_text):
        self.tools = {t.name: t for t in tools}
        self.script = script
        self.final_text = final_text
        self.results = []

    def __iter__(self):
        for name, kwargs in self.script:
            if name not in self.tools:  # the real model cannot call a tool the channel does not expose
                continue
            self.results.append(self.tools[name].call(kwargs))
            yield Msg([Block("tool_use", name=name, input=kwargs)], stop_reason="tool_use")
        yield Msg([Block("text", text=self.final_text)])


class FakeClient:
    def __init__(self):
        self.calls = []
        self.script = []
        self.final_text = "ok"

    class _Beta:
        def __init__(self, outer):
            self.messages = self
            self.outer = outer

        def tool_runner(self, **kwargs):
            self.outer.calls.append(kwargs)
            return FakeRunner(kwargs["tools"], self.outer.script, self.outer.final_text)

    @property
    def beta(self):
        return FakeClient._Beta(self)


@pytest.fixture
def agent(tmp_path: Path):
    cfg = KikoConfig(data_dir=tmp_path, top_calls_per_day=30)
    store = HomeworkStore(tmp_path / "homework.json")
    store.add("Math", "Worksheet 4.2", TODAY.isoformat())
    store.add("Science", "Lab write-up", (TODAY - timedelta(days=2)).isoformat())
    store.add("English", "Chapter 6 questions", (TODAY + timedelta(days=1)).isoformat())
    client = FakeClient()
    ag = KikoAgent(cfg, client=client, transport=ConsoleTransport(printer=lambda s: None), store=store, today=TODAY)
    ag.fake = client  # type: ignore[attr-defined]
    return ag


# Store ---------------------------------------------------------------------------
def test_store_marks_overdue_and_computes_streak(tmp_path):
    store = HomeworkStore(tmp_path / "hw.json")
    a = store.add("Math", "old", (TODAY - timedelta(days=1)).isoformat())
    store.refresh_overdue(TODAY)
    assert store.get(a.id).status == STATUS_MISSING
    assert store.record_day(TODAY).missing_count == 1
    assert store.streak() == 0
    store.set_status(a.id, STATUS_DONE, TODAY)
    store.record_day(TODAY)
    assert store.streak() == 1
    assert store.all_clear(TODAY)
    # Persisted and reloaded
    again = HomeworkStore(tmp_path / "hw.json")
    assert again.get(a.id).completed_on == TODAY.isoformat()


def test_csv_import_skips_duplicates(tmp_path):
    csv = tmp_path / "a.csv"
    csv.write_text("subject,title,due,notes\nMath,W1,2026-09-12,\nMath,W1,2026-09-12,\nArt,Poster,2026-09-14,colour\n")
    store = HomeworkStore(tmp_path / "hw.json")
    assert len(store.import_csv(csv)) == 2
    assert len(store.import_csv(csv)) == 0


# Budget --------------------------------------------------------------------------
def test_budget_caps_and_keeps_reserve(tmp_path):
    b = TopTierBudget(tmp_path / "b.json", per_day=3)
    # Group defense (priority 3) keeps a reserve of 4, so with only 3 left it is refused.
    assert not b.try_consume(3)
    assert b.used == 0
    assert b.try_consume(0) and b.try_consume(0) and b.try_consume(0)
    assert not b.try_consume(0)
    assert b.remaining == 0
    assert TopTierBudget(tmp_path / "b.json", per_day=3).used == 3


def test_router_falls_back_to_everyday_model(tmp_path):
    cfg = KikoConfig(data_dir=tmp_path, top_calls_per_day=1)
    r = ModelRouter(cfg, TopTierBudget(tmp_path / "b.json", 1))
    first = r.choose("safety_escalation")
    second = r.choose("safety_escalation")
    assert first.model == cfg.top_model and first.top_tier
    assert second.model == cfg.everyday_model and not second.top_tier
    assert r.choose("checkin_chat").model == cfg.everyday_model


# Persona -------------------------------------------------------------------------
def test_prompts_name_the_family_and_are_stable():
    cfg = KikoConfig(parent_names=["Markos", "Tina"], qustodio_admin="Markos")
    for ch in (CH_GEORGE, CH_GROUP, CH_PARENTS, CH_MARKOS):
        p = system_prompt(cfg, ch)
        assert "George" in p and "Tina" in p and "Markos" in p
        assert system_prompt(cfg, ch) == p
    assert "never lie" in system_prompt(cfg, CH_GEORGE)
    assert "advocate" in system_prompt(cfg, CH_GROUP)


# Agent flows ---------------------------------------------------------------------
def test_afternoon_opener_goes_to_george_on_everyday_model(agent):
    agent.fake.final_text = "yo George, how was school? math 4.2 is due tomorrow right?"
    turn = afternoon_opener(agent)
    assert turn.channel == CH_GEORGE
    assert turn.model.model == agent.cfg.everyday_model
    assert agent.log.recent(CH_GEORGE)[-1].sender == "Kiko"
    call = agent.fake.calls[0]
    assert call["thinking"] == {"type": "adaptive"}
    assert "fallbacks" not in call
    assert call["system"][0]["cache_control"] == {"type": "ephemeral"}


def test_mark_done_requires_evidence_and_updates_store(agent):
    ids = {a.subject: a.id for a in agent.store.assignments}
    agent.fake.script = [
        ("mark_assignment", {"assignment_id": ids["Math"], "status": "done"}),
        ("mark_assignment", {"assignment_id": ids["Math"], "status": "done", "evidence": "last question was 7/8 + 1/4"}),
    ]
    agent.fake.final_text = "nice, marked it"
    turn = agent.respond(CH_GEORGE, "George", "finished the math sheet")
    assert turn.tool_calls == ["mark_assignment", "mark_assignment"]
    assert agent.store.get(ids["Math"]).status == STATUS_DONE
    assert "last question" in agent.store.get(ids["Math"]).notes
    assert agent.log.recent(CH_GEORGE)[-2].sender == "George"


def test_markos_request_refused_while_work_is_open(agent):
    agent.fake.script = [("message_markos", {"text": "please unblock"})]
    agent.fake.final_text = "not yet"
    agent.respond(CH_GEORGE, "George", "can you get my games back")
    assert agent.log.recent(CH_MARKOS) == []


def test_end_of_session_reports_and_asks_markos_when_clear(agent):
    for a in agent.store.assignments:
        if a.due_date <= TODAY:
            agent.store.set_status(a.id, STATUS_DONE, TODAY)
    agent.fake.script = [("report_to_parents", {"report": "All done today. Streak 1."})]
    agent.fake.final_text = "sent"
    turn = end_of_session(agent)
    assert turn.channel == CH_PARENTS and turn.model.top_tier
    assert agent.log.recent(CH_PARENTS)[-1].text.startswith("All done")
    # Second initiate() targeted Markos; the fake replayed the same script, which
    # the Markos tool set does not contain, so check the call itself.
    assert agent.fake.calls[-1]["model"] == agent.cfg.top_model
    assert agent.fake.calls[-1]["fallbacks"] == "default"
    tool_names = {t.name for t in agent.fake.calls[-1]["tools"]}
    assert tool_names == {"list_assignments", "message_markos", "set_qustodio_state"}
    assert agent.store.ledger[-1].missing_count == 0


def test_group_defense_uses_top_tier_and_posts_in_group(agent):
    agent.fake.script = [("post_in_group", {"text": "he handed in math today, science is the only one left"})]
    agent.fake.final_text = ""
    turn = defend_in_group(agent, "Tina", "George never does anything")
    assert turn.model.top_tier
    msgs = agent.log.recent(CH_GROUP)
    assert [m.sender for m in msgs] == ["Tina", "Kiko"]
    assert "handed in" in msgs[-1].text


def test_tools_are_scoped_per_channel(agent):
    from kiko.tools import build_tools
    names = lambda ch: {t.name for t in build_tools(agent.rt, ch)}
    assert "post_in_group" not in names(CH_GEORGE)
    assert "mark_assignment" not in names(CH_GROUP)
    assert "message_markos" not in names(CH_PARENTS)
