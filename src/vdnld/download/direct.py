"""Resumable direct-download helpers."""

from __future__ import annotations

from pathlib import Path
from time import monotonic
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from vdnld.download.cache import cache_dir_for_output, clear_download_cache


class DirectDownloadError(RuntimeError):
    """Raised when vdnld cannot complete a direct-media download."""


def download_direct_media(
    source_url: str,
    output_path: Path,
    *,
    request_headers: dict[str, str] | None = None,
    progress_callback=None,
    resume: bool = True,
) -> Path:
    if not resume:
        clear_download_cache(output_path)

    state_dir = direct_state_dir(output_path)
    state_dir.mkdir(parents=True, exist_ok=True)
    cache_path = direct_cache_path(source_url, output_path)
    cache_path.parent.mkdir(parents=True, exist_ok=True)

    downloaded = cache_path.stat().st_size if cache_path.exists() else 0
    initial_downloaded = downloaded
    started_at = monotonic()
    headers = dict(request_headers or {})
    if downloaded > 0:
        headers["Range"] = f"bytes={downloaded}-"

    request = Request(source_url, headers=headers)
    try:
        with urlopen(request, timeout=30.0) as response:
            total_size = _total_size(response, downloaded)
            mode = "ab" if downloaded > 0 and getattr(response, "status", None) == 206 else "wb"
            if mode == "wb":
                downloaded = 0
            with cache_path.open(mode) as handle:
                while True:
                    chunk = response.read(1024 * 256)
                    if not chunk:
                        break
                    handle.write(chunk)
                    downloaded += len(chunk)
                    if progress_callback is not None:
                        elapsed = max(monotonic() - started_at, 0.0)
                        bytes_per_second = None
                        session_downloaded = downloaded - initial_downloaded
                        if session_downloaded > 0 and elapsed > 0:
                            bytes_per_second = session_downloaded / elapsed
                        progress_callback(
                            render_direct_progress(
                                downloaded,
                                total_size,
                                bytes_per_second=bytes_per_second,
                            )
                        )
    except Exception as exc:  # pragma: no cover - normalized below
        raise DirectDownloadError(f"failed to download media: {exc}") from exc

    return cache_path


def direct_state_dir(output_path: Path) -> Path:
    return cache_dir_for_output(output_path)


def direct_cache_path(source_url: str, output_path: Path) -> Path:
    suffix = Path(urlparse(source_url).path).suffix or ".bin"
    return direct_state_dir(output_path) / f"source{suffix}"


def render_direct_progress(
    downloaded: int,
    total_size: int | None,
    *,
    bytes_per_second: float | None = None,
) -> str:
    speed_label = _format_rate(bytes_per_second)
    if total_size and total_size > 0:
        ratio = max(0.0, min(1.0, downloaded / total_size))
        percent = int(ratio * 100)
        bar = _render_progress_bar(ratio)
        parts = [f"direct: {percent:3d}% {bar} {_format_size(downloaded)}/{_format_size(total_size)}"]
        if speed_label:
            parts.append(speed_label)
        return " ".join(parts)
    parts = [f"direct: {_format_size(downloaded)}"]
    if speed_label:
        parts.append(speed_label)
    return " ".join(parts)


def _total_size(response, downloaded: int) -> int | None:
    content_range = response.headers.get("Content-Range")
    if content_range and "/" in content_range:
        total_text = content_range.rsplit("/", 1)[-1]
        if total_text.isdigit():
            return int(total_text)
    content_length = response.headers.get("Content-Length")
    if content_length and content_length.isdigit():
        size = int(content_length)
        if getattr(response, "status", None) == 206 and downloaded > 0:
            return downloaded + size
        return size
    return None


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


def _format_rate(bytes_per_second: float | None) -> str | None:
    if bytes_per_second is None or bytes_per_second <= 0:
        return None
    return f"{_format_size(int(bytes_per_second))}/s"


def _render_progress_bar(ratio: float, width: int = 24) -> str:
    filled = int(ratio * width)
    return "[" + "#" * filled + "-" * (width - filled) + "]"
