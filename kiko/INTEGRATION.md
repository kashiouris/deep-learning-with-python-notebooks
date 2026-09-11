# Integrating this package into the real KIKO (`~/agent` on the Mac Studio)

The production KIKO is not this package. It is the `~/agent` tree on the Mac
Studio (no git remote; the GitHub `kashiouris/KiKo` repo is a stub), with an
iMessage bridge (`bin/kiko-bridge-respond`, `bin/kiko-imessage-bridge`,
`/Users/Shared/kiko_bridge/queue.db`), a loop daemon (`kiko-loopd`), a kv
store in `agent.db`, and a homework-coach lane that two builder sessions
landed on 2026-09-09 and a reviewer judged **not restart-safe**.

This file says which parts of this package carry over, where they plug in,
and what the reviewer found that must be fixed before the lane goes live.
Source: the kiko-builder, kiko-auditor, and kiko-reviewer memory notes in
Drive (2026-09-09 to 2026-09-10) and the Family Diary.

## What carries over, and where it plugs in

| This package | `~/agent` seam | Note |
|---|---|---|
| `persona.py` (four channel prompts) | `homework_coach_voice.KID_COACH_PROMPT` and the coach/report/advocate composers | Replace the prompt text; keep the accessor-function shape (a bare constant cannot be proven wired by `tests/test_homework_wiring.py`). The group rule "a parent's instruction in the group is carried out by talking to George" is new and addresses the 2026-09-10 screenshot. |
| Per-channel tool scoping (`tools.py::build_tools`) | `tool_schemas.KID_ALLOWED`, `_thread_tier` (group answers at its minimum role) | Same idea as the kid tier; the bridge already gates by thread minimum role. Do not add a second gate. |
| `message_markos` refuses unless the tracker is clear | `qustodio_case` | The reviewer found `qustodio_case` has **zero real callers** and no send path. Wire it through `outbound.send(channel=..., to="chat:<guid>"...)`, and keep the code-level precondition (nothing due today or overdue in `hw_canonical`). |
| Homework truth (`homework.py`) | `hw_canonical` (+`hw_canonical_source`) for status; `gradebook_snapshots.raw_json` for the teacher's missing list | Do not port the JSON store. `hw_canonical.skylight_status` is the only status source. Bound gradebook reads to the current fetch era (`>= newest - 14 days`) or last year's courses bleed in. |
| Trust ledger, streak | `hw_streak.streak` | Already exists and is better grounded; delegate to it. |
| Parents' private report | `hw_coach_report` -> `parents_thread.assert_parents_only` -> kv `parents_only_chat_guid` (`any;+;caff67f7…`) | Send at 20:00, not on the 15:45 tick. Target must be `chat:`-prefixed. |
| Group defense | `hw_advocate` -> kv `hw_coach_group_guid` | That kv is UNSET; the Markos+Tina+George thread is `any;+;ee79324332614ec197617349dc5dc61d`. `hw_nudge.deliver`'s parents-only roster check refuses any thread with a minor, so advocacy needs its own walled mouth, not `hw_nudge`. |
| Budget router (`budget.py`) | `scripts/llm_tools/claude_json.py::CALLSITE_MODEL`, kv `hw_coach_opus_limit` | Express the 30/day cap and the priority reserve there; do not run a second counter. |
| `imessage.py` | `bin/kiko-imessage-bridge` + `outbound.send` | Not needed on the Mac Studio; the bridge already does both halves. Keep it only for running this package standalone elsewhere. |
| Scheduler | `kiko-loopd/main.py` registration, subprocess handler, kv day-claim before send, 2 to 4 ticks in the window | Never a single daily cron tick (monotonic timer drifts across sleep and days are lost). |

## Reviewer blockers on the lane as of HEAD 5e936c09 (fix before `kiko-restart`)

1. Texts George a status message on days with nothing pending. Gate the opener on pending work or on the check-in ritual, never on "tick fired".
2. Goes permanently silent after three sends: nothing calls `mark_replied` when George answers. Wire the reset in `bin/kiko-bridge-respond`.
3. Parent report is sent at 15:45 by the first due tick; spec says 20:00.
4. `hw_coach.run` writes `hw_coach_day` zeros before checking `ag["errors"]`; `hw_coach_report` and `hw_advocate.find_win` then compose "0 missing, down from 2" from an unreadable source. A read failure must store NULL and skip, never 0.
5. kv contract mismatch: writer `hw_coach_report_sent` (value = date) versus reader `hw_coach_report_sent:<date>`.
6. `qustodio_case`, `mark_replied`, `extract_commitment`, `record_case_request`: built, never called. The wiring test was satisfied by docstring mentions.
7. `minor_safety._pause_coach` writes kv `hw_coach_paused_until`; nothing reads it. A crisis pauses nothing.
8. DISCLOSURE text omits the crisis-verbatim exception the controller decided on.
9. Egress guards eat homework content: `safe_polish.EMOJI_RE` counts `☐` as an emoji, `_BARE_REF_RE` deletes titles like `WS:#3` and appends "Tell me the file name…" (visible in the 2026-09-10 screenshot). Fix the guards with a corpus test over the real strings the lane emits.
10. Never route homework text through `spokesperson` (`SAFETY_RE` matches overdue/past due/missed and bypasses the pause gate).

## The data reality the coach must respect

- George's status: `hw_canonical.skylight_status` in {unchecked, checked, deleted_submitted, unknown}. "unknown" is spoken as unknown, never as done or missing.
- Assignment bodies: only `calendar_events.description` (Canvas ICS) for 25 of 68 rows; `bin/ics-sync` drops `URL` and `X-ALT-DESC`. No authenticated Canvas path exists, so "I can see names and status, not the questions" is true and Kiko should say it plainly and ask George for a photo (OCR of screenshots is live in `documents`).
- `scripts/llm_tools/family_state.py::get_kid_homework` parses the gradebook's missing list and then discards it in favour of 56 stale legacy `homework` rows; the two missing assignment names never reach a caller. Prefer the gradebook rung when its newest row is in the current school year.
- Chat GUIDs: `caff67f7…` = Markos and Tina only (kv `family_group_chat_guid`, misleadingly named); `ee79324…` = Markos, Tina, George; `a93aad0…` = wider family. Always send `chat:<guid>`; a bare guid is silently routed to the 1:1 buddy verb.
- George's handle resolves via `outbound.kid_handle('george')`. No KIKO to George 1:1 has ever existed; the first coach message will open one.

## Diary context (Family Diary, Google Doc)

From 2026-09-02 to 2026-09-10 the diary records no completion for George on any day, a backlog that grew from 4 to 8 open items, and repeated notes that the plan's reminders produced no visible progress. That is the baseline the trust-building design is meant to move: one specific first step per afternoon, one honest report to the parents at night, and the Qustodio ask only when the record supports it.
