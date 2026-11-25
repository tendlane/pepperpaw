"""Lanes stopped on purpose, read from the command that ``[stops]`` names.

The command prints a JSON list of lane records. A record with a ``lane`` name and a ``stopped`` object
(``by``, ``at``, ``why``) is a stop on purpose; ``courier agents`` shows one line for each such lane that runs in
no pane, so a lane stopped on purpose reads apart from one that went away without a word.
"""

import json
import os
import subprocess
from dataclasses import asdict, dataclass

from .config import Stops

MAX_OUTPUT = 1 << 20


@dataclass(frozen=True)
class Stop:
    lane: str
    by: str
    at: str
    why: str

    def as_dict(self) -> dict[str, str]:
        return asdict(self)

    def line(self) -> str:
        return f"{self.lane} stopped on purpose at {self.at[:16].replace('T', ' ')} by {self.by}: {self.why}"


def read(settings: Stops) -> tuple[list[Stop], str | None]:
    """The stops the command prints, and a note when it could not be read; nothing when no command is set."""
    if not settings.command:
        return [], None
    try:
        done = subprocess.run(
            [os.path.expandvars(arg) for arg in settings.command],
            capture_output=True,
            encoding="utf-8",
            errors="replace",
            timeout=settings.timeout,
            check=False,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return [], f"stops command failed: {exc}"
    if done.returncode:
        return [], f"stops command exited {done.returncode}: {(done.stderr or '').strip()[:200]}"
    if len(done.stdout) > MAX_OUTPUT:
        return [], "stops command printed more than 1 MiB"
    try:
        records = json.loads(done.stdout)
    except ValueError:
        return [], "stops command did not print JSON"
    if not isinstance(records, list):
        return [], "stops command did not print a JSON list"
    found = []
    for record in records:
        if not isinstance(record, dict):
            continue
        lane, mark = record.get("lane"), record.get("stopped")
        if isinstance(lane, str) and lane and isinstance(mark, dict):
            found.append(
                Stop(
                    lane,
                    str(mark.get("by") or "?"),
                    str(mark.get("at") or "?"),
                    str(mark.get("why") or "?"),
                )
            )
    return found, None


def not_running(stops: list[Stop], running: set[str]) -> list[Stop]:
    """The stops whose lane runs in no pane; a lane that runs again is not shown as stopped."""
    return [s for s in stops if s.lane not in running]
