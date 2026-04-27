import unittest

from vdnld.manifest.m3u8 import parse_m3u8


class ParseM3U8Tests(unittest.TestCase):
    def test_parse_master_playlist_selects_best_variant(self) -> None:
        text = """#EXTM3U
#EXT-X-STREAM-INF:BANDWIDTH=800000,RESOLUTION=640x360
low/index.m3u8
#EXT-X-STREAM-INF:BANDWIDTH=2400000,RESOLUTION=1280x720
mid/index.m3u8
"""
        playlist = parse_m3u8(text, base_url="https://example.com/master.m3u8")

        self.assertEqual(playlist.kind, "master")
        self.assertEqual(len(playlist.variants), 2)
        self.assertIsNotNone(playlist.best_variant())
        self.assertEqual(
            playlist.best_variant().uri,
            "https://example.com/mid/index.m3u8",
        )

    def test_select_variant_by_quality(self) -> None:
        text = """#EXTM3U
#EXT-X-STREAM-INF:BANDWIDTH=800000,RESOLUTION=640x360
low/index.m3u8
#EXT-X-STREAM-INF:BANDWIDTH=2400000,RESOLUTION=1280x720
mid/index.m3u8
#EXT-X-STREAM-INF:BANDWIDTH=5000000,RESOLUTION=1920x1080
high/index.m3u8
"""
        playlist = parse_m3u8(text, base_url="https://example.com/master.m3u8")

        self.assertEqual(
            playlist.select_variant("lowest").uri,
            "https://example.com/low/index.m3u8",
        )
        self.assertEqual(
            playlist.select_variant("720p").uri,
            "https://example.com/mid/index.m3u8",
        )
        self.assertEqual(
            playlist.select_variant("1280x720").uri,
            "https://example.com/mid/index.m3u8",
        )
        self.assertIsNone(playlist.select_variant("not-a-quality"))

    def test_parse_media_playlist_collects_segments(self) -> None:
        text = """#EXTM3U
#EXTINF:4.0,
seg-1.ts
#EXTINF:5.5,
seg-2.ts
"""
        playlist = parse_m3u8(text, base_url="https://cdn.example.com/path/playlist.m3u8")

        self.assertEqual(playlist.kind, "media")
        self.assertEqual(
            [segment.uri for segment in playlist.segments],
            [
                "https://cdn.example.com/path/seg-1.ts",
                "https://cdn.example.com/path/seg-2.ts",
            ],
        )


if __name__ == "__main__":
    unittest.main()
