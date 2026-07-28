import unittest
from pathlib import Path
from unittest.mock import patch

from vdnld.app import run
from vdnld.dependencies import DependencyError
from vdnld.download.manager import DownloadPlan, plan_download
from vdnld.extractors.browser import BrowserChallengeError, BrowserExtractionError, BrowserMediaCandidate
from vdnld.net.http import FetchError, HttpTextResponse


class PlanDownloadTests(unittest.TestCase):
    def test_plan_download_detects_hls_master(self) -> None:
        def fake_fetch(url: str) -> HttpTextResponse:
            return HttpTextResponse(
                url=url,
                content_type="application/vnd.apple.mpegurl",
                text="""#EXTM3U
#EXT-X-STREAM-INF:BANDWIDTH=1000
small.m3u8
#EXT-X-STREAM-INF:BANDWIDTH=5000
large.m3u8
""",
            )

        plan = plan_download("https://example.com/master.m3u8", output=None, fetcher=fake_fetch)

        self.assertEqual(plan.strategy, "hls_master")
        self.assertEqual(plan.extractor, "hls")
        self.assertEqual(plan.selected_url, "https://example.com/large.m3u8")
        self.assertTrue(plan.executable)

    def test_plan_download_detects_magnet_links(self) -> None:
        plan = plan_download(
            "magnet:?xt=urn:btih:abc",
            output="downloads/torrents",
            fetcher=lambda url: (_ for _ in ()).throw(AssertionError("fetch should not run")),
        )

        self.assertEqual(plan.strategy, "torrent")
        self.assertEqual(plan.extractor, "torrent")
        self.assertEqual(plan.selected_url, "magnet:?xt=urn:btih:abc")
        self.assertTrue(plan.executable)

    def test_plan_download_detects_torrent_files(self) -> None:
        plan = plan_download(
            "https://example.com/file.torrent",
            output=None,
            fetcher=lambda url: (_ for _ in ()).throw(AssertionError("fetch should not run")),
        )

        self.assertEqual(plan.strategy, "torrent")
        self.assertEqual(plan.extractor, "torrent")
        self.assertTrue(plan.executable)

    def test_plan_download_can_select_hls_quality(self) -> None:
        def fake_fetch(url: str) -> HttpTextResponse:
            return HttpTextResponse(
                url=url,
                content_type="application/vnd.apple.mpegurl",
                text="""#EXTM3U
#EXT-X-STREAM-INF:BANDWIDTH=1000,RESOLUTION=640x360
small.m3u8
#EXT-X-STREAM-INF:BANDWIDTH=5000,RESOLUTION=1920x1080
large.m3u8
""",
            )

        plan = plan_download(
            "https://example.com/master.m3u8",
            output=None,
            fetcher=fake_fetch,
            quality="360p",
        )

        self.assertEqual(plan.strategy, "hls_master")
        self.assertEqual(plan.selected_url, "https://example.com/small.m3u8")
        self.assertIn("selected quality 360p", plan.notes)

    def test_plan_download_falls_back_to_direct(self) -> None:
        def fake_fetch(url: str) -> HttpTextResponse:
            return HttpTextResponse(
                url=url,
                content_type="video/mp4",
                text="not a manifest",
            )

        plan = plan_download("https://example.com/video.mp4", output="out.mp4", fetcher=fake_fetch)

        self.assertEqual(plan.strategy, "direct")
        self.assertEqual(plan.extractor, "generic")
        self.assertEqual(plan.selected_url, "https://example.com/video.mp4")
        self.assertTrue(plan.executable)

    def test_plan_download_reports_probe_failures(self) -> None:
        def fake_fetch(url: str) -> HttpTextResponse:
            raise FetchError("boom")

        plan = plan_download("https://example.com/video", output=None, fetcher=fake_fetch)

        self.assertEqual(plan.strategy, "probe_failed")
        self.assertEqual(plan.notes, "boom")
        self.assertFalse(plan.executable)

    def test_plan_download_preserves_site_specific_extractors(self) -> None:
        plan = plan_download(
            "https://www.youtube.com/watch?v=test",
            output=None,
            fetcher=lambda url: (_ for _ in ()).throw(FetchError("boom")),
            browser_fallback=False,
        )

        self.assertEqual(plan.strategy, "site")
        self.assertEqual(plan.extractor, "youtube")
        self.assertFalse(plan.executable)

    def test_plan_download_uses_youtube_bootstrap_data(self) -> None:
        def fake_fetch(url: str) -> HttpTextResponse:
            return HttpTextResponse(
                url=url,
                content_type="text/html",
                text="""
                <script>
                ytInitialPlayerResponse = {
                  "streamingData": {
                    "formats": [{"qualityLabel": "360p", "url": "https://cdn.example.com/video.mp4"}],
                    "adaptiveFormats": []
                  }
                };
                </script>
                """,
            )

        plan = plan_download("https://www.youtube.com/watch?v=test", output=None, fetcher=fake_fetch)

        self.assertEqual(plan.strategy, "youtube_direct")
        self.assertEqual(plan.selected_url, "https://cdn.example.com/video.mp4")
        self.assertTrue(plan.executable)

    def test_plan_download_does_not_execute_html_pages(self) -> None:
        def fake_fetch(url: str) -> HttpTextResponse:
            return HttpTextResponse(
                url=url,
                content_type="text/html",
                text="<html></html>",
            )

        plan = plan_download("https://example.com/page", output=None, fetcher=fake_fetch)

        self.assertEqual(plan.strategy, "direct")
        self.assertFalse(plan.executable)

    def test_plan_download_can_use_browser_for_site_url(self) -> None:
        def fake_browser(url: str) -> BrowserMediaCandidate:
            return BrowserMediaCandidate(
                url="https://cdn.example.com/master.m3u8",
                kind="hls",
            )

        def fake_fetch(url: str) -> HttpTextResponse:
            return HttpTextResponse(
                url=url,
                content_type="application/vnd.apple.mpegurl",
                text="""#EXTM3U
#EXT-X-STREAM-INF:BANDWIDTH=1000
small.m3u8
#EXT-X-STREAM-INF:BANDWIDTH=5000
large.m3u8
""",
            )

        plan = plan_download(
            "https://www.youtube.com/watch?v=test",
            output=None,
            fetcher=fake_fetch,
            browser_probe=fake_browser,
        )

        self.assertEqual(plan.strategy, "hls_master")
        self.assertEqual(plan.extractor, "hls")
        self.assertTrue(plan.executable)
        self.assertIn("extracted via browser", plan.notes)

    def test_plan_download_uses_browser_headers_for_hls_manifest_fetch(self) -> None:
        def fake_browser(url: str) -> BrowserMediaCandidate:
            return BrowserMediaCandidate(
                url="https://cdn.example.com/master.m3u8",
                kind="hls",
                request_headers={
                    "referer": "https://protected.example/page",
                    "user-agent": "Mozilla/5.0",
                },
            )

        def fake_fetch(url: str) -> HttpTextResponse:
            raise FetchError(f"unexpected plain fetch for {url}")

        def fake_fetch_with_headers(
            url: str,
            headers: dict[str, str] | None = None,
            timeout: float = 20.0,
        ) -> HttpTextResponse:
            self.assertEqual(headers["referer"], "https://protected.example/page")
            if url == "https://cdn.example.com/master.m3u8":
                return HttpTextResponse(
                    url=url,
                    content_type="application/vnd.apple.mpegurl",
                    text="""#EXTM3U
#EXT-X-STREAM-INF:BANDWIDTH=1000
small.m3u8
#EXT-X-STREAM-INF:BANDWIDTH=5000
large.m3u8
""",
                )
            if url == "https://cdn.example.com/large.m3u8":
                return HttpTextResponse(
                    url=url,
                    content_type="application/vnd.apple.mpegurl",
                    text="""#EXTM3U
#EXTINF:5.0,
seg-1.ts
#EXTINF:5.0,
seg-2.ts
""",
                )
            raise AssertionError(f"unexpected URL {url}")

        with patch("vdnld.download.manager.fetch_text_with_headers", side_effect=fake_fetch_with_headers):
            plan = plan_download(
                "https://protected.example/video-page",
                output=None,
                fetcher=fake_fetch,
                browser_probe=fake_browser,
            )

        self.assertEqual(plan.strategy, "hls_master")
        self.assertEqual(plan.selected_url, "https://cdn.example.com/large.m3u8")
        self.assertEqual(plan.request_headers["referer"], "https://protected.example/page")
        self.assertEqual(plan.duration_seconds, 10.0)

    def test_plan_download_can_fall_back_to_browser_direct(self) -> None:
        def fake_fetch(url: str) -> HttpTextResponse:
            return HttpTextResponse(url=url, content_type="text/html", text="<html></html>")

        def fake_browser(url: str) -> BrowserMediaCandidate:
            return BrowserMediaCandidate(
                url="https://cdn.example.com/video.mp4",
                kind="direct",
            )

        plan = plan_download(
            "https://example.com/page",
            output=None,
            fetcher=fake_fetch,
            browser_probe=fake_browser,
        )

        self.assertEqual(plan.strategy, "browser_direct")
        self.assertEqual(plan.extractor, "browser")
        self.assertTrue(plan.executable)

    def test_plan_download_can_fall_back_to_browser_direct_video_audio_mux(self) -> None:
        def fake_fetch(url: str) -> HttpTextResponse:
            return HttpTextResponse(url=url, content_type="text/html", text="<html></html>")

        def fake_browser(url: str) -> BrowserMediaCandidate:
            return BrowserMediaCandidate(
                url="https://cdn.example.com/video.m4s",
                kind="direct",
                media_type="video",
                request_headers={
                    "referer": "https://protected.example/page",
                    "user-agent": "Mozilla/5.0",
                },
                audio_url="https://cdn.example.com/audio.m4s",
                audio_request_headers={
                    "referer": "https://protected.example/page",
                    "user-agent": "Mozilla/5.0",
                },
            )

        plan = plan_download(
            "https://example.com/page",
            output=None,
            fetcher=fake_fetch,
            browser_probe=fake_browser,
        )

        self.assertEqual(plan.strategy, "browser_direct_mux")
        self.assertEqual(plan.extractor, "browser")
        self.assertEqual(plan.selected_url, "https://cdn.example.com/video.m4s")
        self.assertEqual(plan.audio_url, "https://cdn.example.com/audio.m4s")
        self.assertEqual(plan.audio_request_headers["referer"], "https://protected.example/page")
        self.assertTrue(plan.needs_merge)
        self.assertTrue(plan.executable)

    def test_plan_download_can_fall_back_to_browser_audio_only(self) -> None:
        def fake_fetch(url: str) -> HttpTextResponse:
            return HttpTextResponse(url=url, content_type="text/html", text="<html></html>")

        def fake_browser(url: str, *, quality: str | None = None, audio_only: bool = False) -> BrowserMediaCandidate:
            self.assertTrue(audio_only)
            return BrowserMediaCandidate(
                url="https://cdn.example.com/audio.m4a",
                kind="direct",
                media_type="audio",
                duration_seconds=8575.0,
                request_headers={
                    "referer": "https://protected.example/page",
                    "user-agent": "Mozilla/5.0",
                },
            )

        plan = plan_download(
            "https://example.com/page",
            output=None,
            fetcher=fake_fetch,
            browser_probe=fake_browser,
            audio_only=True,
        )

        self.assertEqual(plan.strategy, "browser_direct")
        self.assertEqual(plan.extractor, "browser")
        self.assertEqual(plan.selected_url, "https://cdn.example.com/audio.m4a")
        self.assertEqual(plan.request_headers["referer"], "https://protected.example/page")
        self.assertEqual(plan.duration_seconds, 8575.0)
        self.assertTrue(plan.audio_only)
        self.assertFalse(plan.needs_merge)
        self.assertTrue(plan.executable)

    def test_plan_download_ignores_browser_failure(self) -> None:
        def fake_browser(url: str) -> BrowserMediaCandidate:
            raise BrowserExtractionError("missing playwright")

        plan = plan_download(
            "https://www.youtube.com/watch?v=test",
            output=None,
            browser_probe=fake_browser,
        )

        self.assertEqual(plan.strategy, "site")

    def test_plan_download_reports_challenge_page(self) -> None:
        def fake_fetch(url: str) -> HttpTextResponse:
            return HttpTextResponse(url=url, content_type="text/html", text="<html></html>")

        def fake_browser(url: str) -> BrowserMediaCandidate:
            raise BrowserChallengeError("site protection challenge detected")

        plan = plan_download(
            "https://example.com/protected",
            output=None,
            fetcher=fake_fetch,
            browser_probe=fake_browser,
        )

        self.assertEqual(plan.strategy, "challenge_detected")
        self.assertFalse(plan.executable)
        self.assertIn("challenge", plan.notes)

    def test_run_raises_when_ffmpeg_is_missing(self) -> None:
        with patch("vdnld.app.require_ffmpeg", side_effect=DependencyError("missing")):
            with patch("vdnld.app.plan_download") as plan_download_mock:
                plan_download_mock.return_value = plan_download(
                    "https://example.com/video.mp4",
                    output=None,
                    fetcher=lambda url: HttpTextResponse(
                        url=url,
                        content_type="video/mp4",
                        text="binary",
                    ),
                    browser_fallback=False,
                )
                with self.assertRaises(DependencyError):
                    run("https://example.com/video.mp4", output=None)

    def test_run_can_skip_ffmpeg_requirement(self) -> None:
        with patch("vdnld.app.require_ffmpeg", side_effect=DependencyError("missing")):
            run("https://www.youtube.com/watch?v=test", output=None, ffmpeg_required=False)

    def test_run_torrent_requires_aria2c_instead_of_ffmpeg(self) -> None:
        with patch("vdnld.app.require_ffmpeg", side_effect=DependencyError("missing")) as require_ffmpeg_mock:
            with patch("vdnld.app.require_aria2c", return_value="/usr/bin/aria2c") as require_aria2c_mock:
                with patch("vdnld.app.execute_plan") as execute_plan_mock:
                    run("magnet:?xt=urn:btih:abc", output="downloads/torrents")

        require_ffmpeg_mock.assert_not_called()
        require_aria2c_mock.assert_called_once_with()
        execute_plan_mock.assert_called_once()

    def test_run_plan_only_does_not_require_ffmpeg(self) -> None:
        with patch("vdnld.app.require_ffmpeg", side_effect=DependencyError("missing")):
            run("https://www.youtube.com/watch?v=test", output=None, plan_only=True)

    def test_run_clear_cache_does_not_require_ffmpeg(self) -> None:
        with patch("vdnld.app.require_ffmpeg", side_effect=DependencyError("missing")):
            with patch("vdnld.app.clear_plan_cache", return_value=("output.mp4", False)):
                run("https://www.youtube.com/watch?v=test", output=None, clear_cache=True)

    def test_run_can_enable_browser_fallback(self) -> None:
        with patch("vdnld.app.require_ffmpeg", return_value="/usr/bin/ffmpeg"):
            with patch("vdnld.app.plan_download") as plan_download_mock:
                plan_download_mock.return_value = plan_download(
                    "https://www.youtube.com/watch?v=test",
                    output=None,
                    browser_fallback=False,
                )
                run(
                    "https://www.youtube.com/watch?v=test",
                    output=None,
                    browser_fallback=True,
                )
        self.assertTrue(plan_download_mock.call_args.kwargs["browser_fallback"])

    def test_run_can_enable_interactive_browser(self) -> None:
        with patch("vdnld.app.require_ffmpeg", return_value="/usr/bin/ffmpeg"):
            with patch("vdnld.app.plan_download") as plan_download_mock:
                plan_download_mock.return_value = plan_download(
                    "https://www.youtube.com/watch?v=test",
                    output=None,
                    browser_fallback=False,
                )
                run(
                    "https://www.youtube.com/watch?v=test",
                    output=None,
                    interactive_browser=True,
                )
        self.assertTrue(plan_download_mock.call_args.kwargs["browser_fallback"])
        self.assertEqual(
            plan_download_mock.call_args.kwargs["browser_probe"].__name__,
            "interactive_capture_media_requests",
        )

    def test_run_plan_only_skips_execution(self) -> None:
        with patch("vdnld.app.require_ffmpeg", return_value="/usr/bin/ffmpeg"):
            with patch("vdnld.app.execute_plan") as execute_plan_mock:
                run(
                    "https://www.youtube.com/watch?v=test",
                    output=None,
                    ffmpeg_required=True,
                    plan_only=True,
                )
        execute_plan_mock.assert_not_called()

    def test_run_transcribes_after_successful_download(self) -> None:
        with patch("vdnld.app.require_ffmpeg", return_value="/usr/bin/ffmpeg") as require_ffmpeg_mock:
            with patch("vdnld.app.require_whisper", return_value="/usr/bin/whisper") as require_whisper_mock:
                with patch("vdnld.app.plan_download") as plan_download_mock:
                    plan_download_mock.return_value = DownloadPlan(
                        url="https://example.com/video.mp4",
                        output=None,
                        extractor="generic",
                        strategy="direct",
                        needs_merge=False,
                        selected_url="https://example.com/video.mp4",
                        executable=True,
                    )
                    with patch("vdnld.app.execute_plan", return_value=Path("downloads/video.mp4")):
                        with patch("vdnld.app.transcribe_media", return_value=[Path("downloads/video.txt")]) as transcribe_mock:
                            run(
                                "https://example.com/video.mp4",
                                output=None,
                                transcribe=True,
                                whisper_model="small",
                                whisper_language="English",
                                transcript_format="txt",
                                transcript_output="downloads",
                            )

        require_ffmpeg_mock.assert_called_once_with()
        require_whisper_mock.assert_called_once_with()
        transcribe_mock.assert_called_once_with(
            Path("downloads/video.mp4"),
            output_dir=Path("downloads"),
            model="small",
            language="English",
            output_format="txt",
        )

    def test_run_plan_only_does_not_require_whisper(self) -> None:
        with patch("vdnld.app.require_whisper") as require_whisper_mock:
            run(
                "https://www.youtube.com/watch?v=test",
                output=None,
                transcribe=True,
                plan_only=True,
            )

        require_whisper_mock.assert_not_called()

    def test_run_can_clear_cache_and_skip_execution(self) -> None:
        with patch("vdnld.app.clear_plan_cache", return_value=("output.mp4", True)) as clear_cache_mock:
            with patch("vdnld.app.execute_plan") as execute_plan_mock:
                run(
                    "https://www.youtube.com/watch?v=test",
                    output=None,
                    clear_cache=True,
                )
        clear_cache_mock.assert_called_once()
        execute_plan_mock.assert_not_called()


if __name__ == "__main__":
    unittest.main()
