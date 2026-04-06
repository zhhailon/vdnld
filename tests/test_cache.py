import tempfile
import unittest
from pathlib import Path

from vdnld.download.cache import cache_dir_for_output, clear_download_cache


class CacheTests(unittest.TestCase):
    def test_cache_dir_for_output_uses_hidden_sibling_directory(self) -> None:
        self.assertEqual(cache_dir_for_output(Path("video.mp4")), Path(".video.vdnld"))

    def test_clear_download_cache_removes_existing_directory(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            output_path = Path(tmp) / "video.mp4"
            cache_dir = cache_dir_for_output(output_path)
            cache_dir.mkdir(parents=True)
            (cache_dir / "marker.txt").write_text("x", encoding="utf-8")

            cleared = clear_download_cache(output_path)

            self.assertTrue(cleared)
            self.assertFalse(cache_dir.exists())

    def test_clear_download_cache_returns_false_when_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            output_path = Path(tmp) / "video.mp4"
            self.assertFalse(clear_download_cache(output_path))


if __name__ == "__main__":
    unittest.main()
