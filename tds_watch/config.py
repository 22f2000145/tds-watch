"""Runtime configuration, read from environment variables."""

from __future__ import annotations

import os
from dataclasses import dataclass

DEFAULT_REPO = "sanand0/tools-in-data-science-public"


def _load_dotenv(path: str = ".env") -> None:
    """Minimal .env reader so local runs need no exports. Real env wins."""
    try:
        with open(path, encoding="utf-8") as handle:
            lines = handle.readlines()
    except FileNotFoundError:
        return
    for line in lines:
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        if key.startswith("export "):
            key = key[len("export ") :].strip()
        os.environ.setdefault(key, value.strip().strip('"').strip("'"))


def _flag(name: str) -> bool:
    return os.getenv(name, "").strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Config:
    repo: str = DEFAULT_REPO
    term: str | None = None
    state_path: str = "state.json"
    token: str | None = None
    chat_id: str | None = None
    dry_run: bool = False

    @classmethod
    def from_env(cls) -> "Config":
        _load_dotenv()
        return cls(
            repo=os.getenv("TDS_REPO", DEFAULT_REPO).strip() or DEFAULT_REPO,
            term=(os.getenv("TDS_TERM", "").strip() or None),
            state_path=os.getenv("STATE_PATH", "state.json").strip() or "state.json",
            token=(os.getenv("TELEGRAM_BOT_TOKEN", "").strip() or None),
            chat_id=(os.getenv("TELEGRAM_CHAT_ID", "").strip() or None),
            dry_run=_flag("DRY_RUN"),
        )

    def require_telegram(self) -> tuple[str, str]:
        if not self.token or not self.chat_id:
            raise RuntimeError(
                "TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID must be set "
                "(use --dry-run to preview without them)."
            )
        return self.token, self.chat_id
