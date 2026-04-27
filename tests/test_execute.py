import unittest
import tempfile
from pathlib import Path
from unittest.mock import patch

from vdnld.download.execute import (
    _render_progress_line,
    derive_output_basename,
    DownloadExecutionError,
    build_ffmpeg_command,
    clear_plan_cache,
    default_suffix_for_plan,
    execute_plan,
    parse_ffmpeg_status_line,
    partial_output_path,
    resolve_output_path,
    strip_site_suffix,
)
from vdnld.download.manager import DownloadPlan
from vdnld.download.cache import cache_dir_for_output


class ExecutePlanTests(unittest.TestCase):
    def test_build_ffmpeg_command(self) -> None:
        command = build_ffmpeg_command(
            source_url="https://example.com/master.m3u8",
            output_path=Path("video.mp4"),
        )
        self.assertEqual(
            command,
            ["ffmpeg", "-y", "-i", "https://example.com/master.m3u8", "-c", "copy", "video.mp4"],
        )

    def test_build_ffmpeg_command_includes_headers(self) -> None:
        command = build_ffmpeg_command(
            source_url="https://example.com/master.m3u8",
            output_path=Path("video.mp4"),
            request_headers={"referer": "https://example.com", "user-agent": "vdnld-test"},
        )
        self.assertIn("-headers", command)
        header_blob = command[command.index("-headers") + 1]
        self.assertIn("referer: https://example.com", header_blob)
        self.assertIn("user-agent: vdnld-test", header_blob)

    def test_build_ffmpeg_command_allows_nonstandard_extensions_for_local_hls(self) -> None:
        command = build_ffmpeg_command(
            source_url=".video.vdnld/playlist.m3u8",
            output_path=Path("video.mp4"),
            local_hls=True,
        )
        self.assertIn("-allowed_extensions", command)
        self.assertEqual(command[command.index("-allowed_extensions") + 1], "ALL")
        self.assertIn("-protocol_whitelist", command)

    def test_build_ffmpeg_command_does_not_use_hls_options_for_local_direct_input(self) -> None:
        command = build_ffmpeg_command(
            source_url=".video.vdnld/source.mp4",
            output_path=Path("video.mp4"),
            local_input=True,
        )
        self.assertNotIn("-allowed_extensions", command)
        self.assertNotIn("-protocol_whitelist", command)

    def test_resolve_output_path_uses_explicit_output(self) -> None:
        plan = DownloadPlan(
            url="https://example.com/v.m3u8",
            output="custom.mp4",
            extractor="hls",
            strategy="hls_media",
            needs_merge=False,
        )
        self.assertEqual(resolve_output_path(plan), Path("custom.mp4"))

    def test_default_suffix_for_hls(self) -> None:
        plan = DownloadPlan(
            url="https://example.com/v.m3u8",
            output=None,
            extractor="hls",
            strategy="hls_media",
            needs_merge=False,
        )
        self.assertEqual(default_suffix_for_plan(plan), ".mp4")

    def test_derive_output_basename_prefers_title(self) -> None:
        plan = DownloadPlan(
            url="https://example.com/v.m3u8",
            output=None,
            extractor="hls",
            strategy="hls_media",
            needs_merge=False,
            title='My Great Video: Episode 1',
        )
        self.assertEqual(derive_output_basename(plan), "My Great Video_ Episode 1")

    def test_strip_site_suffix(self) -> None:
        self.assertEqual(strip_site_suffix("Example Title - YouTube"), "Example Title")
        self.assertEqual(strip_site_suffix("Example Title | MISSAV"), "Example Title")

    def test_partial_output_path_preserves_media_extension(self) -> None:
        self.assertEqual(partial_output_path(Path("output.mp4")), Path("output.part.mp4"))

    def test_execute_plan_rejects_unsupported_strategy(self) -> None:
        plan = DownloadPlan(
            url="https://youtube.com/watch?v=test",
            output=None,
            extractor="youtube",
            strategy="site",
            needs_merge=True,
            notes="site-specific extractor required",
            executable=False,
        )
        with self.assertRaises(DownloadExecutionError):
            execute_plan(plan)

    def test_execute_plan_runs_ffmpeg_for_supported_strategy(self) -> None:
        plan = DownloadPlan(
            url="https://example.com/video.mp4",
            output=None,
            extractor="generic",
            strategy="direct",
            needs_merge=False,
            title=None,
            selected_url="https://example.com/video.mp4",
            executable=True,
        )
        with patch("vdnld.download.execute.run_direct_download") as run_direct:
            output_path = execute_plan(plan)
        self.assertEqual(output_path, Path("video.mp4"))
        run_direct.assert_called_once_with(
            source_url="https://example.com/video.mp4",
            output_path=Path("video.mp4"),
            request_headers=None,
            duration_seconds=None,
            resume=True,
        )

    def test_execute_plan_routes_hls_to_resumable_downloader(self) -> None:
        plan = DownloadPlan(
            url="https://example.com/master.m3u8",
            output=None,
            extractor="hls",
            strategy="hls_master",
            needs_merge=False,
            title=None,
            selected_url="https://example.com/high.m3u8",
            executable=True,
        )
        with patch("vdnld.download.execute.run_hls_download") as run_hls:
            output_path = execute_plan(plan)
        self.assertEqual(output_path, Path("high.mp4"))
        run_hls.assert_called_once_with(
            source_url="https://example.com/high.m3u8",
            output_path=Path("high.mp4"),
            request_headers=None,
            duration_seconds=None,
            resume=True,
        )

    def test_execute_plan_passes_resume_flag_to_direct_download(self) -> None:
        plan = DownloadPlan(
            url="https://example.com/video.mp4",
            output=None,
            extractor="generic",
            strategy="direct",
            needs_merge=False,
            selected_url="https://example.com/video.mp4",
            executable=True,
        )
        with patch("vdnld.download.execute.run_direct_download") as run_direct:
            execute_plan(plan, resume=False)
        run_direct.assert_called_once_with(
            source_url="https://example.com/video.mp4",
            output_path=Path("video.mp4"),
            request_headers=None,
            duration_seconds=None,
            resume=False,
        )

    def test_run_direct_download_clears_cache_after_successful_mux(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            output_path = Path(tmp) / "video.mp4"
            cache_dir = cache_dir_for_output(output_path)
            cache_dir.mkdir(parents=True)
            (cache_dir / "source.mp4").write_bytes(b"data")

            with patch("vdnld.download.execute.download_direct_media", return_value=cache_dir / "source.mp4"):
                with patch("vdnld.download.execute.run_ffmpeg_copy"):
                    from vdnld.download.execute import run_direct_download

                    run_direct_download("https://example.com/video.mp4", output_path)

            self.assertFalse(cache_dir.exists())

    def test_run_hls_download_clears_cache_after_successful_mux(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            output_path = Path(tmp) / "video.mp4"
            cache_dir = cache_dir_for_output(output_path)
            cache_dir.mkdir(parents=True)
            playlist_path = cache_dir / "playlist.m3u8"
            playlist_path.write_text("#EXTM3U\n", encoding="utf-8")

            with patch("vdnld.download.execute.download_hls_media_playlist", return_value=playlist_path):
                with patch("vdnld.download.execute.run_ffmpeg_copy"):
                    from vdnld.download.execute import run_hls_download

                    run_hls_download("https://example.com/master.m3u8", output_path)

            self.assertFalse(cache_dir.exists())

    def test_clear_plan_cache_returns_target_and_status(self) -> None:
        plan = DownloadPlan(
            url="https://example.com/video.mp4",
            output="custom.mp4",
            extractor="generic",
            strategy="direct",
            needs_merge=False,
        )
        with patch("vdnld.download.execute.clear_download_cache", return_value=True) as clear_cache:
            target, cleared = clear_plan_cache(plan)
        self.assertEqual(target, Path("custom.mp4"))
        self.assertTrue(cleared)
        clear_cache.assert_called_once_with(Path("custom.mp4"))

    def test_parse_ffmpeg_status_line(self) -> None:
        parsed = parse_ffmpeg_status_line(
            "frame=  240 fps=0.0 q=-1.0 size=    1024kB time=00:00:10.00 bitrate= 838.9kbits/s speed=1.0x"
        )
        self.assertIsNotNone(parsed)
        self.assertIn("00:00:10", parsed)
        self.assertIn("1.0x", parsed)

    def test_parse_ffmpeg_status_line_with_duration_renders_progress(self) -> None:
        parsed = parse_ffmpeg_status_line(
            "frame=  240 fps=0.0 q=-1.0 size=    1024kB time=00:00:10.00 bitrate= 838.9kbits/s speed=1.0x",
            duration_seconds=20.0,
        )
        self.assertIsNotNone(parsed)
        self.assertIn("progress:  50%", parsed)
        self.assertIn("00:00:10/00:00:20", parsed)
        self.assertIn("1.0x", parsed)

    def test_render_progress_line_uses_carriage_return(self) -> None:
        with patch("vdnld.download.execute.sys.stdout.write") as write_mock:
            with patch("vdnld.download.execute.sys.stdout.flush"):
                _render_progress_line("progress:  50% [############--------]")
        write_mock.assert_called_once_with("\rprogress:  50% [############--------]")


if __name__ == "__main__":
    unittest.main()
