import unittest

from vdnld.extractors.browser import (
    BrowserChallengeError,
    BrowserMediaCandidate,
    _candidate_from_response,
    _choose_best_candidate,
    _page_title,
    _raise_if_challenge_page,
)


class BrowserExtractorTests(unittest.TestCase):
    def test_candidate_from_response_detects_hls(self) -> None:
        candidate = _candidate_from_response(
            "https://cdn.example.com/master.m3u8",
            "application/vnd.apple.mpegurl",
            {"referer": "https://example.com"},
            title="Example Title - MISSAV",
        )
        self.assertIsNotNone(candidate)
        self.assertEqual(candidate.kind, "hls")
        self.assertEqual(candidate.request_headers["referer"], "https://example.com")
        self.assertEqual(candidate.title, "Example Title - MISSAV")

    def test_candidate_from_response_detects_direct_media(self) -> None:
        candidate = _candidate_from_response(
            "https://cdn.example.com/video.mp4",
            "video/mp4",
        )
        self.assertIsNotNone(candidate)
        self.assertEqual(candidate.kind, "direct")

    def test_choose_best_candidate_prefers_hls(self) -> None:
        best = _choose_best_candidate(
            [
                BrowserMediaCandidate(url="https://example.com/video.mp4", kind="direct"),
                BrowserMediaCandidate(url="https://example.com/master.m3u8", kind="hls"),
            ]
        )
        self.assertEqual(best.kind, "hls")

    def test_choose_best_candidate_pairs_direct_video_and_audio(self) -> None:
        best = _choose_best_candidate(
            [
                BrowserMediaCandidate(
                    url="https://example.com/video.m4s",
                    kind="direct",
                    media_type="video",
                    content_length=10_000,
                    request_headers={"referer": "https://example.com/video"},
                ),
                BrowserMediaCandidate(
                    url="https://example.com/audio.m4s",
                    kind="direct",
                    media_type="audio",
                    content_length=2_000,
                    request_headers={"referer": "https://example.com/audio"},
                ),
            ]
        )

        self.assertEqual(best.url, "https://example.com/video.m4s")
        self.assertEqual(best.audio_url, "https://example.com/audio.m4s")
        self.assertEqual(best.audio_request_headers["referer"], "https://example.com/audio")

    def test_choose_best_candidate_honors_lowest_quality_for_direct_video(self) -> None:
        best = _choose_best_candidate(
            [
                BrowserMediaCandidate(
                    url="https://example.com/high.m4s",
                    kind="direct",
                    media_type="video",
                    content_length=2_000_000,
                    height=1080,
                ),
                BrowserMediaCandidate(
                    url="https://example.com/low.m4s",
                    kind="direct",
                    media_type="video",
                    content_length=500_000,
                    height=360,
                ),
                BrowserMediaCandidate(
                    url="https://example.com/audio.m4s",
                    kind="direct",
                    media_type="audio",
                    content_length=200_000,
                ),
            ],
            quality="lowest",
        )

        self.assertEqual(best.url, "https://example.com/low.m4s")
        self.assertEqual(best.audio_url, "https://example.com/audio.m4s")

    def test_raise_if_challenge_page_detects_cloudflare(self) -> None:
        class FakePage:
            def title(self) -> str:
                return "Just a moment..."

            def content(self) -> str:
                return "<html>cf-chl cloudflare</html>"

        with self.assertRaises(BrowserChallengeError):
            _raise_if_challenge_page(FakePage())

    def test_page_title_returns_none_when_navigation_interrupts_lookup(self) -> None:
        class FakePage:
            def title(self) -> str:
                raise RuntimeError("Execution context was destroyed")

        self.assertIsNone(_page_title(FakePage()))


if __name__ == "__main__":
    unittest.main()
