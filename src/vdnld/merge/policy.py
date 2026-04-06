"""Merge decision rules."""

from __future__ import annotations


def needs_media_merge(extractor: str) -> bool:
    return extractor in {"youtube", "vimeo", "generic"}
