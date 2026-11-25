"""Google Chat card layouts: compact summaries, clear changes, and source links."""

from __future__ import annotations

import html
from datetime import datetime
from typing import Any

from .notify import IST, exam_url, format_timestamp

MAX_DETAIL_WIDGETS = 50  # Leave ample room below Chat's 100-widget limit.
AVATAR_URL = "https://developers.google.com/chat/images/chat-product-icon.png"
FIELD_LABELS = {
    "due": "Submission deadline",
    "release": "Release date",
    "weight": "Weight",
    "content": "Content",
}


def _text(value: Any, limit: int = 240) -> str:
    value = " ".join(str(value or "—").split())
    if len(value) > limit:
        value = value[: limit - 1] + "…"
    return html.escape(value, quote=False)


def _button(label: str, url: str) -> dict[str, Any]:
    return {"text": label, "onClick": {"openLink": {"url": url}}}


def _detail(
    label: str,
    text: str,
    *,
    icon: str,
    note: str = "",
    url: str | None = None,
    button_label: str = "Open assessment",
) -> dict[str, Any]:
    detail: dict[str, Any] = {
        "startIcon": {"knownIcon": icon, "altText": label},
        "topLabel": label,
        "text": text,
        "wrapText": True,
    }
    if note:
        detail["bottomLabel"] = note
    if url:
        detail["button"] = _button(button_label, url)
    return {"decoratedText": detail}


def _card(title: str, subtitle: str, sections: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "header": {
            "title": title,
            "subtitle": subtitle,
            "imageUrl": AVATAR_URL,
            "imageType": "CIRCLE",
            "imageAltText": "TDS shared course alerts",
        },
        "sections": sections,
    }


def build_card(
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
) -> dict[str, Any]:
    now = now or datetime.now(IST)
    subtitle = f"Term {term} · {now.strftime('%d %b %Y · %H:%M IST')}"
    sections: list[dict[str, Any]] = []
    remaining = MAX_DETAIL_WIDGETS
    omitted = 0

    def section(header: str, widgets: list[dict[str, Any]], *, collapsible: bool = False) -> None:
        nonlocal remaining, omitted
        visible = widgets[:remaining]
        omitted += len(widgets) - len(visible)
        remaining -= len(visible)
        if not visible:
            return
        content: dict[str, Any] = {"header": header, "widgets": visible}
        if collapsible:
            content.update(collapsible=True, uncollapsibleWidgetsCount=1)
        sections.append(content)

    if seeded:
        rows, exams = seeded_counts
        section(
            "✅ Baseline saved · Monitoring is ready",
            [
                _detail("Schedule rows watched", f"<b>{rows}</b>", icon="INVITE"),
                _detail("Assessments already released", f"<b>{exams}</b>", icon="DESCRIPTION"),
                {"textParagraph": {"text": "Your group will only hear from me when something changes."}},
            ],
        )
    else:
        total = len(schedule_changes) + len(exam_changes)
        sections.append(
            {
                "header": "At a glance",
                "widgets": [
                    {
                        "textParagraph": {
                            "text": f"<b>{total} course update{'s' if total != 1 else ''}</b><br>"
                            f"{len(schedule_changes)} schedule · {len(exam_changes)} assessment"
                        }
                    }
                ],
            }
        )

    deadlines = [c for c in exam_changes if c["type"] == "changed" and c["field"] in {"start", "end"}]
    widgets = []
    for change in deadlines:
        label = labels.get(change["id"], change["id"].upper())
        window = "Opens" if change["field"] == "start" else "Closes"
        before = _text(format_timestamp(change.get("old") or ""))
        after = _text(format_timestamp(change.get("new") or ""))
        widgets.append(
            _detail(
                f"{_text(label)} · {window}",
                f'<font color="#1a73e8"><b>{after} IST</b></font>',
                icon="CLOCK",
                note=f"Previously: {before} IST",
                url=exam_url(term, change["id"]),
            )
        )
    section("⏰ Exact deadline changes", widgets)

    widgets = []
    for change in schedule_changes:
        key = _text(change["key"])
        if change["type"] == "changed":
            field = FIELD_LABELS.get(change["field"], change["field"])
            widgets.append(
                _detail(
                    f"{key} · {_text(field)}",
                    f'<font color="#1a73e8"><b>{_text(change.get("new"))}</b></font>',
                    icon="INVITE",
                    note=f"Previously: {_text(change.get('old'))}",
                )
            )
        elif change["type"] == "added":
            due = change.get("fields", {}).get("due") or "No date yet"
            widgets.append(_detail(f"{key} · Added", f"<b>Due {_text(due)}</b>", icon="INVITE"))
        else:
            widgets.append(_detail(f"{key} · Removed", "Removed from the schedule", icon="INVITE"))
    section("📅 Schedule updates", widgets)

    widgets = []
    for change in (c for c in exam_changes if c["type"] == "released"):
        label = labels.get(change["id"], change["id"].upper())
        widgets.append(
            _detail(
                f"{_text(label)} · Now available",
                f"<b>{_text(change.get('title') or label)}</b>",
                icon="DESCRIPTION",
                note="Open the assessment for the latest instructions.",
                url=exam_url(term, change["id"]),
            )
        )
    section("🎉 New assessments", widgets)

    widgets = []
    for change in exam_changes:
        label = _text(labels.get(change["id"], change["id"].upper()))
        if change["type"] == "unreleased":
            widgets.append(
                _detail(label, '<font color="#b06000"><b>Assessment page withdrawn</b></font>', icon="DESCRIPTION")
            )
        elif change["type"] == "changed" and change["field"] == "title":
            widgets.append(
                _detail(
                    f"{label} · Title changed",
                    f"<b>{_text(change.get('new'))}</b>",
                    icon="DESCRIPTION",
                    note=f"Previously: {_text(change.get('old'))}",
                    url=exam_url(term, change["id"]),
                )
            )
        elif change["type"] == "changed" and change["field"] == "instructions":
            widgets.append(
                _detail(
                    label,
                    "<b>Instructions updated</b>",
                    icon="DESCRIPTION",
                    note="Review the assessment page before submitting.",
                    url=exam_url(term, change["id"]),
                    button_label="Read instructions",
                )
            )
    section("📝 Assessment updates", widgets)

    if commits:
        widgets = [
            _detail(_text(commit.author), _text(commit.title, 180), icon="DESCRIPTION")
            for commit in commits[:5]
        ]
        if len(commits) > 5:
            widgets.append({"textParagraph": {"text": f"…and {len(commits) - 5} more. Use View commits below."}})
        section("🔗 Change context", widgets, collapsible=True)

    if omitted:
        sections.append(
            {"widgets": [{"textParagraph": {"text": f"{omitted} more updates. See the source links below for details."}}]}
        )
    buttons = [_button("View schedule", f"https://github.com/{repo}/blob/main/{term}/README.md")]
    if commits:
        buttons.append(_button("View commits", f"https://github.com/{repo}/commits/main"))
    else:
        buttons.append(_button("View course", f"https://github.com/{repo}"))
    sections.append(
        {
            "widgets": [
                {"buttonList": {"buttons": buttons}},
                {"textParagraph": {"text": "<i>Public course updates only · All times in IST</i>"}},
            ]
        }
    )
    return _card("TDS · Deadline Watch", subtitle, sections)


def build_test_card(*, repo: str, now: datetime | None = None) -> dict[str, Any]:
    now = now or datetime.now(IST)
    sections = [
        {
            "header": "✅ Connection check",
            "widgets": [
                _detail(
                    "Shared study-group alerts",
                    "<b>Your Google Chat webhook is connected</b>",
                    icon="MULTIPLE_PEOPLE",
                    note="This is a setup test, not a new course update.",
                )
            ],
        },
        {
            "header": "What your group will receive",
            "widgets": [
                _detail("Deadlines & schedule", "New dates highlighted, previous dates kept for context", icon="CLOCK"),
                _detail("New assessments", "Release notifications with direct assessment links", icon="DESCRIPTION"),
                _detail("Course changes", "Instruction edits and relevant source commits", icon="INVITE"),
            ],
        },
        {
            "widgets": [
                {"buttonList": {"buttons": [_button("View course", f"https://github.com/{repo}")]}},
                {
                    "textParagraph": {
                        "text": "<i>Only public course updates are shared. This test does not change your saved baseline.</i>"
                    }
                },
            ]
        },
    ]
    return _card("TDS · Shared alerts connected", now.strftime("Test notification · %d %b %Y · %H:%M IST"), sections)
