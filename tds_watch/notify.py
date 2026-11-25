"""Format changes and send them to Telegram and/or a Google Chat space."""

from __future__ import annotations

import html
import json
from datetime import datetime, timedelta, timezone
from html.parser import HTMLParser
from typing import Any

import requests

from .config import Config

IST = timezone(timedelta(hours=5, minutes=30))
MAX_LENGTH = 3900  # Telegram's hard limit is 4096; leave room for truncation.
GOOGLE_CHAT_MAX_BYTES = 32000

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


def format_timestamp(value: str) -> str:
    """Format an ISO timestamp in IST; callers append the timezone label."""
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
                f"• <b>{_esc(label)}</b> {window}: {_esc(format_timestamp(change.get('old', '')))} → "
                f"<b>{_esc(format_timestamp(change.get('new', '')))}</b> IST"
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


class _GoogleChatMessage(HTMLParser):
    """Translate the bold text and links produced by build_message to Chat markup."""

    def __init__(self, *, plain: bool = False) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.link: str | None = None
        self.plain = plain

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "b" and not self.plain:
            self.parts.append("*")
        elif tag == "a":
            self.link = dict(attrs).get("href")
            if self.link and not self.plain:
                self.parts.append(f"<{self.link}|")

    def handle_endtag(self, tag: str) -> None:
        if tag == "b" and not self.plain:
            self.parts.append("*")
        elif tag == "a" and self.link:
            self.parts.append(f" ({self.link})" if self.plain else ">")
            self.link = None

    def handle_data(self, data: str) -> None:
        self.parts.append(data)


def google_chat_text(text: str, *, plain: bool = False) -> str:
    """Google Chat uses *bold* and <url|label>, not Telegram's HTML markup."""
    message = _GoogleChatMessage(plain=plain)
    message.feed(text)
    message.close()
    return "".join(message.parts)


def google_chat_payload(text: str, *, card: dict[str, Any] | None = None) -> dict[str, Any]:
    """Use a rich card with a notification fallback, without duplicating its body."""
    payload: dict[str, Any]
    if card is not None:
        payload = {
            "fallbackText": google_chat_text(text, plain=True),
            "cardsV2": [{"cardId": "tds-update", "card": card}],
        }
        if len(json.dumps(payload).encode("utf-8")) <= GOOGLE_CHAT_MAX_BYTES:
            return payload

    # Very large change sets still deliver as text instead of exceeding Chat's limit.
    payload = {"text": google_chat_text(text)}
    while len(json.dumps(payload).encode("utf-8")) > GOOGLE_CHAT_MAX_BYTES:
        payload["text"] = payload["text"][: len(payload["text"]) // 2] + "…"
    return payload


def send_google_chat(webhook_url: str, text: str, *, card: dict[str, Any] | None = None) -> None:
    """Post the notification to the space that owns the incoming webhook."""
    try:
        response = requests.post(
            webhook_url,
            json=google_chat_payload(text, card=card),
            timeout=25,
            allow_redirects=False,
        )
    except requests.RequestException as exc:
        # The URL (and potentially the exception text) contains secret credentials.
        raise RuntimeError(f"Google Chat request failed: {type(exc).__name__}") from None
    if not 200 <= response.status_code < 300:
        # Do not log the response body, which could echo the secret webhook URL.
        raise RuntimeError(
            f"Google Chat rejected the message ({response.status_code}). "
            "Check the webhook URL and space permissions."
        )


def send_notifications(cfg: Config, text: str, *, card: dict[str, Any] | None = None) -> None:
    """Try every configured destination; report failures after attempting both."""
    cfg.require_notifications()
    failures: list[str] = []
    if cfg.token and cfg.chat_id:
        try:
            send(cfg.token, cfg.chat_id, text)
        except RuntimeError as exc:
            failures.append(str(exc))
    if cfg.google_chat_webhook_url:
        try:
            send_google_chat(cfg.google_chat_webhook_url, text, card=card)
        except RuntimeError as exc:
            failures.append(str(exc))
    if failures:
        raise RuntimeError("; ".join(failures))
