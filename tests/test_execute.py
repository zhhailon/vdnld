import unittest
import tempfile
from pathlib import Path
from unittest.mock import patch

from vdnld.download.execute import (
    _render_progress_line,
    derive_output_basename,
    DownloadExecutionError,
    build_aria2c_command,
    build_ffmpeg_command,
    build_ffmpeg_mux_command,
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

    def test_build_ffmpeg_command_can_extract_audio_only(self) -> None:
        command = build_ffmpeg_command(
            source_url=".video.vdnld/source.mp4",
            output_path=Path("audio.m4a"),
            local_input=True,
            audio_only=True,
        )
        self.assertIn("-vn", command)
        self.assertIn("-c:a", command)
        self.assertNotIn("-c", command)

    def test_build_ffmpeg_mux_command_maps_video_and_audio(self) -> None:
        command = build_ffmpeg_mux_command(
            video_source=".video.vdnld/source.m4s",
            audio_source=".audio.vdnld/source.m4s",
            output_path=Path("video.mp4"),
        )
        self.assertEqual(
            command,
            [
                "ffmpeg",
                "-y",
                "-i",
                ".video.vdnld/source.m4s",
                "-i",
                ".audio.vdnld/source.m4s",
                "-map",
                "0:v:0",
                "-map",
                "1:a:0",
                "-c",
                "copy",
                "video.mp4",
            ],
        )

    def test_build_aria2c_command_downloads_to_directory(self) -> None:
        command = build_aria2c_command(
            source_url="magnet:?xt=urn:btih:abc",
            output_dir=Path("downloads"),
        )
        self.assertEqual(
            command,
            [
                "aria2c",
                "--continue=true",
                "--seed-time=0",
                "--summary-interval=5",
                "--dir",
                "downloads",
                "magnet:?xt=urn:btih:abc",
            ],
        )

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

    def test_resolve_output_path_defaults_media_to_downloads_directory(self) -> None:
        plan = DownloadPlan(
            url="https://example.com/video.mp4",
            output=None,
            extractor="generic",
            strategy="direct",
            needs_merge=False,
            selected_url="https://example.com/video.mp4",
            executable=True,
        )
        self.assertEqual(resolve_output_path(plan), Path("downloads/video.mp4"))

    def test_resolve_output_path_defaults_audio_only_media_to_m4a(self) -> None:
        plan = DownloadPlan(
            url="https://example.com/video.mp4",
            output=None,
            extractor="generic",
            strategy="direct",
            needs_merge=False,
            selected_url="https://example.com/video.mp4",
            executable=True,
            audio_only=True,
        )
        self.assertEqual(resolve_output_path(plan), Path("downloads/video.m4a"))

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
        self.assertEqual(output_path, Path("downloads/video.mp4"))
        run_direct.assert_called_once_with(
            source_url="https://example.com/video.mp4",
            output_path=Path("downloads/video.mp4"),
            request_headers=None,
            duration_seconds=None,
            resume=True,
            audio_only=False,
        )

    def test_execute_plan_routes_browser_audio_only_to_remote_ffmpeg(self) -> None:
        plan = DownloadPlan(
            url="https://example.com/page",
            output=None,
            extractor="browser",
            strategy="browser_direct",
            needs_merge=False,
            title="Browser Audio",
            selected_url="https://cdn.example.com/audio.m4s",
            executable=True,
            request_headers={"referer": "https://example.com/page"},
            duration_seconds=8575.0,
            audio_only=True,
        )
        with patch("vdnld.download.execute.run_direct_download") as run_direct:
            with patch("vdnld.download.execute.run_ffmpeg_copy") as run_ffmpeg:
                output_path = execute_plan(plan)

        self.assertEqual(output_path, Path("downloads/Browser Audio.m4a"))
        run_direct.assert_not_called()
        run_ffmpeg.assert_called_once_with(
            source_url="https://cdn.example.com/audio.m4s",
            output_path=Path("downloads/Browser Audio.m4a"),
            request_headers={"referer": "https://example.com/page"},
            duration_seconds=8575.0,
            audio_only=True,
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
        self.assertEqual(output_path, Path("downloads/high.mp4"))
        run_hls.assert_called_once_with(
            source_url="https://example.com/high.m3u8",
            output_path=Path("downloads/high.mp4"),
            request_headers=None,
            duration_seconds=None,
            resume=True,
            audio_only=False,
        )

    def test_execute_plan_routes_browser_direct_mux_to_video_audio_downloader(self) -> None:
        plan = DownloadPlan(
            url="https://example.com/page",
            output="video.mp4",
            extractor="browser",
            strategy="browser_direct_mux",
            needs_merge=True,
            selected_url="https://cdn.example.com/video.m4s",
            audio_url="https://cdn.example.com/audio.m4s",
            request_headers={"referer": "https://example.com/video"},
            audio_request_headers={"referer": "https://example.com/audio"},
            executable=True,
        )
        with patch("vdnld.download.execute.run_direct_mux_download") as run_mux:
            output_path = execute_plan(plan)
        self.assertEqual(output_path, Path("video.mp4"))
        run_mux.assert_called_once_with(
            video_url="https://cdn.example.com/video.m4s",
            audio_url="https://cdn.example.com/audio.m4s",
            output_path=Path("video.mp4"),
            video_request_headers={"referer": "https://example.com/video"},
            audio_request_headers={"referer": "https://example.com/audio"},
            duration_seconds=None,
            resume=True,
        )

    def test_execute_plan_routes_torrent_to_aria2c(self) -> None:
        plan = DownloadPlan(
            url="magnet:?xt=urn:btih:abc",
            output="downloads/torrents",
            extractor="torrent",
            strategy="torrent",
            needs_merge=False,
            selected_url="magnet:?xt=urn:btih:abc",
            executable=True,
        )
        with patch("vdnld.download.execute.run_aria2c_download") as run_aria2c:
            output_path = execute_plan(plan, resume=False)
        self.assertEqual(output_path, Path("downloads/torrents"))
        run_aria2c.assert_called_once_with(
            source_url="magnet:?xt=urn:btih:abc",
            output_dir=Path("downloads/torrents"),
            resume=False,
        )

    def test_resolve_output_path_defaults_torrent_to_downloads_directory(self) -> None:
        plan = DownloadPlan(
            url="magnet:?xt=urn:btih:abc",
            output=None,
            extractor="torrent",
            strategy="torrent",
            needs_merge=False,
            executable=True,
        )
        self.assertEqual(resolve_output_path(plan), Path("downloads"))

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
            output_path=Path("downloads/video.mp4"),
            request_headers=None,
            duration_seconds=None,
            resume=False,
            audio_only=False,
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
