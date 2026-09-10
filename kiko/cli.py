"""Command line for driving Kiko.

    python -m kiko checkin            Kiko opens today's one-on-one with George
    python -m kiko chat               interactive one-on-one, you type as George
    python -m kiko say "..."          one message from George, one reply
    python -m kiko group Tina "..."   a message in the family group; Kiko answers there
    python -m kiko parents Tina "..." a parent asks Kiko privately
    python -m kiko markos "..."       Markos replies to Kiko's request
    python -m kiko report             end the session: ledger, parents' report, Markos request if earned
    python -m kiko status             tracker snapshot and top-tier budget left
    python -m kiko add "Math" "Worksheet 4.2" 2026-09-11
    python -m kiko done <id>
    python -m kiko import file.csv
    python -m kiko qustodio blocked|unblocked
    python -m kiko seed               demo assignments on a fresh install
    python -m kiko serve              loop forever, check-in daily at KIKO_CHECKIN_TIME
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .agent import KikoAgent
from .checkin import afternoon_opener, defend_in_group, end_of_session, markos_replies, parents_ask
from .config import CH_GEORGE, KikoConfig
from .homework import STATUS_DONE, seed_examples


def _agent() -> KikoAgent:
    return KikoAgent(KikoConfig())


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="kiko", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("checkin")
    sub.add_parser("chat")
    sub.add_parser("say").add_argument("text")
    g = sub.add_parser("group"); g.add_argument("sender"); g.add_argument("text")
    p = sub.add_parser("parents"); p.add_argument("sender"); p.add_argument("text")
    sub.add_parser("markos").add_argument("text")
    sub.add_parser("report")
    sub.add_parser("status")
    a = sub.add_parser("add"); a.add_argument("subject"); a.add_argument("title"); a.add_argument("due"); a.add_argument("--notes", default="")
    sub.add_parser("done").add_argument("assignment_id")
    sub.add_parser("import").add_argument("csv_path")
    sub.add_parser("qustodio").add_argument("state", choices=["blocked", "unblocked"])
    sub.add_parser("seed")
    sub.add_parser("serve")
    args = ap.parse_args(argv)

    cfg = KikoConfig()
    cfg.ensure_dirs()

    # Commands that do not need the API client.
    if args.cmd in ("status", "add", "done", "import", "qustodio", "seed"):
        from .budget import default_budget
        from .homework import HomeworkStore
        store = HomeworkStore(cfg.data_dir / "homework.json")
        if args.cmd == "status":
            print(store.snapshot())
            b = default_budget(cfg)
            print(f"Top-tier calls left today: {b.remaining}/{b.per_day} ({cfg.top_model}); everyday model: {cfg.everyday_model}")
        elif args.cmd == "add":
            print(store.add(args.subject, args.title, args.due, args.notes).describe(store_today()))
        elif args.cmd == "done":
            print(store.set_status(args.assignment_id, STATUS_DONE).describe(store_today()))
        elif args.cmd == "import":
            added = store.import_csv(Path(args.csv_path))
            print(f"Imported {len(added)} assignment(s).")
        elif args.cmd == "qustodio":
            store.qustodio_blocked = args.state == "blocked"
            store.save()
            print(f"Qustodio recorded as {args.state}.")
        elif args.cmd == "seed":
            for x in seed_examples(store):
                print(x.describe(store_today()))
        return 0

    agent = _agent()
    if args.cmd == "checkin":
        afternoon_opener(agent)
    elif args.cmd == "say":
        agent.respond(CH_GEORGE, cfg.kid_name, args.text)
    elif args.cmd == "chat":
        afternoon_opener(agent)
        print(f"(type as {cfg.kid_name}; 'bye' ends the session and sends the parents' report)")
        while True:
            try:
                line = input(f"{cfg.kid_name}> ").strip()
            except (EOFError, KeyboardInterrupt):
                line = "bye"
            if line.lower() in ("bye", "quit", "exit"):
                break
            if line:
                agent.respond(CH_GEORGE, cfg.kid_name, line)
        end_of_session(agent)
    elif args.cmd == "group":
        defend_in_group(agent, args.sender, args.text)
    elif args.cmd == "parents":
        parents_ask(agent, args.sender, args.text)
    elif args.cmd == "markos":
        markos_replies(agent, args.text)
    elif args.cmd == "report":
        end_of_session(agent)
    elif args.cmd == "serve":
        from .scheduler import run_forever
        run_forever(agent)
    return 0


def store_today():
    from datetime import date
    return date.today()


if __name__ == "__main__":
    sys.exit(main())
