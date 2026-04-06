"""HTTP helpers for lightweight probing."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


class FetchError(RuntimeError):
    """Raised when a probe request fails."""


@dataclass(slots=True)
class HttpTextResponse:
    url: str
    content_type: str
    text: str


FetchText = Callable[[str], HttpTextResponse]


def fetch_text(url: str, timeout: float = 20.0) -> HttpTextResponse:
    return fetch_text_with_headers(
        url,
        headers={
            "User-Agent": "vdnld/0.1.0",
            "Accept": "*/*",
        },
        timeout=timeout,
    )


def fetch_text_with_headers(
    url: str,
    headers: dict[str, str] | None = None,
    timeout: float = 20.0,
) -> HttpTextResponse:
    request = Request(
        url,
        headers=headers or {},
    )
    try:
        with urlopen(request, timeout=timeout) as response:
            raw = response.read()
            content_type = response.headers.get_content_type()
            charset = response.headers.get_content_charset() or "utf-8"
            return HttpTextResponse(
                url=response.geturl(),
                content_type=content_type,
                text=raw.decode(charset, errors="replace"),
            )
    except HTTPError as exc:
        raise FetchError(f"http error {exc.code} for {url}") from exc
    except URLError as exc:
        raise FetchError(f"network error for {url}: {exc.reason}") from exc
