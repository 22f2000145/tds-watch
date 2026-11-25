#!/usr/bin/env python3
"""Poll the public TDS dashboard and push changes to Telegram and/or Google Chat.

Usage:
    python monitor.py                 # check, save state, notify on changes
    python monitor.py --dry-run       # preview without sending or saving state
    python monitor.py --seed          # reset the baseline silently
    python monitor.py --test-notification  # test delivery without polling or saving
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import replace

from tds_watch import cards, notify
from tds_watch.config import Config
from tds_watch.run import run, status_report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Notify on changes to the public TDS course pages.")
    parser.add_argument("--dry-run", action="store_true", help="print the message instead of sending it")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--seed", action="store_true", help="overwrite the saved baseline without notifying")
    mode.add_argument("--status", action="store_true", help="show what is being watched, then exit")
    mode.add_argument(
        "--test-notification", action="store_true", help="test all configured destinations without changing state"
    )
    args = parser.parse_args(argv)

    cfg = Config.from_env()
    if args.dry_run:
        cfg = replace(cfg, dry_run=True)

    if args.status:
        try:
            print(status_report(cfg))
        except Exception as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 1
        return 0

    try:
        if args.test_notification:
            message = (
                "🔔 TDS monitor test\n\n"
                "✅ Notifications are working. Future public TDS schedule and assessment "
                "changes will be posted here."
            )
            if cfg.dry_run:
                print(message)
                print("Preview only; no notifications sent.")
            else:
                card = cards.build_test_card(repo=cfg.repo) if cfg.google_chat_webhook_url else None
                notify.send_notifications(cfg, message, card=card)
                print("Test notification sent to all configured destinations.")
            return 0
        result = run(cfg, force_seed=args.seed)
    except Exception as exc:  # surfaced in the GitHub Actions log
        print(f"error: {exc}", file=sys.stderr)
        return 1

    status = "baseline saved" if result.seeded else f"{result.changes} change(s)"
    delivered = "sent" if result.sent else ("preview only" if result.message else "nothing to report")
    print(
        f"term {result.term} · {result.schedule_rows} schedule rows · "
        f"{result.released_assessments} assessments live · {status} · {delivered}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
