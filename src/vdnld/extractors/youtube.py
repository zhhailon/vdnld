"""YouTube page extractor based on embedded player bootstrap data."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass


@dataclass(slots=True)
class YouTubeExtraction:
    url: str | None
    title: str | None
    source: str
    notes: str | None = None


class YouTubeExtractionError(RuntimeError):
    """Raised when a YouTube page cannot be parsed into a usable media URL."""


def extract_youtube_media(html: str) -> YouTubeExtraction:
    player = _extract_initial_player_response(html)
    title = _extract_title(player)
    streaming = player.get("streamingData") or {}

    direct_url = _best_progressive_url(streaming.get("formats") or [])
    if direct_url is not None:
        return YouTubeExtraction(
            url=direct_url,
            title=title,
            source="progressive_format",
            notes="direct progressive format extracted from ytInitialPlayerResponse",
        )

    hls_url = streaming.get("hlsManifestUrl")
    if isinstance(hls_url, str) and hls_url:
        return YouTubeExtraction(
            url=hls_url,
            title=title,
            source="hls_manifest",
            notes="HLS manifest extracted from ytInitialPlayerResponse",
        )

    dash_url = streaming.get("dashManifestUrl")
    if isinstance(dash_url, str) and dash_url:
        return YouTubeExtraction(
            url=dash_url,
            title=title,
            source="dash_manifest",
            notes="DASH manifest extracted from ytInitialPlayerResponse",
        )

    server_abr = streaming.get("serverAbrStreamingUrl")
    if isinstance(server_abr, str) and server_abr:
        return YouTubeExtraction(
            url=server_abr,
            title=title,
            source="server_abr",
            notes="serverAbrStreamingUrl present but not yet normalized",
        )

    raise YouTubeExtractionError("no supported YouTube stream URL found in page bootstrap data")


def _extract_initial_player_response(html: str) -> dict:
    match = re.search(r"ytInitialPlayerResponse\s*=\s*", html)
    if not match:
        raise YouTubeExtractionError("ytInitialPlayerResponse not found")
    start = html.find("{", match.end())
    if start == -1:
        raise YouTubeExtractionError("ytInitialPlayerResponse JSON start not found")
    payload = _extract_json_object(html, start)
    return json.loads(payload)


def _extract_json_object(text: str, start: int) -> str:
    depth = 0
    in_string = False
    escaped = False
    for index in range(start, len(text)):
        char = text[index]
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return text[start : index + 1]
    raise YouTubeExtractionError("unterminated ytInitialPlayerResponse JSON")


def _best_progressive_url(formats: list[dict]) -> str | None:
    best: tuple[int, str] | None = None
    for item in formats:
        url = item.get("url")
        if not isinstance(url, str) or not url:
            continue
        score = _quality_score(item)
        if best is None or score > best[0]:
            best = (score, url)
    return best[1] if best else None


def _quality_score(item: dict) -> int:
    quality_label = item.get("qualityLabel")
    if isinstance(quality_label, str):
        digits = "".join(ch for ch in quality_label if ch.isdigit())
        if digits:
            return int(digits)
    bitrate = item.get("bitrate")
    if isinstance(bitrate, int):
        return bitrate
    return 0


def _extract_title(player: dict) -> str | None:
    details = player.get("videoDetails") or {}
    title = details.get("title")
    return title if isinstance(title, str) else None
