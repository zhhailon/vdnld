"""Browser-assisted media URL extraction using Playwright when needed."""

from __future__ import annotations

import time
from dataclasses import dataclass, replace
from importlib import import_module
from typing import Callable


class BrowserExtractionError(RuntimeError):
    """Raised when browser-assisted extraction cannot complete."""


class BrowserChallengeError(BrowserExtractionError):
    """Raised when the page presents an anti-bot or verification challenge."""


@dataclass(slots=True)
class BrowserMediaCandidate:
    url: str
    kind: str
    source: str = "browser"
    title: str | None = None
    request_headers: dict[str, str] | None = None
    content_length: int = -1
    media_type: str = "unknown"
    audio_url: str | None = None
    audio_request_headers: dict[str, str] | None = None
    height: int | None = None
    duration_seconds: float | None = None


def capture_media_requests(
    url: str,
    timeout_ms: int = 8_000,
    *,
    proxy_url: str | None = None,
    quality: str | None = None,
    audio_only: bool = False,
) -> BrowserMediaCandidate:
    return _capture_media_requests(
        url=url,
        timeout_ms=timeout_ms,
        headless=False,
        proxy_url=proxy_url,
        quality=quality,
        audio_only=audio_only,
    )


def interactive_capture_media_requests(
    url: str,
    timeout_ms: int = 30_000,
    *,
    proxy_url: str | None = None,
    quality: str | None = None,
    audio_only: bool = False,
    prompt_fn: PromptFn = input,
    printer: PrintFn = print,
) -> BrowserMediaCandidate:
    return _capture_media_requests(
        url=url,
        timeout_ms=timeout_ms,
        headless=False,
        interactive=True,
        proxy_url=proxy_url,
        quality=quality,
        audio_only=audio_only,
        prompt_fn=prompt_fn,
        printer=printer,
    )


def _capture_media_requests(
    url: str,
    timeout_ms: int,
    *,
    headless: bool,
    interactive: bool = False,
    proxy_url: str | None = None,
    quality: str | None = None,
    audio_only: bool = False,
    prompt_fn: PromptFn | None = None,
    printer: PrintFn | None = None,
) -> BrowserMediaCandidate:
    try:
        sync_api = import_module("playwright.sync_api")
    except ModuleNotFoundError as exc:
        raise BrowserExtractionError(
            "Playwright is not installed. Add the browser extra and install Chromium."
        ) from exc

    sync_playwright = sync_api.sync_playwright

    candidates: list[BrowserMediaCandidate] = []
    try:
        with sync_playwright() as playwright:
            browser = _launch_browser(playwright, headless=headless)
            proxy = {"server": proxy_url} if proxy_url else None
            context = browser.new_context(
                proxy=proxy,
                user_agent=(
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/124.0.0.0 Safari/537.36"
                ),
                viewport={"width": 1280, "height": 720},
                locale="zh-CN",
            )
            _apply_stealth(context)
            page = context.new_page()

            page_title: list[str | None] = [None]

            def on_response(response: object) -> None:
                response_url = response.url
                headers = response.headers
                content_type = (headers.get("content-type") or "").lower()
                request_headers = response.request.headers
                try:
                    content_length = int(headers.get("content-length") or -1)
                except (ValueError, TypeError):
                    content_length = -1
                candidate = _candidate_from_response(
                    response_url,
                    content_type,
                    request_headers,
                    title=page_title[0],
                    content_length=content_length,
                )
                if candidate is not None:
                    candidates.append(candidate)

            page.on("response", on_response)
            page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
            page_title[0] = _page_title(page)
            if interactive:
                if printer is not None:
                    printer(f"interactive browser opened for: {url}")
                    printer("Complete login, verification, and playback in the browser window.")
                    printer("Return here and press Enter when the media has started loading.")
                if prompt_fn is not None:
                    prompt_fn("")
                if printer is not None:
                    printer("capturing media requests, please wait...")
                time.sleep(10)
                if printer is not None:
                    printer("closing browser...")
            else:
                if _is_challenge_page(page):
                    time.sleep(12)
                if not _is_challenge_page(page):
                    _trigger_playback(page)
                else:
                    raise BrowserChallengeError(
                        "site protection challenge detected; complete verification in a normal browser and provide a user-authorized session"
                    )
                time.sleep(8)
                candidates.extend(
                    _bilibili_playinfo_candidates(page, title=page_title[0], page_url=url)
                )
                if not candidates:
                    _raise_if_challenge_page(page)
            browser.close()
    except BrowserChallengeError:
        raise
    except Exception as exc:
        raise BrowserExtractionError(f"browser extraction failed: {exc}") from exc

    if not candidates:
        raise BrowserExtractionError("no media requests were observed during browser playback")

    return _choose_best_candidate(candidates, quality=quality, audio_only=audio_only)


def _launch_browser(playwright: object, *, headless: bool) -> object:
    """Try real Chrome, then Edge, then fall back to bundled Chromium. Always incognito."""
    args = ["--incognito"]
    for channel in ("chrome", "msedge"):
        try:
            return playwright.chromium.launch(channel=channel, headless=headless, args=args)
        except Exception:
            continue
    return playwright.chromium.launch(headless=headless, args=args)


def _apply_stealth(context: object) -> None:
    """Inject JavaScript to mask Playwright's automation fingerprint."""
    context.add_init_script("""
        (() => {
            Object.defineProperty(navigator, 'webdriver', {
                get: () => undefined,
                configurable: true,
            });
            Object.defineProperty(navigator, 'plugins', {
                get: () => ({ length: 5 }),
                configurable: true,
            });
            Object.defineProperty(navigator, 'languages', {
                get: () => ['zh-CN', 'zh', 'en-US', 'en'],
                configurable: true,
            });
            if (!window.chrome) {
                window.chrome = { runtime: {} };
            }
            const origQuery = navigator.permissions && navigator.permissions.query
                ? navigator.permissions.query.bind(navigator.permissions)
                : null;
            if (origQuery) {
                navigator.permissions.query = (params) =>
                    params.name === 'notifications'
                        ? Promise.resolve({ state: Notification.permission })
                        : origQuery(params);
            }
        })();
    """)


def _trigger_playback(page: object) -> None:
    selectors = [
        "button[aria-label*='Play']",
        "button[title*='Play']",
        ".vjs-big-play-button",
        ".ytp-large-play-button",
        "[data-testid='play-button']",
    ]

    try:
        page.evaluate(
            """
            () => {
              const video = document.querySelector("video");
              if (video) {
                video.muted = false;
                video.volume = 1;
                return video.play()?.catch(() => {});
              }
            }
            """
        )
    except Exception:
        pass

    for selector in selectors:
        try:
            page.locator(selector).first.click(timeout=1_000)
            return
        except Exception:
            continue

    try:
        page.mouse.click(640, 360)
    except Exception:
        pass

    try:
        page.evaluate(
            """
            () => {
              const video = document.querySelector("video");
              if (video) {
                video.muted = false;
                video.volume = 1;
              }
            }
            """
        )
    except Exception:
        pass


def _candidate_from_response(
    url: str,
    content_type: str,
    request_headers: dict[str, str] | None = None,
    title: str | None = None,
    content_length: int = -1,
) -> BrowserMediaCandidate | None:
    lower_url = url.lower()
    if ".m3u8" in lower_url or "mpegurl" in content_type:
        return BrowserMediaCandidate(url=url, kind="hls", title=title, request_headers=request_headers, content_length=content_length)
    if ".mpd" in lower_url or "dash+xml" in content_type:
        return BrowserMediaCandidate(url=url, kind="dash", title=title, request_headers=request_headers, content_length=content_length)
    if content_type.startswith("video/"):
        return BrowserMediaCandidate(url=url, kind="direct", title=title, request_headers=request_headers, content_length=content_length, media_type="video")
    if content_type.startswith("audio/"):
        return BrowserMediaCandidate(url=url, kind="direct", title=title, request_headers=request_headers, content_length=content_length, media_type="audio")
    if lower_url.endswith((".mp4", ".webm", ".mkv", ".m4s")):
        return BrowserMediaCandidate(url=url, kind="direct", title=title, request_headers=request_headers, content_length=content_length, media_type="video")
    if lower_url.endswith((".m4a", ".mp3", ".aac", ".opus")):
        return BrowserMediaCandidate(url=url, kind="direct", title=title, request_headers=request_headers, content_length=content_length, media_type="audio")
    return None


def _choose_best_candidate(
    candidates: list[BrowserMediaCandidate],
    *,
    quality: str | None = None,
    audio_only: bool = False,
) -> BrowserMediaCandidate:
    if audio_only:
        audio_candidates = [item for item in candidates if item.kind == "direct" and item.media_type == "audio"]
        if audio_candidates:
            return max(audio_candidates, key=lambda item: item.content_length)

    hls_candidates = [item for item in candidates if item.kind == "hls"]
    if hls_candidates:
        return max(hls_candidates, key=lambda item: item.content_length)

    direct_candidates = [item for item in candidates if item.kind == "direct"]
    best_direct = _choose_best_direct_candidate(direct_candidates, quality=quality)
    if best_direct is not None:
        return best_direct

    rank = {"hls": 3, "dash": 2, "direct": 1}
    return max(candidates, key=lambda item: (rank.get(item.kind, 0), item.content_length))


def _choose_best_direct_candidate(
    candidates: list[BrowserMediaCandidate],
    *,
    quality: str | None = None,
) -> BrowserMediaCandidate | None:
    if not candidates:
        return None
    videos = [item for item in candidates if item.media_type == "video"]
    audios = [item for item in candidates if item.media_type == "audio"]
    if not videos:
        return max(candidates, key=lambda item: item.content_length)

    best_video = _choose_video_candidate(videos, quality=quality)
    if not audios:
        return best_video

    best_audio = max(audios, key=lambda item: item.content_length)
    return replace(
        best_video,
        audio_url=best_audio.url,
        audio_request_headers=best_audio.request_headers,
    )


def _choose_video_candidate(
    candidates: list[BrowserMediaCandidate],
    *,
    quality: str | None = None,
) -> BrowserMediaCandidate:
    normalized = (quality or "highest").strip().lower()
    if normalized in {"lowest", "worst", "min"}:
        return min(candidates, key=lambda item: (_candidate_height(item, default=10**9), item.content_length))

    target_height = _parse_quality_height(normalized)
    if target_height is not None:
        with_heights = [item for item in candidates if item.height is not None]
        if with_heights:
            exact_or_lower = [item for item in with_heights if item.height is not None and item.height <= target_height]
            if exact_or_lower:
                return max(exact_or_lower, key=lambda item: (_candidate_height(item), item.content_length))
            return min(with_heights, key=lambda item: (_candidate_height(item), -item.content_length))

    return max(candidates, key=lambda item: (_candidate_height(item), item.content_length))


def _candidate_height(candidate: BrowserMediaCandidate, default: int = -1) -> int:
    return candidate.height if candidate.height is not None else default


def _parse_quality_height(value: str) -> int | None:
    if value.endswith("p"):
        value = value[:-1]
    elif "x" in value:
        value = value.rsplit("x", 1)[-1]
    try:
        return int(value)
    except ValueError:
        return None


def _bilibili_playinfo_candidates(
    page: object,
    *,
    title: str | None,
    page_url: str,
) -> list[BrowserMediaCandidate]:
    try:
        playinfo = page.evaluate(
            """
            () => {
              const dash = window.__playinfo__ && window.__playinfo__.data && window.__playinfo__.data.dash;
              if (!dash) {
                return null;
              }
              const pickUrl = (item) => item.baseUrl || item.base_url || (item.backupUrl && item.backupUrl[0]) || (item.backup_url && item.backup_url[0]);
              return {
                userAgent: navigator.userAgent,
                duration: dash.duration || null,
                video: (dash.video || []).map((item) => ({
                  url: pickUrl(item),
                  bandwidth: item.bandwidth || -1,
                  height: item.height || null,
                })).filter((item) => item.url),
                audio: (dash.audio || []).map((item) => ({
                  url: pickUrl(item),
                  bandwidth: item.bandwidth || -1,
                })).filter((item) => item.url),
              };
            }
            """
        )
    except Exception:
        return []

    if not playinfo:
        return []

    request_headers = {
        "referer": page_url,
        "origin": "https://www.bilibili.com",
    }
    user_agent = playinfo.get("userAgent")
    if user_agent:
        request_headers["user-agent"] = user_agent

    candidates: list[BrowserMediaCandidate] = []
    duration_seconds = _float_or_none(playinfo.get("duration"))
    for item in playinfo.get("video") or []:
        candidates.append(
            BrowserMediaCandidate(
                url=item["url"],
                kind="direct",
                title=title,
                request_headers=request_headers,
                content_length=item.get("bandwidth") or -1,
                media_type="video",
                height=item.get("height"),
                duration_seconds=duration_seconds,
            )
        )
    for item in playinfo.get("audio") or []:
        candidates.append(
            BrowserMediaCandidate(
                url=item["url"],
                kind="direct",
                title=title,
                request_headers=request_headers,
                content_length=item.get("bandwidth") or -1,
                media_type="audio",
                duration_seconds=duration_seconds,
            )
        )
    return candidates


def _float_or_none(value: object) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _raise_if_challenge_page(page: object) -> None:
    if _is_challenge_page(page):
        raise BrowserChallengeError(
            "site protection challenge detected; complete verification in a normal browser and provide a user-authorized session"
        )


PromptFn = Callable[[str], str]
PrintFn = Callable[[str], None]


def _is_challenge_page(page: object) -> bool:
    title = (page.title() or "").strip().lower()
    html = (page.content() or "")[:8000].lower()
    markers = [
        "just a moment",
        "verify you are human",
        "cf-chl",
        "cloudflare",
        "attention required",
        "checking your browser",
    ]
    return any(marker in title or marker in html for marker in markers)


def _page_title(page: object) -> str | None:
    try:
        title = (page.title() or "").strip()
    except Exception:
        return None
    return title or None
