"""Turn the public TDS files into small, comparable dictionaries."""

from __future__ import annotations

import hashlib
import re

# --- markdown helpers -------------------------------------------------------

_INLINE_LINK = re.compile(r"\[([^\]]*)\]\([^)]*\)")
_REF_LINK = re.compile(r"\[([^\]]*)\]\[[^\]]*\]")


def strip_md(text: str) -> str:
    """'[**GA4**][GA4]' -> 'GA4'."""
    text = _INLINE_LINK.sub(r"\1", text)
    text = _REF_LINK.sub(r"\1", text)
    text = text.replace("**", "").replace("__", "").replace("`", "")
    return re.sub(r"\s+", " ", text).strip()


def _cells(row: str) -> list[str]:
    return [cell.strip() for cell in row.strip().strip("|").split("|")]


def parse_schedule(markdown: str) -> dict[str, dict[str, str]]:
    """Extract the assessment schedule table from a term README.

    Returns {assessment: {content, weight, release, due}} where assessment is
    GA0..GA8, P1, P2, ROE or F. Rows without any date (the "Best 7 of 9"
    summary row) are skipped.
    """
    lines = markdown.splitlines()
    start = next(
        (i for i, line in enumerate(lines) if line.strip().startswith("|") and "Submission Date" in line),
        None,
    )
    if start is None:
        raise ValueError("No schedule table (header containing 'Submission Date') found")

    headers = [strip_md(cell).lower() for cell in _cells(lines[start])]
    try:
        content_col = headers.index("content")
        assessment_col = headers.index("assessment")
        weight_col = headers.index("weight")
        release_col = headers.index("release date")
        due_col = headers.index("submission date")
    except ValueError as exc:
        raise ValueError(f"Unexpected schedule header: {headers}") from exc

    schedule: dict[str, dict[str, str]] = {}
    for line in lines[start + 2 :]:
        if not line.strip().startswith("|"):
            break
        cells = _cells(line)
        if len(cells) <= max(content_col, assessment_col, weight_col, release_col, due_col):
            continue
        content = strip_md(cells[content_col])
        assessment = strip_md(cells[assessment_col])
        release = strip_md(cells[release_col])
        due = strip_md(cells[due_col])
        if not release and not due:
            continue
        key = assessment or content
        schedule[key] = {
            "content": content,
            "weight": strip_md(cells[weight_col]),
            "release": release,
            "due": due,
        }
    if not schedule:
        raise ValueError("Schedule table parsed but contained no assessment rows")
    return schedule


# --- exam definitions -------------------------------------------------------

_FIELD = {
    "title": re.compile(r'\btitle:"([^"]*)"'),
    "start": re.compile(r'\bstart:"([^"]*)"'),
    "end": re.compile(r'\bend:"([^"]*)"'),
}
_INSTRUCTIONS = re.compile(r"instructions:`([\s\S]*?)`\}\s*;?\s*export")


def parse_exam(source: str) -> dict[str, str]:
    """Extract metadata from exam-tds-<term>-<id>.info.js."""
    out: dict[str, str] = {}
    for name, pattern in _FIELD.items():
        match = pattern.search(source)
        out[name] = match.group(1) if match else ""

    match = _INSTRUCTIONS.search(source)
    instructions = match.group(1) if match else ""
    # Collapse whitespace so reformatting does not look like a change, then
    # hash: the hash is all we need to detect "instructions were edited".
    normalised = re.sub(r"\s+", " ", instructions).strip()
    out["instructions_hash"] = hashlib.sha256(normalised.encode()).hexdigest()[:16]
    return out


# --- assessment ids ---------------------------------------------------------

BASE_EXAM_IDS = [f"ga{n}" for n in range(9)] + ["p1", "p2", "roe", "et"]


def exam_id_for(key: str) -> str | None:
    """Map a schedule key ('GA4', 'P1', 'ROE', 'F') to an exam-server id."""
    compact = re.sub(r"\s+", "", key).upper()
    match = re.fullmatch(r"GA(\d+)", compact)
    if match:
        return f"ga{int(match.group(1))}"
    if compact in {"P1", "P2"}:
        return compact.lower()
    if "ROE" in compact:
        return "roe"
    if compact in {"F", "ET"} or "ENDTERM" in compact or "END-TERM" in compact:
        return "et"
    return None


def exam_ids(schedule: dict[str, dict[str, str]]) -> list[str]:
    """Every exam id worth probing, derived from the schedule plus the defaults."""
    ids = set(BASE_EXAM_IDS)
    for key in schedule:
        exam_id = exam_id_for(key)
        if exam_id:
            ids.add(exam_id)
    return sorted(ids)
