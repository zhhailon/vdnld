"""Runtime dependency checks."""

from __future__ import annotations

from shutil import which


class DependencyError(RuntimeError):
    """Raised when a required external tool is unavailable."""


def find_ffmpeg() -> str | None:
    return which("ffmpeg")


def require_ffmpeg() -> str:
    ffmpeg = find_ffmpeg()
    if ffmpeg is None:
        raise DependencyError(
            "ffmpeg was not found on PATH. Install it inside WSL and retry."
        )
    return ffmpeg
