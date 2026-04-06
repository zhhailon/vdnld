"""Resumable HLS download helpers."""

from __future__ import annotations

import math
from pathlib import Path
from time import monotonic
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from vdnld.download.cache import cache_dir_for_output, clear_download_cache
from vdnld.manifest.m3u8 import M3U8Playlist, parse_m3u8
from vdnld.net.http import FetchError, HttpTextResponse, fetch_text


class HlsDownloadError(RuntimeError):
    """Raised when vdnld cannot complete an HLS download."""


def download_hls_media_playlist(
    source_url: str,
    output_path: Path,
    *,
    request_headers: dict[str, str] | None = None,
    fetcher=fetch_text,
    progress_callback=None,
    resume: bool = True,
) -> Path:
    if not resume:
        clear_download_cache(output_path)

    state_dir = hls_state_dir(output_path)
    segments_dir = state_dir / "segments"
    segments_dir.mkdir(parents=True, exist_ok=True)

    playlist_response = _fetch_text(source_url, request_headers=request_headers, fetcher=fetcher)
    playlist = parse_m3u8(playlist_response.text, base_url=playlist_response.url)
    if playlist.kind == "master":
        variant = playlist.best_variant()
        if variant is None:
            raise HlsDownloadError("master playlist did not contain any variants")
        playlist_response = _fetch_text(variant.uri, request_headers=request_headers, fetcher=fetcher)
        playlist = parse_m3u8(playlist_response.text, base_url=playlist_response.url)
    if playlist.kind != "media":
        raise HlsDownloadError("expected a media playlist")
    if not playlist.segments:
        raise HlsDownloadError("media playlist did not contain any segments")

    cached_count = 0
    completed_duration = 0.0
    total_duration = _playlist_duration(playlist)
    local_entries: list[tuple[float | None, str]] = []
    downloaded_bytes = 0
    started_at = monotonic()

    for index, segment in enumerate(playlist.segments):
        local_name = _segment_filename(index, segment.uri)
        local_path = segments_dir / local_name
        local_entries.append((segment.duration, f"segments/{local_name}"))
        if local_path.exists() and local_path.stat().st_size > 0:
            cached_count += 1
            if segment.duration is not None:
                completed_duration += segment.duration
            if progress_callback is not None:
                progress_callback(
                    render_hls_progress(
                        current=index + 1,
                        total=len(playlist.segments),
                        completed_duration=completed_duration,
                        total_duration=total_duration,
                        phase="resume",
                        bytes_per_second=None,
                    )
                )
            continue

        segment_size = _download_segment(segment.uri, local_path, request_headers=request_headers) or 0
        downloaded_bytes += segment_size
        if segment.duration is not None:
            completed_duration += segment.duration
        if progress_callback is not None:
            elapsed = max(monotonic() - started_at, 0.0)
            bytes_per_second = None
            if downloaded_bytes > 0 and elapsed > 0:
                bytes_per_second = downloaded_bytes / elapsed
            progress_callback(
                render_hls_progress(
                    current=index + 1,
                    total=len(playlist.segments),
                    completed_duration=completed_duration,
                    total_duration=total_duration,
                    phase="download",
                    bytes_per_second=bytes_per_second,
                )
            )

    write_local_playlist(state_dir / "playlist.m3u8", local_entries)
    if progress_callback is not None and cached_count:
        progress_callback(f"hls: resumed {cached_count}/{len(playlist.segments)} segments")
    return state_dir / "playlist.m3u8"


def hls_state_dir(output_path: Path) -> Path:
    return cache_dir_for_output(output_path)


def write_local_playlist(path: Path, entries: list[tuple[float | None, str]]) -> None:
    target_duration = max((math.ceil(duration or 0.0) for duration, _ in entries), default=1)
    lines = [
        "#EXTM3U",
        "#EXT-X-VERSION:3",
        f"#EXT-X-TARGETDURATION:{max(target_duration, 1)}",
        "#EXT-X-MEDIA-SEQUENCE:0",
    ]
    for duration, local_name in entries:
        if duration is not None:
            lines.append(f"#EXTINF:{duration:.6f},")
        lines.append(local_name)
    lines.append("#EXT-X-ENDLIST")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def render_hls_progress(
    *,
    current: int,
    total: int,
    completed_duration: float | None,
    total_duration: float | None,
    phase: str,
    bytes_per_second: float | None = None,
) -> str:
    if total <= 0:
        return "hls: 0/0"
    ratio = max(0.0, min(1.0, current / total))
    percent = int(ratio * 100)
    bar = _render_progress_bar(ratio)
    label = "resume" if phase == "resume" else "download"
    speed_label = _format_rate(bytes_per_second)
    if completed_duration is not None and total_duration and total_duration > 0:
        current_label = _format_seconds(completed_duration)
        total_label = _format_seconds(total_duration)
        parts = [f"hls: {label} {percent:3d}% {bar} {current}/{total} {current_label}/{total_label}"]
        if speed_label:
            parts.append(speed_label)
        return " ".join(parts)
    parts = [f"hls: {label} {percent:3d}% {bar} {current}/{total}"]
    if speed_label:
        parts.append(speed_label)
    return " ".join(parts)


def _fetch_text(
    url: str,
    *,
    request_headers: dict[str, str] | None,
    fetcher,
) -> HttpTextResponse:
    if not request_headers:
        return fetcher(url)
    request = Request(url, headers=request_headers)
    try:
        with urlopen(request, timeout=20.0) as response:
            raw = response.read()
            content_type = response.headers.get_content_type()
            charset = response.headers.get_content_charset() or "utf-8"
            return HttpTextResponse(
                url=response.geturl(),
                content_type=content_type,
                text=raw.decode(charset, errors="replace"),
            )
    except Exception as exc:  # pragma: no cover - normalized below
        raise FetchError(f"network error for {url}: {exc}") from exc


def _download_segment(
    url: str,
    destination: Path,
    *,
    request_headers: dict[str, str] | None,
) -> int:
    request = Request(url, headers=request_headers or {})
    try:
        with urlopen(request, timeout=30.0) as response:
            raw = response.read()
    except Exception as exc:  # pragma: no cover - normalized below
        raise HlsDownloadError(f"failed to download segment {url}: {exc}") from exc
    destination.write_bytes(raw)
    return len(raw)


def _segment_filename(index: int, uri: str) -> str:
    suffix = Path(urlparse(uri).path).suffix or ".bin"
    return f"{index:05d}{suffix}"


def _playlist_duration(playlist: M3U8Playlist) -> float | None:
    total = 0.0
    seen = False
    for segment in playlist.segments:
        if segment.duration is None:
            continue
        total += segment.duration
        seen = True
    return total if seen else None


def _format_seconds(value: float) -> str:
    total = int(value)
    hours = total // 3600
    minutes = (total % 3600) // 60
    seconds = total % 60
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}"


def _format_rate(bytes_per_second: float | None) -> str | None:
    if bytes_per_second is None or bytes_per_second <= 0:
        return None
    return f"{_format_size(int(bytes_per_second))}/s"


def _format_size(size: int) -> str:
    value = float(size)
    units = ["B", "KB", "MB", "GB", "TB"]
    for unit in units:
        if value < 1024.0 or unit == units[-1]:
            if unit == "B":
                return f"{int(value)}{unit}"
            return f"{value:.1f}{unit}"
        value /= 1024.0
    return f"{size}B"


def _render_progress_bar(ratio: float, width: int = 24) -> str:
    filled = int(ratio * width)
    return "[" + "#" * filled + "-" * (width - filled) + "]"
