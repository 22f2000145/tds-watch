"""Persistent monitor state (plain JSON, committed back to the repo)."""

from __future__ import annotations

import json
import os
import tempfile
from typing import Any

VERSION = 1


def load(path: str) -> dict[str, Any] | None:
    try:
        with open(path, encoding="utf-8") as handle:
            data = json.load(handle)
    except FileNotFoundError:
        return None
    except json.JSONDecodeError as exc:
        raise ValueError(f"{path} is not valid JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise ValueError(f"{path} should contain a JSON object")
    return data


def save(path: str, data: dict[str, Any]) -> None:
    """Write atomically so a crash cannot leave a half-written state file."""
    payload = {**data, "version": VERSION}
    directory = os.path.dirname(os.path.abspath(path))
    os.makedirs(directory, exist_ok=True)
    handle, temp_path = tempfile.mkstemp(dir=directory, prefix=".state-", suffix=".json")
    try:
        with os.fdopen(handle, "w", encoding="utf-8") as out:
            json.dump(payload, out, indent=2, ensure_ascii=False, sort_keys=True)
            out.write("\n")
        os.replace(temp_path, path)
    except BaseException:
        if os.path.exists(temp_path):
            os.unlink(temp_path)
        raise
