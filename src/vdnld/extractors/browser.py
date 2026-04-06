"""Browser-assisted media URL extraction using Playwright when needed."""

from __future__ import annotations

from dataclasses import dataclass
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


def capture_media_requests(url: str, timeout_ms: int = 8_000) -> BrowserMediaCandidate:
    return _capture_media_requests(
        url=url,
        timeout_ms=timeout_ms,
        headless=True,
    )


def interactive_capture_media_requests(
    url: str,
    timeout_ms: int = 30_000,
    *,
    prompt_fn: PromptFn = input,
    printer: PrintFn = print,
) -> BrowserMediaCandidate:
    return _capture_media_requests(
        url=url,
        timeout_ms=timeout_ms,
        headless=False,
        interactive=True,
        prompt_fn=prompt_fn,
        printer=printer,
    )


def _capture_media_requests(
    url: str,
    timeout_ms: int,
    *,
    headless: bool,
    interactive: bool = False,
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
            browser = playwright.chromium.launch(headless=headless)
            context = browser.new_context()
            page = context.new_page()

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
                    title=_page_title(page),
                    content_length=content_length,
                )
                if candidate is not None:
                    candidates.append(candidate)

            page.on("response", on_response)
            page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
            if interactive:
                if printer is not None:
                    printer(f"interactive browser opened for: {url}")
                    printer("Complete login, verification, and playback in the browser window.")
                    printer("Return here and press Enter when the media has started loading.")
                if prompt_fn is not None:
                    prompt_fn("")
                if not candidates:
                    _trigger_playback(page)
            else:
                _raise_if_challenge_page(page)
                _trigger_playback(page)
            page.wait_for_timeout(6_000)
            if not interactive:
                _raise_if_challenge_page(page)
            elif not candidates and _is_challenge_page(page):
                raise BrowserChallengeError(
                    "site protection challenge still appears active after manual interaction"
                )
            browser.close()
    except BrowserChallengeError:
        raise
    except Exception as exc:
        raise BrowserExtractionError(f"browser extraction failed: {exc}") from exc

    if not candidates:
        raise BrowserExtractionError("no media requests were observed during browser playback")

    return _choose_best_candidate(candidates)


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
                video.muted = true;
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
    if content_type.startswith(("video/", "audio/")):
        return BrowserMediaCandidate(url=url, kind="direct", title=title, request_headers=request_headers, content_length=content_length)
    if lower_url.endswith((".mp4", ".m4a", ".mp3", ".webm", ".mkv", ".aac")):
        return BrowserMediaCandidate(url=url, kind="direct", title=title, request_headers=request_headers, content_length=content_length)
    return None


def _choose_best_candidate(candidates: list[BrowserMediaCandidate]) -> BrowserMediaCandidate:
    rank = {"hls": 3, "dash": 2, "direct": 1}
    return max(candidates, key=lambda item: (rank.get(item.kind, 0), item.content_length))


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
