"""Format changes into a Telegram message and send it."""

from __future__ import annotations

import html
from datetime import datetime, timedelta, timezone
from typing import Any

import requests

IST = timezone(timedelta(hours=5, minutes=30))
MAX_LENGTH = 3900  # Telegram's hard limit is 4096; leave room for truncation.

FIELD_LABELS = {
    "due": "submission",
    "release": "release",
    "weight": "weight",
    "content": "content",
}


def _esc(value: Any) -> str:
    return html.escape(str(value), quote=False)


def _shorten(value: str, limit: int) -> str:
    value = " ".join(value.split())
    return value if len(value) <= limit else value[: limit - 1] + "…"


def _iso(value: str) -> str:
    """'2026-11-17T23:59:59+05:30' -> '17 Nov 2026 23:59 IST'."""
    if not value:
        return "—"
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return value
    if parsed.tzinfo is not None:
        parsed = parsed.astimezone(IST)
    return parsed.strftime("%d %b %Y %H:%M")


def exam_url(term: str, exam_id: str) -> str:
    return f"https://exam.sanand.workers.dev/tds-{term}-{exam_id}"


def build_message(
    *,
    term: str,
    schedule_changes: list[dict[str, Any]],
    exam_changes: list[dict[str, Any]],
    commits: list[Any],
    labels: dict[str, str],
    repo: str,
    seeded: bool = False,
    seeded_counts: tuple[int, int] = (0, 0),
    now: datetime | None = None,
) -> str | None:
    if not seeded and not (schedule_changes or exam_changes or commits):
        return None

    now = now or datetime.now(IST)
    lines = [f"🔔 <b>TDS {_esc(term)}</b> · {now.strftime('%d %b %Y %H:%M IST')}"]

    if seeded:
        rows, exams = seeded_counts
        lines += [
            "",
            f"✅ Baseline saved: watching <b>{rows}</b> schedule rows and <b>{exams}</b> released assessments.",
            "You will only hear from me when something changes.",
        ]

    if schedule_changes:
        lines += ["", "📅 <b>Schedule</b>"]
        for change in schedule_changes:
            key = _esc(change["key"])
            if change["type"] == "added":
                due = change.get("fields", {}).get("due") or "no date yet"
                lines.append(f"• <b>{key}</b> added · due {_esc(due)}")
            elif change["type"] == "removed":
                lines.append(f"• <b>{key}</b> removed from the schedule")
            else:
                field = FIELD_LABELS.get(change["field"], change["field"])
                lines.append(
                    f"• <b>{key}</b> {field}: {_esc(change.get('old') or '—')} → "
                    f"<b>{_esc(change.get('new') or '—')}</b>"
                )

    released = [c for c in exam_changes if c["type"] == "released"]
    if released:
        lines += ["", "🎉 <b>New assessment released</b>"]
        for change in released:
            label = labels.get(change["id"], change["id"].upper())
            title = change.get("title") or label
            lines.append(f"• <b>{_esc(label)}</b> — {_esc(title)}")
            lines.append(f"  {_esc(exam_url(term, change['id']))}")

    unreleased = [c for c in exam_changes if c["type"] == "unreleased"]
    if unreleased:
        lines += ["", "⚠️ <b>Assessment page withdrawn</b>"]
        for change in unreleased:
            lines.append(f"• {_esc(labels.get(change['id'], change['id'].upper()))}")

    deadlines = [c for c in exam_changes if c["type"] == "changed" and c["field"] in {"start", "end"}]
    if deadlines:
        lines += ["", "⏰ <b>Exact deadline changed</b>"]
        for change in deadlines:
            label = labels.get(change["id"], change["id"].upper())
            window = "opens" if change["field"] == "start" else "closes"
            lines.append(
                f"• <b>{_esc(label)}</b> {window}: {_esc(_iso(change.get('old', '')))} → "
                f"<b>{_esc(_iso(change.get('new', '')))}</b> IST"
            )

    retitled = [c for c in exam_changes if c["type"] == "changed" and c["field"] == "title"]
    if retitled:
        lines += ["", "✏️ <b>Title changed</b>"]
        for change in retitled:
            lines.append(f"• {_esc(change.get('old'))} → <b>{_esc(change.get('new'))}</b>")

    edited = [c for c in exam_changes if c["type"] == "changed" and c["field"] == "instructions"]
    if edited:
        lines += ["", "📝 <b>Instructions edited</b>"]
        for change in edited:
            label = labels.get(change["id"], change["id"].upper())
            lines.append(f"• <b>{_esc(label)}</b> — {_esc(exam_url(term, change['id']))}")

    if commits:
        lines += ["", f"🔗 <b>{len(commits)} new commit{'s' if len(commits) != 1 else ''}</b>"]
        for commit in commits[:5]:
            lines.append(f"• {_esc(_shorten(commit.title, 90))} — {_esc(commit.author)}")
        if len(commits) > 5:
            lines.append(f"• …and {len(commits) - 5} more")
        lines.append(f'<a href="https://github.com/{_esc(repo)}/commits/main">View commits</a>')

    message = "\n".join(lines)
    if len(message) > MAX_LENGTH:
        message = message[: MAX_LENGTH - 1] + "…"
    return message


def send(token: str, chat_id: str, text: str) -> None:
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    try:
        response = requests.post(
            url,
            json={
                "chat_id": chat_id,
                "text": text,
                "parse_mode": "HTML",
                "disable_web_page_preview": True,
            },
            timeout=25,
        )
    except requests.RequestException as exc:
        # Do not echo the URL: it contains the bot token.
        raise RuntimeError(f"Telegram request failed: {type(exc).__name__}") from exc
    if not response.ok:
        raise RuntimeError(f"Telegram rejected the message ({response.status_code}): {response.text[:300]}")
