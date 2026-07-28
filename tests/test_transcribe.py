import unittest
from pathlib import Path
from unittest.mock import patch

from vdnld.transcribe import (
    TranscriptionError,
    build_whisper_command,
    transcribe_media,
    transcript_paths,
)


class TranscribeTests(unittest.TestCase):
    def test_build_whisper_command_defaults_to_media_directory(self) -> None:
        command = build_whisper_command(Path("downloads/video.mp4"))

        self.assertEqual(
            command,
            [
                "whisper",
                "downloads/video.mp4",
                "--output_dir",
                "downloads",
                "--output_format",
                "txt",
            ],
        )

    def test_build_whisper_command_includes_model_language_and_format(self) -> None:
        command = build_whisper_command(
            Path("downloads/audio.m4a"),
            output_dir=Path("transcripts"),
            model="small",
            language="Chinese",
            output_format="srt",
        )

        self.assertEqual(
            command,
            [
                "whisper",
                "downloads/audio.m4a",
                "--output_dir",
                "transcripts",
                "--output_format",
                "srt",
                "--model",
                "small",
                "--language",
                "Chinese",
            ],
        )

    def test_build_whisper_command_rejects_unknown_format(self) -> None:
        with self.assertRaises(TranscriptionError):
            build_whisper_command(Path("downloads/video.mp4"), output_format="docx")

    def test_transcript_paths_returns_all_known_outputs(self) -> None:
        self.assertEqual(
            transcript_paths(Path("downloads/video.mp4"), output_format="all"),
            [
                Path("downloads/video.txt"),
                Path("downloads/video.srt"),
                Path("downloads/video.vtt"),
                Path("downloads/video.json"),
                Path("downloads/video.tsv"),
            ],
        )

    def test_transcribe_media_runs_whisper_and_returns_transcript_path(self) -> None:
        with patch("vdnld.transcribe.subprocess.run") as run_mock:
            paths = transcribe_media(
                Path("downloads/video.mp4"),
                output_dir=Path("transcripts"),
                model="base",
            )

        run_mock.assert_called_once_with(
            [
                "whisper",
                "downloads/video.mp4",
                "--output_dir",
                "transcripts",
                "--output_format",
                "txt",
                "--model",
                "base",
            ],
            check=True,
        )
        self.assertEqual(paths, [Path("transcripts/video.txt")])


if __name__ == "__main__":
    unittest.main()
