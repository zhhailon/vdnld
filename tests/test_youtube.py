import unittest

from vdnld.extractors.youtube import extract_youtube_media


class YouTubeExtractorTests(unittest.TestCase):
    def test_extracts_progressive_format_url(self) -> None:
        html = """
        <html><script>
        var ytInitialPlayerResponse = {
          "videoDetails": {"title": "Example"},
          "streamingData": {
            "formats": [
              {"qualityLabel": "360p", "url": "https://cdn.example.com/360.mp4"},
              {"qualityLabel": "720p", "url": "https://cdn.example.com/720.mp4"}
            ],
            "adaptiveFormats": []
          }
        };
        </script></html>
        """
        extraction = extract_youtube_media(html)
        self.assertEqual(extraction.url, "https://cdn.example.com/720.mp4")
        self.assertEqual(extraction.title, "Example")
        self.assertEqual(extraction.source, "progressive_format")

    def test_extracts_hls_manifest_when_present(self) -> None:
        html = """
        <script>
        ytInitialPlayerResponse = {
          "streamingData": {
            "formats": [],
            "adaptiveFormats": [],
            "hlsManifestUrl": "https://cdn.example.com/master.m3u8"
          }
        };
        </script>
        """
        extraction = extract_youtube_media(html)
        self.assertEqual(extraction.url, "https://cdn.example.com/master.m3u8")
        self.assertEqual(extraction.source, "hls_manifest")


if __name__ == "__main__":
    unittest.main()
