"""Collect the current public state, diff it against the last run, and notify."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from . import notify, parse, sources, state
from .config import Config


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
