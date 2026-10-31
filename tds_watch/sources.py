"""HTTP access to the public TDS sources.

Everything here is public and unauthenticated:
  * the course repository's commit feed (Atom)
  * terms.yml and the per-term README.md
  * the exam server's per-assessment info.js files

No cookies, tokens, or logins are involved. Please keep polling gentle.
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass
from xml.etree import ElementTree

import requests

RAW = "https://raw.githubusercontent.com/{repo}/main"
EXAM_BASE = "https://exam.sanand.workers.dev"
TIMEOUT = 25
RETRIES = 3

SESSION = requests.Session()
SESSION.headers.update(
    {
        "User-Agent": "tds-watch/1.0 (personal deadline monitor; low volume)",
        "Accept": "*/*",
    }
)


class SourceError(RuntimeError):
    pass


def _get(url: str, *, allow_404: bool = False) -> str | None:
    last_error: Exception | None = None
    for attempt in range(RETRIES):
        try:
            response = SESSION.get(url, timeout=TIMEOUT)
            if response.status_code == 404 and allow_404:
                return None
            response.raise_for_status()
            return response.text
        except requests.RequestException as exc:  # noqa: PERF203 - retry loop
            last_error = exc
            if attempt < RETRIES - 1:
                time.sleep(2**attempt)
    raise SourceError(f"Could not fetch {url}: {last_error}")


def current_term(repo: str) -> str:
    """Read `current: 2026-09` from terms.yml without a YAML dependency."""
    text = _get(f"{RAW.format(repo=repo)}/terms.yml")
    assert text is not None
    match = re.search(r"^\s*current:\s*[\"']?([0-9]{4}-[0-9]{2})[\"']?", text, re.MULTILINE)
    if not match:
        raise SourceError("Could not find `current:` in terms.yml")
    return match.group(1)


def readme(repo: str, term: str) -> str:
    text = _get(f"{RAW.format(repo=repo)}/{term}/README.md")
    assert text is not None
    return text


@dataclass(frozen=True)
class Commit:
    sha: str
    title: str
    author: str
    updated: str
    url: str


ATOM = "{http://www.w3.org/2005/Atom}"


def commits(repo: str, limit: int = 20) -> list[Commit]:
    """Newest-first commits from the public Atom feed (no API key, no rate limit)."""
    text = _get(f"https://github.com/{repo}/commits/main.atom")
    assert text is not None
    try:
        root = ElementTree.fromstring(text)
    except ElementTree.ParseError as exc:
        raise SourceError(f"Unreadable commit feed: {exc}") from exc

    out: list[Commit] = []
    for entry in root.findall(f"{ATOM}entry")[:limit]:
        raw_id = entry.findtext(f"{ATOM}id", default="") or ""
        sha = re.search(r"[0-9a-f]{40}", raw_id)
        link = entry.find(f"{ATOM}link")
        out.append(
            Commit(
                sha=sha.group(0) if sha else raw_id,
                title=(entry.findtext(f"{ATOM}title", default="") or "").strip(),
                author=(entry.findtext(f"{ATOM}author/{ATOM}name", default="") or "").strip(),
                updated=(entry.findtext(f"{ATOM}updated", default="") or "").strip(),
                url=link.get("href", "") if link is not None else "",
            )
        )
    return out


def exam_info(term: str, exam_id: str) -> str | None:
    """The assessment definition, or None when it has not been released yet."""
    return _get(f"{EXAM_BASE}/exam-tds-{term}-{exam_id}.info.js", allow_404=True)
