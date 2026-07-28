"""Whisper transcription helpers."""

from __future__ import annotations

import subprocess
from pathlib import Path


class TranscriptionError(RuntimeError):
    """Raised when Whisper cannot transcribe a media file."""


TRANSCRIPT_FORMATS = ("txt", "srt", "vtt", "json", "tsv", "all")
_ALL_OUTPUT_FORMATS = ("txt", "srt", "vtt", "json", "tsv")


def transcribe_media(
    media_path: Path,
    *,
    output_dir: Path | None = None,
    model: str | None = None,
    language: str | None = None,
    output_format: str = "txt",
) -> list[Path]:
    command = build_whisper_command(
        media_path=media_path,
        output_dir=output_dir,
        model=model,
        language=language,
        output_format=output_format,
    )
    resolved_output_dir = output_dir or media_path.parent
    resolved_output_dir.mkdir(parents=True, exist_ok=True)
    try:
        subprocess.run(command, check=True)
    except KeyboardInterrupt as exc:
        raise TranscriptionError("transcription interrupted") from exc
    except subprocess.CalledProcessError as exc:
        raise TranscriptionError(f"whisper failed with exit code {exc.returncode}") from exc

    return transcript_paths(media_path, output_dir=output_dir, output_format=output_format)


def build_whisper_command(
    media_path: Path,
    *,
    output_dir: Path | None = None,
    model: str | None = None,
    language: str | None = None,
    output_format: str = "txt",
) -> list[str]:
    if output_format not in TRANSCRIPT_FORMATS:
        allowed = ", ".join(TRANSCRIPT_FORMATS)
        raise TranscriptionError(f"unsupported transcript format {output_format!r}; use one of: {allowed}")

    resolved_output_dir = output_dir or media_path.parent
    command = [
        "whisper",
        str(media_path),
        "--output_dir",
        str(resolved_output_dir),
        "--output_format",
        output_format,
    ]
    if model:
        command.extend(["--model", model])
    if language:
        command.extend(["--language", language])
    return command


def transcript_paths(
    media_path: Path,
    *,
    output_dir: Path | None = None,
    output_format: str = "txt",
) -> list[Path]:
    resolved_output_dir = output_dir or media_path.parent
    formats = _ALL_OUTPUT_FORMATS if output_format == "all" else (output_format,)
    return [resolved_output_dir / f"{media_path.stem}.{suffix}" for suffix in formats]
