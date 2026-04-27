"""CLI entrypoint for vdnld."""

from __future__ import annotations

import argparse

from vdnld.app import run


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="vdnld",
        description="Download and merge media from a URL.",
    )
    parser.add_argument(
        "url",
        nargs="?",
        help="Source page or media URL to inspect and download.",
    )
    parser.add_argument(
        "-o",
        "--output",
        help="Target output path for the downloaded media.",
    )
    parser.add_argument(
        "-q",
        "--quality",
        help="HLS quality to select from master playlists: highest, lowest, 720p, or 1280x720. Defaults to highest.",
    )
    parser.add_argument(
        "--browser",
        action="store_true",
        help="Allow Playwright browser fallback when static probing is insufficient.",
    )
    parser.add_argument(
        "--interactive-browser",
        action="store_true",
        help="Open a visible browser and wait for manual interaction before resuming in the CLI.",
    )
    parser.add_argument(
        "--plan-only",
        action="store_true",
        help="Only extract and print the download plan without starting ffmpeg.",
    )
    parser.add_argument(
        "--no-resume",
        action="store_true",
        help="Ignore existing partial download cache and start fresh for this target.",
    )
    parser.add_argument(
        "--clear-cache",
        action="store_true",
        help="Clear the local download cache for this target and exit.",
    )
    parser.add_argument(
        "--tor",
        action="store_true",
        help="Route all traffic through the local Tor SOCKS5 proxy (127.0.0.1:9150 for Tor Browser, 9050 for tor daemon). Requires PySocks: pip install 'vdnld[tor]'.",
    )
    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    if not args.url:
        parser.print_help()
        return

    run(
        url=args.url,
        output=args.output,
        quality=args.quality,
        browser_fallback=args.browser,
        interactive_browser=args.interactive_browser,
        plan_only=args.plan_only,
        resume=not args.no_resume,
        clear_cache=args.clear_cache,
        tor=args.tor,
    )
