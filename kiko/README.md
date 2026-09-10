# Kiko, George's homework aid

Kiko is a Claude-powered companion with the personality of a 14-year-old whose job is to make sure George (12) has no missing assignments, and to earn his trust while doing it.

Every afternoon Kiko:

1. opens a one-on-one chat with George, goes through what is due, and helps him start (never does the work for him);
2. updates the assignment tracker only on George's word plus one concrete check question;
3. sends a private, fully honest report to the parents (Markos and Tina); George never sees that channel;
4. stands up for George in the family group chat with the actual record, without denying missing work;
5. when the tracker is clear and Qustodio is still blocked, messages Markos with the evidence and a specific, reversible proposal to lift the block. Only Markos can change Qustodio; Kiko can only make the case.

## Channels

| Channel | Who reads it | What Kiko does there |
|---|---|---|
| `george_dm` | George only | afternoon check-in, homework help, marking work done |
| `family_group` | George, Markos, Tina | advocacy with context, redirecting criticism to specifics |
| `parents_private` | Markos, Tina | status, honest read, trend, one concrete ask |
| `markos_dm` | Markos | the Qustodio negotiation, evidence only |

Each channel has its own system prompt (`persona.py`) and its own tool set (`tools.py`): Kiko cannot post to the group while writing the parents' report, and the Markos tool is refused by code, not just by prompt, while anything due today or overdue is still open.

## Models and budget

* Everyday chat runs on Claude Sonnet 5 (`claude-sonnet-5`), uncapped.
* The top-tier model (`claude-opus-5` by default; set `KIKO_TOP_MODEL=claude-fable-5-1` if you want Fable) is limited to 30 calls per day (`KIKO_TOP_CALLS_PER_DAY`). Those calls go, in priority order, to: safety escalations, the Markos request, the parents' report, group-chat defense, and hard explanations George is stuck on. As the day's budget runs down, a reserve is kept for the higher-priority tasks; once it is gone everything falls back to Sonnet.
* Adaptive thinking is on for every call; effort is `medium` for chat and `high` for the rest. Server-side refusal fallbacks are enabled on top-tier calls (`KIKO_FALLBACKS=0` disables).
* The system prompt is a stable string with a cache breakpoint; volatile context (tracker snapshot, recent transcripts) goes in the user turn.

## Install and run

```bash
pip install -r kiko/requirements.txt
export ANTHROPIC_API_KEY=...        # or `ant auth login`
python -m kiko seed                 # demo assignments
python -m kiko status
python -m kiko chat                 # you type as George; 'bye' ends the session and sends the parents' report
python -m kiko group Tina "George never does anything"
python -m kiko markos "ok, lifted for tonight"
python -m kiko report
```

Daily schedule: `python -m kiko serve` loops forever and runs the check-in at `KIKO_CHECKIN_TIME` (default 16:30), or use cron:

```
30 16 * * 1-5  cd /path/to/repo && ANTHROPIC_API_KEY=... python -m kiko checkin
```

Tracker maintenance: `python -m kiko add "Math" "Worksheet 4.2" 2026-09-11`, `python -m kiko done <id>`, `python -m kiko import assignments.csv` (columns `subject,title,due[,notes]`), `python -m kiko qustodio blocked|unblocked`.

State lives in `KIKO_DATA_DIR` (default `~/.kiko`): `homework.json` (assignments, daily ledger, Qustodio flag), `budget.json`, and `chat/<channel>.jsonl` transcripts. Kiko reads the transcripts back on every turn, which is how it keeps up with the group chat between sessions.

## Wiring a real chat app

`channels.Transport` is one method, `send(channel, text)`. Implement it for WhatsApp, Telegram, iMessage, or whatever the family uses, pass it to `KikoAgent(transport=...)`, and feed incoming messages to `agent.respond(channel, sender, text)`. The CLI is that loop with the console as the transport.

## Configuration

| Variable | Default | Meaning |
|---|---|---|
| `KIKO_KID_NAME`, `KIKO_KID_AGE` | George, 12 | the kid |
| `KIKO_AGE` | 14 | Kiko's age |
| `KIKO_PARENT_NAMES` | `Markos,Tina` | who gets the private report |
| `KIKO_QUSTODIO_ADMIN` | Markos | who Kiko negotiates with |
| `KIKO_EVERYDAY_MODEL` | `claude-sonnet-5` | uncapped model |
| `KIKO_TOP_MODEL` | `claude-opus-5` | capped model |
| `KIKO_TOP_CALLS_PER_DAY` | 30 | daily cap |
| `KIKO_CHECKIN_TIME` | 16:30 | afternoon check-in |
| `KIKO_DATA_DIR` | `~/.kiko` | state directory |

## Tests

```bash
python -m pytest tests -q
```

The tests fake the Claude client and exercise the real tools and state: marking work done requires evidence, the Markos request is refused while work is open, the parents' report goes to the private channel on the top-tier model, the group defense posts in the group, and the daily budget caps and resets.
