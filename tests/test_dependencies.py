import unittest
from unittest.mock import patch

from vdnld.dependencies import DependencyError, find_ffmpeg, require_ffmpeg


class DependencyTests(unittest.TestCase):
    def test_find_ffmpeg_returns_binary_when_available(self) -> None:
        with patch("vdnld.dependencies.which", return_value="/usr/bin/ffmpeg"):
            self.assertEqual(find_ffmpeg(), "/usr/bin/ffmpeg")

    def test_require_ffmpeg_raises_when_missing(self) -> None:
        with patch("vdnld.dependencies.which", return_value=None):
            with self.assertRaises(DependencyError):
                require_ffmpeg()


if __name__ == "__main__":
    unittest.main()
