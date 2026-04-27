"""Execution layer for supported download strategies."""

from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path
from urllib.parse import urlparse

from vdnld.download.cache import clear_download_cache
from vdnld.download.direct import DirectDownloadError, download_direct_media
from vdnld.download.hls import HlsDownloadError, download_hls_media_playlist
from vdnld.download.manager import DownloadPlan


class DownloadExecutionError(RuntimeError):
    """Raised when vdnld cannot execute a planned download."""


def execute_plan(plan: DownloadPlan, *, resume: bool = True) -> Path:
    if not plan.executable:
        raise DownloadExecutionError(
            f"strategy {plan.strategy!r} is not executable yet: {plan.notes or 'unsupported'}"
        )

    source_url = plan.selected_url or plan.url
    output_path = resolve_output_path(plan)
    if plan.strategy in {"hls_master", "hls_media"}:
        run_hls_download(
            source_url=source_url,
            output_path=output_path,
            request_headers=plan.request_headers,
            duration_seconds=plan.duration_seconds,
            resume=resume,
        )
    elif plan.strategy in {"direct", "browser_direct", "youtube_direct"}:
        run_direct_download(
            source_url=source_url,
            output_path=output_path,
            request_headers=plan.request_headers,
            duration_seconds=plan.duration_seconds,
            resume=resume,
        )
    else:
        run_ffmpeg_copy(
            source_url=source_url,
            output_path=output_path,
            request_headers=plan.request_headers,
            duration_seconds=plan.duration_seconds,
        )
    return output_path


def resolve_output_path(plan: DownloadPlan) -> Path:
    if plan.output:
        return Path(plan.output)

    suffix = default_suffix_for_plan(plan)
    basename = derive_output_basename(plan)
    return Path(basename).with_suffix(suffix)


def default_suffix_for_plan(plan: DownloadPlan) -> str:
    if plan.strategy in {"hls_master", "hls_media"}:
        return ".mp4"
    return ".mp4"


def derive_output_basename(plan: DownloadPlan) -> str:
    if plan.title:
        cleaned = sanitize_filename(plan.title)
        if cleaned:
            return cleaned

    source = plan.selected_url or plan.url
    parsed = urlparse(source)
    tail = Path(parsed.path).stem
    cleaned = sanitize_filename(tail)
    if cleaned:
        return cleaned

    return "output"


def run_ffmpeg_copy(
    source_url: str,
    output_path: Path,
    request_headers: dict[str, str] | None = None,
    duration_seconds: float | None = None,
    *,
    local_input: bool = False,
    local_hls: bool = False,
) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    partial_path = partial_output_path(output_path)
    if partial_path.exists():
        partial_path.unlink()

    command = build_ffmpeg_command(
        source_url=source_url,
        output_path=partial_path,
        request_headers=request_headers,
        local_input=local_input,
        local_hls=local_hls,
    )
    process = subprocess.Popen(
        command,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        text=True,
    )

    last_status = ""
    stderr_tail: list[str] = []
    had_progress_output = False
    try:
        assert process.stderr is not None
        for line in process.stderr:
            stderr_tail.append(line.rstrip())
            stderr_tail = stderr_tail[-20:]
            parsed = parse_ffmpeg_status_line(line, duration_seconds=duration_seconds)
            if parsed and parsed != last_status:
                _render_progress_line(parsed)
                had_progress_output = True
                last_status = parsed
        return_code = process.wait()
    except KeyboardInterrupt as exc:
        process.kill()
        process.wait()
        if partial_path.exists():
            partial_path.unlink()
        if had_progress_output:
            print()
        raise DownloadExecutionError("download interrupted") from exc

    if return_code != 0:
        if partial_path.exists():
            partial_path.unlink()
        stderr_output = "\n".join(line for line in stderr_tail if line).strip()
        if had_progress_output:
            print()
        raise DownloadExecutionError(stderr_output or "ffmpeg failed")

    if had_progress_output:
        print()
    os.replace(partial_path, output_path)


def run_hls_download(
    source_url: str,
    output_path: Path,
    request_headers: dict[str, str] | None = None,
    duration_seconds: float | None = None,
    *,
    resume: bool = True,
) -> None:
    try:
        local_playlist = download_hls_media_playlist(
            source_url,
            output_path,
            request_headers=request_headers,
            progress_callback=_render_progress_line,
            resume=resume,
        )
    except HlsDownloadError as exc:
        print()
        raise DownloadExecutionError(str(exc)) from exc

    print()
    try:
        run_ffmpeg_copy(
            source_url=str(local_playlist),
            output_path=output_path,
            duration_seconds=duration_seconds,
            local_hls=True,
        )
    except DownloadExecutionError as exc:
        raise DownloadExecutionError(f"hls mux failed: {exc}") from exc
    clear_download_cache(output_path)


def run_direct_download(
    source_url: str,
    output_path: Path,
    request_headers: dict[str, str] | None = None,
    duration_seconds: float | None = None,
    *,
    resume: bool = True,
) -> None:
    try:
        local_source = download_direct_media(
            source_url,
            output_path,
            request_headers=request_headers,
            progress_callback=_render_progress_line,
            resume=resume,
        )
    except DirectDownloadError as exc:
        print()
        raise DownloadExecutionError(str(exc)) from exc

    print()
    try:
        run_ffmpeg_copy(
            source_url=str(local_source),
            output_path=output_path,
            duration_seconds=duration_seconds,
            local_input=True,
        )
    except DownloadExecutionError as exc:
        raise DownloadExecutionError(f"direct mux failed: {exc}") from exc
    clear_download_cache(output_path)


def build_ffmpeg_command(
    source_url: str,
    output_path: Path,
    request_headers: dict[str, str] | None = None,
    *,
    local_input: bool = False,
    local_hls: bool = False,
) -> list[str]:
    command = [
        "ffmpeg",
        "-y",
    ]
    if request_headers:
        header_blob = "".join(f"{key}: {value}\r\n" for key, value in request_headers.items())
        command.extend(["-headers", header_blob])
    if local_hls:
        # Local HLS remux can reference cached segments with nonstandard suffixes
        # such as .jpeg even when the payload is valid media data.
        command.extend(["-allowed_extensions", "ALL"])
        command.extend(["-protocol_whitelist", "file,crypto,data"])
    command.extend(
        [
        "-i",
        source_url,
        "-c",
        "copy",
        str(output_path),
        ]
    )
    return command


def clear_plan_cache(plan: DownloadPlan) -> tuple[Path, bool]:
    output_path = resolve_output_path(plan)
    cleared = clear_download_cache(output_path)
    return output_path, cleared


def partial_output_path(output_path: Path) -> Path:
    if output_path.suffix:
        return output_path.with_name(f"{output_path.stem}.part{output_path.suffix}")
    return output_path.with_name(f"{output_path.name}.part")


def sanitize_filename(value: str) -> str:
    collapsed = re.sub(r"\s+", " ", value).strip()
    collapsed = strip_site_suffix(collapsed)
    sanitized = re.sub(r'[<>:"/\\\\|?*\x00-\x1f]', "_", collapsed)
    sanitized = sanitized.rstrip(". ")
    return sanitized[:180] or "output"


def strip_site_suffix(value: str) -> str:
    patterns = [
        r"\s*[-|]\s*YouTube$",
        r"\s*[-|]\s*MissAV$",
        r"\s*[-|]\s*MISSAV$",
        r"\s*[-|]\s*在线观看$",
        r"\s*[-|]\s*Watch Online.*$",
    ]
    cleaned = value
    for pattern in patterns:
        cleaned = re.sub(pattern, "", cleaned, flags=re.IGNORECASE).strip()
    return cleaned


def parse_ffmpeg_status_line(line: str, duration_seconds: float | None = None) -> str | None:
    stripped = line.strip()
    if not stripped.startswith("frame=") and "time=" not in stripped:
        return None
    compact = " ".join(stripped.split())
    current_seconds = _parse_ffmpeg_time(compact)
    speed = _parse_ffmpeg_field(compact, "speed")
    if current_seconds is not None and duration_seconds and duration_seconds > 0:
        ratio = max(0.0, min(1.0, current_seconds / duration_seconds))
        percent = int(ratio * 100)
        bar = _render_progress_bar(ratio)
        current_label = _format_seconds(current_seconds)
        total_label = _format_seconds(duration_seconds)
        speed_label = speed or "?"
        return f"progress: {percent:3d}% {bar} {current_label}/{total_label} {speed_label}"
    if current_seconds is not None:
        current_label = _format_seconds(current_seconds)
        speed_label = speed or "?"
        return f"ffmpeg: {current_label} {speed_label}"
    return f"ffmpeg: {compact}"


def _parse_ffmpeg_time(text: str) -> float | None:
    match = re.search(r"time=(\d+):(\d+):(\d+(?:\.\d+)?)", text)
    if not match:
        return None
    hours = int(match.group(1))
    minutes = int(match.group(2))
    seconds = float(match.group(3))
    return hours * 3600 + minutes * 60 + seconds


def _parse_ffmpeg_field(text: str, key: str) -> str | None:
    match = re.search(rf"{re.escape(key)}=\s*([^\s]+)", text)
    if not match:
        return None
    return match.group(1)


def _format_seconds(value: float) -> str:
    total = int(value)
    hours = total // 3600
    minutes = (total % 3600) // 60
    seconds = total % 60
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}"


def _render_progress_bar(ratio: float, width: int = 24) -> str:
    filled = int(ratio * width)
    return "[" + "#" * filled + "-" * (width - filled) + "]"


def _render_progress_line(text: str) -> None:
    sys.stdout.write("\r" + text)
    sys.stdout.flush()
