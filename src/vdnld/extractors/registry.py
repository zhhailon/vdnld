"""Map URLs to extraction strategies."""

from __future__ import annotations

from urllib.parse import urlparse


def choose_extractor(url: str) -> str:
    host = urlparse(url).netloc.lower()
    if "youtube.com" in host or "youtu.be" in host:
        return "youtube"
    if "vimeo.com" in host:
        return "vimeo"
    if host:
        return "generic"
    return "unknown"
