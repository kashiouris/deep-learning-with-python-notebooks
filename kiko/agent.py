"""The Kiko agent: one Claude tool-runner call per turn, per channel."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Any, Callable, Optional

import anthropic

from .budget import ModelChoice, ModelRouter, default_budget
from .channels import ChatLog, ConsoleTransport, Outbox, Transport
from .config import CH_GEORGE, CH_GROUP, CH_MARKOS, CH_PARENTS, KikoConfig
from .homework import HomeworkStore
from .persona import system_prompt
from .tools import build_tools

FALLBACK_BETA = "server-side-fallback-2026-07-01"


@dataclass
class KikoRuntime:
    """Everything the tools need to act on the world."""

    cfg: KikoConfig
    store: HomeworkStore
    outbox: Outbox
    today: date = field(default_factory=date.today)


@dataclass
class Turn:
    channel: str
    model: ModelChoice
    text: str
    tool_calls: list[str]


class KikoAgent:
    def __init__(
        self,
        cfg: Optional[KikoConfig] = None,
        client: Optional[anthropic.Anthropic] = None,
        transport: Optional[Transport] = None,
        store: Optional[HomeworkStore] = None,
        today: Optional[date] = None,
    ):
        self.cfg = cfg or KikoConfig()
        self.cfg.ensure_dirs()
        self.client = client or anthropic.Anthropic()
        self.log = ChatLog(self.cfg.data_dir / "chat")
        self.outbox = Outbox(self.log, transport or ConsoleTransport())
        self.store = store or HomeworkStore(self.cfg.data_dir / "homework.json")
        self.router = ModelRouter(self.cfg, default_budget(self.cfg))
        self.rt = KikoRuntime(self.cfg, self.store, self.outbox, today or date.today())

    # Context assembly ------------------------------------------------------------
    def _context(self, channel: str) -> str:
        """Volatile context goes in the user turn so the system prompt stays cacheable."""
        n = self.cfg.context_messages
        parts = [
            "<tracker>", self.store.snapshot(self.rt.today), "</tracker>",
            f"<channel name='{CH_GEORGE}'>", self.log.render(CH_GEORGE, n), "</channel>",
            f"<channel name='{CH_GROUP}'>", self.log.render(CH_GROUP, n), "</channel>",
        ]
        if channel in (CH_PARENTS, CH_MARKOS):
            parts += [f"<channel name='{CH_PARENTS}'>", self.log.render(CH_PARENTS, 10), "</channel>",
                      f"<channel name='{CH_MARKOS}'>", self.log.render(CH_MARKOS, 10), "</channel>"]
        return "\n".join(parts)

    # Model call ------------------------------------------------------------------
    def _run(self, channel: str, prompt: str, choice: ModelChoice) -> tuple[str, list[str]]:
        kwargs: dict[str, Any] = dict(
            model=choice.model,
            max_tokens=self.cfg.max_tokens,
            max_iterations=self.cfg.max_iterations,
            system=[{"type": "text", "text": system_prompt(self.cfg, channel), "cache_control": {"type": "ephemeral"}}],
            thinking={"type": "adaptive"},
            output_config={"effort": choice.effort},
            tools=build_tools(self.rt, channel),
            messages=[{"role": "user", "content": prompt}],
        )
        if self.cfg.use_fallbacks and choice.top_tier:
            kwargs["betas"] = [FALLBACK_BETA]
            kwargs["fallbacks"] = "default"
        runner = self.client.beta.messages.tool_runner(**kwargs)
        tool_calls: list[str] = []
        final = None
        for message in runner:
            final = message
            tool_calls += [b.name for b in message.content if b.type == "tool_use"]
        if final is None:
            return "", tool_calls
        if final.stop_reason == "refusal":
            detail = getattr(final, "stop_details", None)
            return f"(Kiko could not answer: {getattr(detail, 'explanation', 'refused')})", tool_calls
        text = "\n".join(b.text for b in final.content if b.type == "text").strip()
        return text, tool_calls

    # Public turns ----------------------------------------------------------------
    def respond(self, channel: str, sender: str, text: str, task: str = "checkin_chat") -> Turn:
        """A human said `text` in `channel`; Kiko replies there."""
        self.outbox.receive(channel, sender, text)
        choice = self.router.choose(task)
        prompt = (
            f"{self._context(channel)}\n\n"
            f"{sender} just wrote in this channel:\n{text}\n\n"
            "Reply as Kiko. Use tools when you need to read or change anything. "
            "Your final message is what gets sent to this channel; write only that."
        )
        reply, calls = self._run(channel, prompt, choice)
        if reply:
            self.outbox.send(channel, reply)
        return Turn(channel, choice, reply, calls)

    def initiate(self, channel: str, instruction: str, task: str) -> Turn:
        """Kiko speaks first (check-in opener, report, defense, request)."""
        choice = self.router.choose(task)
        prompt = f"{self._context(channel)}\n\n{instruction}"
        reply, calls = self._run(channel, prompt, choice)
        # Reports and requests are delivered by the tools; anything left over in the
        # final text is Kiko's note back to the operator, not a channel message.
        if reply and channel in (CH_GEORGE, CH_GROUP) and "post_in_group" not in calls:
            self.outbox.send(channel, reply)
        return Turn(channel, choice, reply, calls)
