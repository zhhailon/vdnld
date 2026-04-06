# Repository Guidelines

## Project Structure & Module Organization
This project studies Video DownloadHelper’s packaged extension builds and extracts reusable harnesses for `vdnld`, a Python downloader that should expose a CLI and automatically download and merge media streams from a URL. Use `uv` as the project and package manager.

- `downloads/`: downloaded release artifacts, including the Chrome `.crx` and Firefox `.xpi`.
- `unpack/chrome/`: unpacked Chrome extension build used for analysis.
- `unpack/firefox/`: unpacked Firefox extension build used for analysis.
- `AGENTS.md`: contributor guidance for analysis and follow-on implementation work.

Within each unpacked build:

- `manifest.json`: extension entrypoint and permissions.
- `service/`: background/service worker bundle.
- `content/`: popup, sidebar, settings, and history UI assets.
- `injected/`: site-specific content scripts.
- `download_worker/`: media processing worker and bundled WASM.
- `bitmaps/` and `_locales/`: images and translations.

## Build, Test, and Development Commands
There is no native Python project checked into this workspace yet. Treat files under `unpack/` as generated release output and use them as reference material, not primary source.

- `file downloads/*`: identify package formats.
- `rg --files unpack/chrome unpack/firefox`: inspect available files quickly.
- `rg -n "download_worker|BroadcastChannel|service/main" unpack/chrome unpack/firefox`: trace architecture and message flow.
- `python3 -m http.server`: optionally serve unpacked assets for static inspection.
- `uv init`: create the Python project scaffold when implementation begins.
- `uv run <command>`: run project entrypoints and scripts inside the managed environment.

Avoid reformatting or bulk-rewriting minified bundles unless the task explicitly requires it. New `vdnld` code should live outside `unpack/` once implementation begins.

## Coding Style & Naming Conventions
Preserve the shipped structure and naming:

- Keep browser-specific changes isolated to `unpack/chrome/` or `unpack/firefox/`.
- Follow existing file groupings such as `content/*.js`, `injected/*.js`, and `service/main.js` when documenting or extracting behavior.
- For new Python code, prefer clear package names such as `vdnld/cli.py`, `vdnld/extractors/`, `vdnld/merge/`, and `vdnld/harness/`.
- Use 2-space indentation in Markdown and JSON edits when practical; do not reindent minified JavaScript.
- Use Python conventions: 4-space indentation, `snake_case` for modules/functions, `PascalCase` for classes, and type hints on public interfaces.
- Prefer small, surgical edits. When porting logic, rewrite into readable Python rather than copying minified bundles directly.

## Testing Guidelines
No automated test suite is present yet. Validate analysis changes manually:

- Check `manifest.json` for permission or entrypoint changes.
- Load the unpacked extension in Chrome or Firefox and verify popup/sidebar behavior.
- Re-test affected site integrations when editing `injected/` scripts.
- Confirm media workflows still initialize when editing `service/` or `download_worker/`.

For future `vdnld` code, add deterministic tests around URL parsing, playlist extraction, segment download, and merge orchestration. Run them with `uv run pytest` once the Python project exists.

## Commit & Pull Request Guidelines
This directory is not currently a Git repository, so no local commit history is available. If it is moved into version control:

- Use short imperative commit subjects, for example `Map download worker message flow` or `Add Python CLI merge harness`.
- Keep commits scoped to one analysis area or one `vdnld` feature.
- In pull requests, include a summary, affected paths, manual verification steps, and note whether work is analysis-only or production code.
- Call out explicitly when behavior is inferred from bundled artifacts rather than proven from original source.
