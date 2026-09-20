"""Stdlib-only JSON and file utilities for subprocess-toolkit orchestration scripts."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def read_json_field(path: Path, field: str) -> Any:
    """Read a dot-separated field path from a JSON file.

    Numeric segments index into lists, so "a.b.0" is valid.

    Example::
        read_json_field(Path("response.json"), "status")
        read_json_field(Path("data.json"), "a.b.c")
    """
    data: Any = json.loads(Path(path).read_text(encoding="utf-8"))
    for part in field.split("."):
        if part == "":
            continue
        data = data[int(part)] if isinstance(data, list) else data[part]
    return data


def write_json_file(path: Path, data: dict[str, Any]) -> None:
    """Write a dictionary as a pretty-printed JSON file."""
    Path(path).write_text(json.dumps(data, indent=2, sort_keys=True), encoding="utf-8")


def wrap_payload(payload_path: Path, destination: Path) -> None:
    """Wrap a raw payload file in {"input": ...} for invocation."""
    with payload_path.open(encoding="utf-8") as handle:
        payload = json.load(handle)
    destination.write_text(
        json.dumps({"input": payload}, separators=(",", ":")), encoding="utf-8"
    )
