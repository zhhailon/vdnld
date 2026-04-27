"""Small HLS manifest parser used for planning."""

from __future__ import annotations

from dataclasses import dataclass, field
from urllib.parse import urljoin


@dataclass(slots=True)
class M3U8Variant:
    uri: str
    bandwidth: int | None = None
    resolution: str | None = None


@dataclass(slots=True)
class M3U8Segment:
    uri: str
    duration: float | None = None


@dataclass(slots=True)
class M3U8Playlist:
    kind: str
    variants: list[M3U8Variant] = field(default_factory=list)
    segments: list[M3U8Segment] = field(default_factory=list)

    def best_variant(self) -> M3U8Variant | None:
        if not self.variants:
            return None
        return max(self.variants, key=lambda item: item.bandwidth or -1)

    def select_variant(self, quality: str | None = None) -> M3U8Variant | None:
        if not self.variants:
            return None

        normalized = (quality or "highest").strip().lower()
        if normalized in {"highest", "best", "max"}:
            return self.best_variant()
        if normalized in {"lowest", "worst", "min"}:
            return min(self.variants, key=lambda item: item.bandwidth or float("inf"))

        height = _parse_quality_height(normalized)
        if height is not None:
            return _select_variant_by_height(self.variants, height)

        if "x" in normalized:
            exact = [variant for variant in self.variants if (variant.resolution or "").lower() == normalized]
            if exact:
                return max(exact, key=lambda item: item.bandwidth or -1)

        return None


def parse_m3u8(text: str, base_url: str) -> M3U8Playlist:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    variants: list[M3U8Variant] = []
    segments: list[M3U8Segment] = []
    pending_stream_inf: dict[str, str] | None = None
    pending_duration: float | None = None

    for line in lines:
        if line.startswith("#EXT-X-STREAM-INF:"):
            pending_stream_inf = _parse_attribute_list(line.partition(":")[2])
            continue

        if line.startswith("#EXTINF:"):
            raw_duration = line.partition(":")[2].split(",", 1)[0].strip()
            pending_duration = float(raw_duration) if raw_duration else None
            continue

        if line.startswith("#"):
            continue

        absolute_uri = urljoin(base_url, line)
        if pending_stream_inf is not None:
            variants.append(
                M3U8Variant(
                    uri=absolute_uri,
                    bandwidth=_parse_int(pending_stream_inf.get("BANDWIDTH")),
                    resolution=pending_stream_inf.get("RESOLUTION"),
                )
            )
            pending_stream_inf = None
            continue

        segments.append(M3U8Segment(uri=absolute_uri, duration=pending_duration))
        pending_duration = None

    kind = "master" if variants else "media"
    return M3U8Playlist(kind=kind, variants=variants, segments=segments)


def _parse_attribute_list(text: str) -> dict[str, str]:
    attributes: dict[str, str] = {}
    for chunk in text.split(","):
        key, _, value = chunk.partition("=")
        if not key:
            continue
        attributes[key.strip()] = value.strip().strip('"')
    return attributes


def _parse_int(value: str | None) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except ValueError:
        return None


def _parse_quality_height(value: str) -> int | None:
    if value.endswith("p"):
        return _parse_int(value[:-1])
    if "x" in value:
        _, _, raw_height = value.partition("x")
        return _parse_int(raw_height)
    return None


def _variant_height(variant: M3U8Variant) -> int | None:
    if not variant.resolution or "x" not in variant.resolution:
        return None
    _, _, raw_height = variant.resolution.lower().partition("x")
    return _parse_int(raw_height)


def _select_variant_by_height(variants: list[M3U8Variant], target_height: int) -> M3U8Variant | None:
    with_heights = [(variant, _variant_height(variant)) for variant in variants]
    with_heights = [(variant, height) for variant, height in with_heights if height is not None]
    if not with_heights:
        return None

    exact_or_lower = [(variant, height) for variant, height in with_heights if height <= target_height]
    if exact_or_lower:
        return max(
            exact_or_lower,
            key=lambda item: (item[1], item[0].bandwidth or -1),
        )[0]

    return min(
        with_heights,
        key=lambda item: (item[1], -(item[0].bandwidth or -1)),
    )[0]
