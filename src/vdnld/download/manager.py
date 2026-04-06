"""Download planning layer."""

from __future__ import annotations

from dataclasses import dataclass

from vdnld.extractors.browser import (
    BrowserChallengeError,
    BrowserExtractionError,
    BrowserMediaCandidate,
    capture_media_requests,
)
from vdnld.extractors.registry import choose_extractor
from vdnld.extractors.youtube import YouTubeExtractionError, extract_youtube_media
from vdnld.manifest.m3u8 import M3U8Playlist, parse_m3u8
from vdnld.merge.policy import needs_media_merge
from vdnld.net.http import FetchError, FetchText, fetch_text, fetch_text_with_headers


@dataclass(slots=True)
class DownloadPlan:
    url: str
    output: str | None
    extractor: str
    strategy: str
    needs_merge: bool
    title: str | None = None
    selected_url: str | None = None
    notes: str | None = None
    executable: bool = False
    request_headers: dict[str, str] | None = None
    duration_seconds: float | None = None


def plan_download(
    url: str,
    output: str | None,
    fetcher: FetchText = fetch_text,
    browser_probe: BrowserProbe = capture_media_requests,
    browser_fallback: bool = True,
) -> DownloadPlan:
    extractor = choose_extractor(url)

    if extractor == "youtube":
        youtube_plan = _plan_youtube(url, output, fetcher)
        if youtube_plan is not None:
            return youtube_plan
        if browser_fallback:
            browser_plan = _plan_with_browser(url, output, fetcher, browser_probe)
            if browser_plan is not None:
                return browser_plan
        return DownloadPlan(
            url=url,
            output=output,
            extractor=extractor,
            strategy="site",
            needs_merge=needs_media_merge(extractor),
            title=None,
            selected_url=url,
            notes="site-specific extractor required",
            executable=False,
        )

    if extractor == "vimeo":
        if browser_fallback:
            browser_plan = _plan_with_browser(url, output, fetcher, browser_probe)
            if browser_plan is not None:
                return browser_plan
        return DownloadPlan(
            url=url,
            output=output,
            extractor=extractor,
            strategy="site",
            needs_merge=needs_media_merge(extractor),
            title=None,
            selected_url=url,
            notes="site-specific extractor required",
            executable=False,
        )

    try:
        response = fetcher(url)
    except FetchError as exc:
        if browser_fallback:
            browser_plan = _plan_with_browser(url, output, fetcher, browser_probe)
            if browser_plan is not None:
                return browser_plan
        return DownloadPlan(
            url=url,
            output=output,
            extractor=extractor,
            strategy="probe_failed",
            needs_merge=False,
            title=None,
            selected_url=url,
            notes=str(exc),
            executable=False,
        )

    if _looks_like_m3u8(url=url, response=response):
        playlist = parse_m3u8(response.text, base_url=response.url)
        return _plan_hls(url=url, output=output, extractor=extractor, playlist=playlist)

    plan = DownloadPlan(
        url=url,
        output=output,
        extractor=extractor,
        strategy="direct",
        needs_merge=False,
        title=None,
        selected_url=response.url,
        notes=response.content_type or None,
        executable=_looks_like_direct_media(response),
    )
    if not plan.executable and browser_fallback:
        browser_plan = _plan_with_browser(url, output, fetcher, browser_probe)
        if browser_plan is not None:
            return browser_plan
    return plan


def _looks_like_m3u8(url: str, response: "HttpResponseLike") -> bool:
    content_type = (response.content_type or "").lower()
    if ".m3u8" in url.lower() or ".m3u8" in response.url.lower():
        return True
    if "mpegurl" in content_type or "vnd.apple.mpegurl" in content_type:
        return True
    return response.text.lstrip().startswith("#EXTM3U")


def _plan_hls(
    url: str,
    output: str | None,
    extractor: str,
    playlist: M3U8Playlist,
) -> DownloadPlan:
    if playlist.kind == "master":
        best = playlist.best_variant()
        return DownloadPlan(
            url=url,
            output=output,
            extractor="hls",
            strategy="hls_master",
            needs_merge=False,
            title=None,
            selected_url=best.uri if best else url,
            notes=f"{len(playlist.variants)} variants discovered",
            executable=best is not None,
        )

    return DownloadPlan(
        url=url,
        output=output,
        extractor="hls",
        strategy="hls_media",
        needs_merge=False,
        title=None,
        selected_url=url,
        notes=f"{len(playlist.segments)} segments discovered",
        executable=True,
        duration_seconds=_playlist_duration(playlist),
    )


class HttpResponseLike:
    url: str
    content_type: str
    text: str


def _looks_like_direct_media(response: "HttpResponseLike") -> bool:
    content_type = (response.content_type or "").lower()
    if content_type.startswith("video/") or content_type.startswith("audio/"):
        return True
    lower_url = response.url.lower()
    return lower_url.endswith((".mp4", ".m4a", ".mp3", ".webm", ".mkv", ".aac"))


def _plan_youtube(url: str, output: str | None, fetcher: FetchText) -> DownloadPlan | None:
    try:
        response = fetcher(url)
        extraction = extract_youtube_media(response.text)
    except (FetchError, YouTubeExtractionError):
        return None

    if extraction.url is None:
        return None

    if extraction.source == "hls_manifest":
        manifest_response = fetcher(extraction.url)
        playlist = parse_m3u8(manifest_response.text, base_url=manifest_response.url)
        plan = _plan_hls(url, output, "youtube", playlist)
        plan.notes = extraction.notes
        return plan

    executable = extraction.source == "progressive_format"
    strategy = "youtube_direct" if executable else "youtube_unsupported"
    return DownloadPlan(
        url=url,
        output=output,
        extractor="youtube",
        strategy=strategy,
        needs_merge=not executable,
        title=extraction.title,
        selected_url=extraction.url,
        notes=extraction.notes,
        executable=executable,
    )


def _plan_with_browser(
    url: str,
    output: str | None,
    fetcher: FetchText,
    browser_probe: "BrowserProbe",
) -> DownloadPlan | None:
    try:
        candidate = browser_probe(url)
    except BrowserChallengeError as exc:
        return DownloadPlan(
            url=url,
            output=output,
            extractor="browser",
            strategy="challenge_detected",
            needs_merge=False,
            title=None,
            selected_url=url,
            notes=str(exc),
            executable=False,
        )
    except BrowserExtractionError:
        return None
    return _plan_from_browser_candidate(url, output, candidate, fetcher)


def _plan_from_browser_candidate(
    original_url: str,
    output: str | None,
    candidate: BrowserMediaCandidate,
    fetcher: FetchText,
) -> DownloadPlan:
    request_headers = _filter_request_headers(candidate.request_headers)
    if candidate.kind == "hls":
        response = _fetch_browser_text(candidate.url, request_headers=request_headers, fetcher=fetcher)
        playlist = parse_m3u8(response.text, base_url=response.url)
        plan = _plan_hls(original_url, output, "browser", playlist)
        plan.title = candidate.title
        plan.notes = f"{plan.notes}; extracted via browser"
        plan.request_headers = request_headers
        if plan.strategy == "hls_master" and plan.selected_url:
            try:
                media_response = _fetch_browser_text(
                    plan.selected_url,
                    request_headers=request_headers,
                    fetcher=fetcher,
                )
                media_playlist = parse_m3u8(media_response.text, base_url=media_response.url)
                if media_playlist.kind == "media":
                    plan.duration_seconds = _playlist_duration(media_playlist)
            except FetchError:
                pass
        return plan

    if candidate.kind == "direct":
        return DownloadPlan(
            url=original_url,
            output=output,
            extractor="browser",
            strategy="browser_direct",
            needs_merge=False,
            title=candidate.title,
            selected_url=candidate.url,
            notes="direct media extracted via browser",
            executable=True,
            request_headers=request_headers,
        )

    return DownloadPlan(
        url=original_url,
        output=output,
        extractor="browser",
        strategy="browser_unsupported",
        needs_merge=False,
        title=candidate.title,
        selected_url=candidate.url,
        notes=f"{candidate.kind} extracted via browser but not supported yet",
        executable=False,
    )


class BrowserProbe:
    def __call__(self, url: str) -> BrowserMediaCandidate: ...


def _fetch_browser_text(
    url: str,
    *,
    request_headers: dict[str, str] | None,
    fetcher: FetchText,
):
    if request_headers:
        return fetch_text_with_headers(url, headers=request_headers)
    return fetcher(url)


def _filter_request_headers(headers: dict[str, str] | None) -> dict[str, str] | None:
    if not headers:
        return None
    allowed = {}
    for key in ("referer", "origin", "user-agent", "cookie"):
        value = headers.get(key)
        if value:
            allowed[key] = value
    return allowed or None


def _playlist_duration(playlist: M3U8Playlist) -> float | None:
    total = 0.0
    seen = False
    for segment in playlist.segments:
        if segment.duration is None:
            continue
        total += segment.duration
        seen = True
    return total if seen else None
