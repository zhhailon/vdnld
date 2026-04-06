"""Download cache helpers."""

from __future__ import annotations

import shutil
from pathlib import Path


def cache_dir_for_output(output_path: Path) -> Path:
    return output_path.with_name(f".{output_path.stem}.vdnld")


def clear_download_cache(output_path: Path) -> bool:
    cache_dir = cache_dir_for_output(output_path)
    if not cache_dir.exists():
        return False
    shutil.rmtree(cache_dir)
    return True
