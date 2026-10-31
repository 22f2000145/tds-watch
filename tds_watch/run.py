"""Collect the current public state, diff it against the last run, and notify."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from . import notify, parse, sources, state
from .config import Config

_MONTHS = {
    name: index
    for index, name in enumerate(
        ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"], start=1
    )
}


def _date_key(text: str) -> tuple[int, int, int]:
    """"Sun 08 Nov" -> (2000, 11, 8) so rows sort by calendar order, not alphabetically.

    The term README omits the year for in-term dates; rows that spell it out
    (e.g. "Sun 10 Jan 2027") keep it, so the end term does not jump to the top.
    """
    match = re.search(r"(\d{1,2})\s+([A-Za-z]{3})(?:\s+(\d{4}))?", text or "")
    if not match:
        return (9999, 13, 32)
    year = int(match.group(3)) if match.group(3) else 2000
    return (year, _MONTHS.get(match.group(2).title(), 13), int(match.group(1)))


@dataclass
class Result:
    term: str
    seeded: bool
    changes: int
    message: str | None
    sent: bool
    schedule_rows: int
    released_assessments: int


def _diff_schedule(
    old: dict[str, dict[str, str]], new: dict[str, dict[str, str]]
) -> list[dict[str, Any]]:
    changes: list[dict[str, Any]] = []
    for key in sorted(set(old) | set(new)):
        before, after = old.get(key), new.get(key)
        if before is None:
            changes.append({"key": key, "type": "added", "fields": after})
            continue
        if after is None:
            changes.append({"key": key, "type": "removed", "fields": before})
            continue
        for field in ("content", "weight", "release", "due"):
            if before.get(field) != after.get(field):
                changes.append(
                    {
                        "key": key,
                        "type": "changed",
                        "field": field,
                        "old": before.get(field),
                        "new": after.get(field),
                    }
                )
    return changes


def _diff_exams(
    old: dict[str, dict[str, str] | None], new: dict[str, dict[str, str] | None]
) -> list[dict[str, Any]]:
    changes: list[dict[str, Any]] = []
    for exam_id in sorted(set(old) | set(new)):
        before, after = old.get(exam_id), new.get(exam_id)
        if before is None and after is not None:
            changes.append({"id": exam_id, "type": "released", "title": after.get("title", "")})
            continue
        if before is not None and after is None:
            changes.append({"id": exam_id, "type": "unreleased"})
            continue
        if before is None or after is None:
            continue
        for field in ("start", "end", "title"):
            if before.get(field) != after.get(field):
                changes.append(
                    {
                        "id": exam_id,
                        "type": "changed",
                        "field": field,
                        "old": before.get(field),
                        "new": after.get(field),
                    }
                )
        if before.get("instructions_hash") != after.get("instructions_hash"):
            changes.append({"id": exam_id, "type": "changed", "field": "instructions"})
    return changes


def _diff_commits(last_sha: str | None, commits: list[sources.Commit]) -> list[sources.Commit]:
    if not last_sha:
        return []
    for index, commit in enumerate(commits):
        if commit.sha == last_sha:
            return commits[:index]
    # The old commit fell off the feed (more than 20 commits since last run).
    return commits[:5]


def _labels(schedule: dict[str, dict[str, str]]) -> dict[str, str]:
    labels: dict[str, str] = {}
    for key in schedule:
        exam_id = parse.exam_id_for(key)
        if exam_id:
            labels[exam_id] = "End term" if key.upper() == "F" else key
    return labels


def collect(cfg: Config) -> tuple[str, dict[str, dict[str, str]], dict[str, Any], list[sources.Commit]]:
    term = cfg.term or sources.current_term(cfg.repo)
    markdown = sources.readme(cfg.repo, term)
    schedule = parse.parse_schedule(markdown)
    exams: dict[str, dict[str, str] | None] = {}
    for exam_id in parse.exam_ids(schedule):
        raw = sources.exam_info(term, exam_id)
        exams[exam_id] = parse.parse_exam(raw) if raw else None
    return term, schedule, exams, sources.commits(cfg.repo)


def status_report(cfg: Config) -> str:
    """Readable snapshot of what the parser sees right now. No notifications, no writes."""
    term, schedule, exams, commits = collect(cfg)
    live = sum(1 for value in exams.values() if value)
    latest = commits[0].sha[:7] if commits else "unknown"
    lines = [
        f"term {term}  ·  {cfg.repo}  ·  latest commit {latest}",
        f"{len(schedule)} schedule rows  ·  {live} of {len(exams)} assessment pages live",
        "",
        f"{'key':<6} {'release':<22} {'due':<24} page",
        f"{'-' * 6} {'-' * 22} {'-' * 24} {'-' * 6}",
    ]
    for key in sorted(schedule, key=lambda k: (_date_key(schedule[k]["due"]), k)):
        row = schedule[key]
        exam_id = parse.exam_id_for(key)
        page = "live" if exam_id and exams.get(exam_id) else "—"
        lines.append(f"{key:<6} {row['release'] or '—':<22} {row['due'] or '—':<24} {page}")
    return "\n".join(lines)


def run(cfg: Config, force_seed: bool = False) -> Result:
    term, schedule, exams, commits = collect(cfg)
    previous = state.load(cfg.state_path)
    first_run = previous is None
    seeded = first_run or force_seed or previous.get("term") != term

    labels = _labels(schedule)
    released = sum(1 for value in exams.values() if value)
    new_sha = commits[0].sha if commits else (previous or {}).get("last_commit")

    if seeded:
        schedule_changes: list[dict[str, Any]] = []
        exam_changes: list[dict[str, Any]] = []
        shown_commits: list[sources.Commit] = []
        message = None
        if not force_seed:
            message = notify.build_message(
                term=term,
                schedule_changes=[],
                exam_changes=[],
                commits=[],
                labels=labels,
                repo=cfg.repo,
                seeded=True,
                seeded_counts=(len(schedule), released),
            )
        changes = 0
    else:
        schedule_changes = _diff_schedule(previous.get("schedule") or {}, schedule)
        exam_changes = _diff_exams(previous.get("exams") or {}, exams)
        new_commits = _diff_commits(previous.get("last_commit"), commits)
        # Commits are context, not a trigger: blog/image commits should not page you.
        shown_commits = new_commits if (schedule_changes or exam_changes) else []
        changes = len(schedule_changes) + len(exam_changes)
        message = notify.build_message(
            term=term,
            schedule_changes=schedule_changes,
            exam_changes=exam_changes,
            commits=shown_commits,
            labels=labels,
            repo=cfg.repo,
        )

    # Only persist when the watched data actually changed. Writing on every run
    # would make the Actions workflow commit a new state.json every hour.
    if not cfg.dry_run and (seeded or schedule_changes or exam_changes):
        state.save(
            cfg.state_path,
            {
                "term": term,
                "last_commit": new_sha,
                "schedule": schedule,
                "exams": exams,
                "updated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            },
        )

    sent = False
    if message:
        if cfg.dry_run:
            print(message)
        else:
            token, chat_id = cfg.require_telegram()
            notify.send(token, chat_id, message)
            sent = True

    return Result(
        term=term,
        seeded=seeded,
        changes=changes,
        message=message,
        sent=sent,
        schedule_rows=len(schedule),
        released_assessments=released,
    )
