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


def find_aria2c() -> str | None:
    return which("aria2c")


def require_aria2c() -> str:
    aria2c = find_aria2c()
    if aria2c is None:
        raise DependencyError(
            "aria2c was not found on PATH. Install aria2 inside WSL and retry."
        )
    return aria2c


def find_whisper() -> str | None:
    return which("whisper")


def require_whisper() -> str:
    whisper = find_whisper()
    if whisper is None:
        raise DependencyError(
            "whisper was not found on PATH. Install OpenAI Whisper inside WSL and retry."
        )
    return whisper
