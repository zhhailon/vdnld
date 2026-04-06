import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from vdnld.download.direct import (
    direct_cache_path,
    direct_state_dir,
    download_direct_media,
    render_direct_progress,
)


class _FakeResponse:
    def __init__(self, chunks: list[bytes], headers: dict[str, str], status: int) -> None:
        self._chunks = list(chunks)
        self.headers = headers
        self.status = status

    def read(self, size: int = -1) -> bytes:
        if not self._chunks:
            return b""
        return self._chunks.pop(0)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        return None


class DirectDownloadTests(unittest.TestCase):
    def test_direct_state_dir_uses_hidden_sibling_directory(self) -> None:
        self.assertEqual(direct_state_dir(Path("video.mp4")), Path(".video.vdnld"))

    def test_direct_cache_path_uses_source_suffix(self) -> None:
        self.assertEqual(
            direct_cache_path("https://example.com/video.webm", Path("output.mp4")),
            Path(".output.vdnld/source.webm"),
        )

    def test_download_direct_media_resumes_from_partial_file(self) -> None:
        requests = []

        def fake_urlopen(request, timeout=30.0):
            requests.append(request)
            return _FakeResponse(
                [b"56789"],
                {"Content-Range": "bytes 5-9/10", "Content-Length": "5"},
                206,
            )

        progress_updates: list[str] = []
        with tempfile.TemporaryDirectory() as tmp:
            output_path = Path(tmp) / "video.mp4"
            cache_path = direct_cache_path("https://example.com/video.mp4", output_path)
            cache_path.parent.mkdir(parents=True, exist_ok=True)
            cache_path.write_bytes(b"01234")

            with patch("vdnld.download.direct.urlopen", side_effect=fake_urlopen):
                local_path = download_direct_media(
                    "https://example.com/video.mp4",
                    output_path,
                    progress_callback=progress_updates.append,
                )

            self.assertEqual(local_path.read_bytes(), b"0123456789")
            self.assertEqual(requests[0].headers["Range"], "bytes=5-")
            self.assertTrue(any("100%" in item for item in progress_updates))

    def test_download_direct_media_can_disable_resume(self) -> None:
        requests = []

        def fake_urlopen(request, timeout=30.0):
            requests.append(request)
            return _FakeResponse(
                [b"abc"],
                {"Content-Length": "3"},
                200,
            )

        with tempfile.TemporaryDirectory() as tmp:
            output_path = Path(tmp) / "video.mp4"
            cache_path = direct_cache_path("https://example.com/video.mp4", output_path)
            cache_path.parent.mkdir(parents=True, exist_ok=True)
            cache_path.write_bytes(b"old-data")

            with patch("vdnld.download.direct.urlopen", side_effect=fake_urlopen):
                local_path = download_direct_media(
                    "https://example.com/video.mp4",
                    output_path,
                    resume=False,
                )

            self.assertEqual(local_path.read_bytes(), b"abc")
            self.assertNotIn("Range", requests[0].headers)

    def test_render_direct_progress_includes_percent_when_total_known(self) -> None:
        rendered = render_direct_progress(5, 10, bytes_per_second=2048)
        self.assertIn("50%", rendered)
        self.assertIn("5B/10B", rendered)
        self.assertIn("2.0KB/s", rendered)


if __name__ == "__main__":
    unittest.main()
