import tempfile
import unittest
from pathlib import Path

from vdnld.download.hls import (
    download_hls_media_playlist,
    hls_state_dir,
    render_hls_progress,
    write_local_playlist,
)
from vdnld.net.http import HttpTextResponse


class HlsDownloadTests(unittest.TestCase):
    def test_hls_state_dir_uses_hidden_sibling_directory(self) -> None:
        self.assertEqual(hls_state_dir(Path("video.mp4")), Path(".video.vdnld"))

    def test_write_local_playlist_references_local_segments(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            playlist_path = Path(tmp) / "playlist.m3u8"
            write_local_playlist(
                playlist_path,
                [
                    (5.0, "segments/00000.ts"),
                    (6.5, "segments/00001.ts"),
                ],
            )
            text = playlist_path.read_text(encoding="utf-8")
        self.assertIn("#EXTM3U", text)
        self.assertIn("#EXTINF:5.000000,", text)
        self.assertIn("segments/00001.ts", text)
        self.assertIn("#EXT-X-ENDLIST", text)

    def test_download_hls_media_playlist_skips_cached_segments(self) -> None:
        responses = {
            "https://example.com/media.m3u8": HttpTextResponse(
                url="https://example.com/media.m3u8",
                content_type="application/vnd.apple.mpegurl",
                text="""#EXTM3U
#EXTINF:5.0,
seg0.ts
#EXTINF:6.0,
seg1.ts
""",
            )
        }

        def fake_fetch(url: str) -> HttpTextResponse:
            return responses[url]

        downloads: list[str] = []

        def fake_download(url: str, destination: Path, *, request_headers=None) -> None:
            downloads.append(url)
            destination.write_bytes(b"segment")

        progress_updates: list[str] = []

        with tempfile.TemporaryDirectory() as tmp:
            output_path = Path(tmp) / "video.mp4"
            segments_dir = hls_state_dir(output_path) / "segments"
            segments_dir.mkdir(parents=True, exist_ok=True)
            (segments_dir / "00000.ts").write_bytes(b"cached")

            from unittest.mock import patch

            with patch("vdnld.download.hls._download_segment", side_effect=fake_download):
                playlist_path = download_hls_media_playlist(
                    "https://example.com/media.m3u8",
                    output_path,
                    fetcher=fake_fetch,
                    progress_callback=progress_updates.append,
                )

            self.assertEqual(downloads, ["https://example.com/seg1.ts"])
            self.assertTrue(playlist_path.exists())
            self.assertTrue((segments_dir / "00001.ts").exists())
            self.assertTrue(any("resume" in item for item in progress_updates))

    def test_render_hls_progress_includes_percent_and_duration(self) -> None:
        rendered = render_hls_progress(
            current=2,
            total=4,
            completed_duration=10.0,
            total_duration=20.0,
            phase="download",
            bytes_per_second=1_572_864,
        )
        self.assertIn("50%", rendered)
        self.assertIn("2/4", rendered)
        self.assertIn("00:00:10/00:00:20", rendered)
        self.assertIn("1.5MB/s", rendered)

    def test_download_hls_media_playlist_can_disable_resume(self) -> None:
        responses = {
            "https://example.com/media.m3u8": HttpTextResponse(
                url="https://example.com/media.m3u8",
                content_type="application/vnd.apple.mpegurl",
                text="""#EXTM3U
#EXTINF:5.0,
seg0.ts
""",
            )
        }

        def fake_fetch(url: str) -> HttpTextResponse:
            return responses[url]

        downloads: list[str] = []

        def fake_download(url: str, destination: Path, *, request_headers=None) -> None:
            downloads.append(url)
            destination.write_bytes(b"fresh")

        with tempfile.TemporaryDirectory() as tmp:
            output_path = Path(tmp) / "video.mp4"
            segments_dir = hls_state_dir(output_path) / "segments"
            segments_dir.mkdir(parents=True, exist_ok=True)
            (segments_dir / "00000.ts").write_bytes(b"cached")

            from unittest.mock import patch

            with patch("vdnld.download.hls._download_segment", side_effect=fake_download):
                playlist_path = download_hls_media_playlist(
                    "https://example.com/media.m3u8",
                    output_path,
                    fetcher=fake_fetch,
                    resume=False,
                )

            self.assertEqual(downloads, ["https://example.com/seg0.ts"])
            self.assertEqual((segments_dir / "00000.ts").read_bytes(), b"fresh")
            self.assertTrue(playlist_path.exists())

    def test_download_hls_media_playlist_selects_master_quality(self) -> None:
        responses = {
            "https://example.com/master.m3u8": HttpTextResponse(
                url="https://example.com/master.m3u8",
                content_type="application/vnd.apple.mpegurl",
                text="""#EXTM3U
#EXT-X-STREAM-INF:BANDWIDTH=1000,RESOLUTION=640x360
small.m3u8
#EXT-X-STREAM-INF:BANDWIDTH=5000,RESOLUTION=1920x1080
large.m3u8
""",
            ),
            "https://example.com/small.m3u8": HttpTextResponse(
                url="https://example.com/small.m3u8",
                content_type="application/vnd.apple.mpegurl",
                text="""#EXTM3U
#EXTINF:5.0,
seg0.ts
""",
            ),
        }

        def fake_fetch(url: str) -> HttpTextResponse:
            return responses[url]

        downloads: list[str] = []

        def fake_download(url: str, destination: Path, *, request_headers=None) -> None:
            downloads.append(url)
            destination.write_bytes(b"segment")

        with tempfile.TemporaryDirectory() as tmp:
            output_path = Path(tmp) / "video.mp4"

            from unittest.mock import patch

            with patch("vdnld.download.hls._download_segment", side_effect=fake_download):
                playlist_path = download_hls_media_playlist(
                    "https://example.com/master.m3u8",
                    output_path,
                    fetcher=fake_fetch,
                    quality="360p",
                )

            self.assertEqual(downloads, ["https://example.com/seg0.ts"])
            self.assertTrue(playlist_path.exists())


if __name__ == "__main__":
    unittest.main()
