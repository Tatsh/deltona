<!-- markdownlint-configure-file {"MD024": { "siblings_only": true } } -->

# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.1/), and this project
adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [unreleased]

### Fixed

- `remove-trailing-commas` no longer strips the required comma from single-element tuple unpacks on
  the left-hand side of an assignment (for example `(count,) = cursor.fetchone()`), which would
  silently change the assignment's semantics.

## [0.2.0] - 2026-04-25

### Added

- `pair_redtiger_dashcam_files()` and `group_pairs()` public utility functions for
  timestamp-proximity pairing of front/rear dashcam files.
- `max_offset` parameter on `media.archive_dashcam_footage` (default 1 second) for controlling
  front/rear file pairing tolerance.
- `--max-offset` CLI option on `encode-dashcam`.
- `parse_timestamp()` public utility function.
- Chapter markers in `encode-dashcam` output; each clip pair becomes a chapter named after the front
  file stem. Disable with `--no-chapters`.
- `duration` field to `FormatDict` and `StreamsDict` typed dictionaries.
- `anyio`, `async-lru`, and `pytest-asyncio` dependencies.
- `merge-dependabot-prs` CLI options:
  - `--concurrency` (default `os.cpu_count() or 1`) to cap repositories processed in parallel.
  - `-M` / `--max-concurrent-http-requests` (default `3`) to cap simultaneous in-flight HTTP
    requests.
  - `-r` / `--repo` (repeatable) to limit processing to specific repositories. Each value may be
    a bare `NAME` (resolved against the authenticated user) or a fully qualified `OWNER/NAME`.
- `repos` parameter on `merge_dependabot_pull_requests` mirroring the `--repo` CLI option.
- `DependabotMergeError` raised by `merge_dependabot_pull_requests` when any pull request fails to
  merge. Carries a `remaining` mapping of repository full name to the count of unmerged pull
  requests.
- `merge-dependabot-prs` now prints the repositories with unmerged Dependabot pull requests, and
  the count of pull requests for each, before sleeping between retry attempts.
- New `remove-trailing-commas` CLI command that walks files or directories and removes non-required
  trailing commas from Python source. Options:
  - `--no-format` to skip running `yarn format` and `yarn ruff:fix` after editing.
  - `--no-gitignore` to disable `.gitignore` filtering when walking directories.
  - `--no-dot` to skip files and directories starting with `.`.
- New `deltona.refactor` library module with public functions `find_removable_trailing_commas` and
  `remove_trailing_commas`.
- New public async function `refactor.remove_trailing_commas_in_paths` that walks files and
  directories, parses each as Python, removes non-required trailing commas using non-blocking I/O,
  and returns a mapping of modified paths to their original content.
- `# rtc-off` and `# rtc-on` in-source directives to skip a block of code from comma removal.
- `pathspec` base dependency for `.gitignore` matching.
- `tomlkit` base dependency for reading `pyproject.toml` and Ruff configuration files.

### Changed

- Replaced `requests` dependency with `niquests`, a drop-in replacement with HTTP/2, HTTP/3, and
  built-in type annotations.
- `CD_FRAMES` constant moved from `deltona.media` to `deltona.utils` to decouple CDDA utilities from
  media disc-ID internals.
- `media.archive_dashcam_footage` now uses timestamp-proximity pairing instead of positional file
  matching.
- Unmatched dashcam files are now logged and skipped instead of being deleted.
- Chapter durations are derived from source file duration with the setpts factor applied.
- Improved NVENC quality defaults: `-cq 25` (was 29), added `-rc vbr`, `-temporal_aq 1`,
  `-b_ref_mode middle`.
- CLI defaults for `encode-dashcam` now match intended NVENC usage: `hevc_nvenc` encoder, `p7`
  preset, `20M` max bitrate.
- Renamed `pair_dashcam_files` to `pair_redtiger_dashcam_files` to clarify Red Tiger specificity.
- `media.archive_dashcam_footage` now accepts `pair_fn` and `group_fn` parameters for custom
  pairing and grouping logic.
- `media.archive_dashcam_footage` `rear_dir` parameter is now optional (`None` for single-camera
  mode). When `rear_dir` is `None` or `pair_fn` is `None`, front files are encoded without overlay.
- `group_pairs` now accepts `Sequence` instead of `list` for the `pairs` parameter.
- `encode-dashcam` CLI: `rear_dir` argument is now optional.
- All HTTP-calling functions converted from synchronous to async using `niquests.AsyncSession`.
  Affected modules: `deltona.adp`, `deltona.chromium`, `deltona.media`, `deltona.www`.
- Click commands that make HTTP requests now use `asyncio.run()` to invoke async implementations.
- `check_bookmarks_html_urls` now checks URLs concurrently using anyio task groups.
- `@cache` on async functions replaced with `@alru_cache` from async-lru.
- File I/O in async functions uses anyio for non-blocking access.
- `merge_dependabot_pull_requests` now lists repositories with `get_repos(sort='full_name')`
  instead of filtering by `affiliation='owner'`.
- `merge_dependabot_pull_requests` is now async and processes repositories concurrently with
  bounded HTTP and task concurrency.
- `merge_dependabot_pull_requests` now lists repositories with `visibility='all'`, ensuring private
  repositories are included.
- `remove-trailing-commas` now picks up exclude patterns from `pyproject.toml`
  (`tool.yapfignore.ignore_patterns`, `tool.ruff.exclude`, `tool.ruff.extend-exclude`,
  `tool.ruff.format.exclude`) and from `ruff.toml` / `.ruff.toml` (`exclude`, `extend-exclude`,
  `format.exclude`) when `--no-format` is not passed.
- `remove-trailing-commas` directory walker now prunes excluded directories during traversal
  instead of post-filtering, so large directories such as `.venv` and `node_modules` are skipped
  without descending.
- `remove-trailing-commas` suppresses `yarn format` and `yarn ruff:fix` output by default; pass
  `--debug` (`-d`) to show the output and to emit debug logs tracing how the ignore pattern set is
  built up.

### Removed

- `get_cd_disc_id()` and all CD-ROM ioctl/ctypes support code from `deltona.media`.
- `-a`/`--affiliation` option from `merge-dependabot-prs` and the `affiliation` argument from
  `merge_dependabot_pull_requests`.
- `requests` and `types-requests` dependencies in favour of `niquests` (fully typed).
- `requests-mock` test dependency; tests now use standard `mocker.patch`.
- `allow_group_discrepancy_resolution` parameter from `media.archive_dashcam_footage`.
- `--no-fix-groups` CLI option from `encode-dashcam`.

### Fixed

- Click option default mismatches in `encode_dashcam_main` for `preset`, `video_encoder`, and
  `video_max_bitrate`.
- `encode-dashcam` `click.Path` constraints now correctly use `file_okay=False` for directory
  arguments.
- `encode-dashcam` `--temp-dir` option now uses `click.Path` type.

## [0.1.4] - 2026-03-21

### Changed

- All extras groups now work correctly; optional dependencies are lazily imported so modules load
  without installing every group.
- `keyring` and `send2trash` moved from core dependencies to extras (`git`, `media`, `www`).

## [0.1.3] - 2026-03-21

### Changed

- Moved optional dependencies to extras (`admin`, `desktop`, `git`, `media`, `string`, `wine`,
  `www`). Install with e.g. `pip install deltona[media]`.

## [0.1.2] - 2026-03-21

Minor release for testing the release process.

## [0.1.1] - 2026-03-21

### Changed

- Restored Python 3.10 compatibility; `requires-python` lowered to `>=3.10`.

## [0.1.0] - 2026-03-20

### Added

- Added top-level `deltona` CLI that wraps all commands as subcommands.
- Added `kconfig-to-json` and `deltona.system.kconfig_to_dict`.
- Added `cssq`.
- `adp`: added `-d`/`--debug` flag for debug logging.
- Exported `InvalidExec` from `deltona.ultraiso` as part of the public API.

### Changed

- `deltona` CLI now hides commands that are unavailable on the current platform (Linux-only commands
  hidden on macOS/Windows, Windows-incompatible commands hidden on Windows).
- `windows`: set `DEFAULT_DPI` to 96 (was 72).
- `kconfig_to_commands` boolean check is no longer case-sensitive.
- Narrowed `pydbus` and `pygobject` platform markers from non-Windows to Linux-only (bluez is
  Linux-specific).

### Fixed

- `netloc` subcommand now works correctly when invoked as `deltona netloc` (previously only worked
  as a standalone script).
- Fixed `kconfig-to-commands` not outputting the `--file` argument for non-default files.
- `connect-g603`: import `Gio` late (fix for when `gi` is not installed especially on non-Linux).
- `merge-dependabot-prs`: post `@dependabot recreate` consistently and do not repost it if the last
  comment is the same.

### Removed

- Moved `mkwineprefix` to its own package `mkwineprefix`.
- Moved `ripcd` to its own package `ripcd`.
- Moved `flacted` to its own package `flacted`.

## [0.0.3] - 2025-06-08

### Added

- `media.archive_dashcam_footage`
  - Added `container` parameter (defaults to `matroska`). Must match extension.
  - Added `extension` parameter (defaults to `'mkv'`).
  - Added `keep_audio` parameter (defaults to `False`).

### Changed

- `encode-dashcam`
  - Set default `--video-max-bitrate` to `'30M'`.
  - Set default encoder to `'libx265'`.
- `media.archive_dashcam_footage`
  - Set default `video_encoder` to `'libx265'`.

## [0.0.2] - 2025-06-07

### Added

- `encode-dashcam`
  - Added `-crf` option.
  - Added `--no-delete` option.
- `media.archive_dashcam_footage`
  - Added `crf` parameter for software encoders.

### Fixed

- `media.archive_dashcam_footage` was completely broken due to path issue.

### Changed

- `encode-dashcam`
  - Set default level to `'auto'` (NVENC HEVC).
- `media.archive_dashcam_footage`
  - Now accepts `Pattern[str]` for the `match_re` parameter.
  - Improved handling of encoder-specific arguments.
  - Added `no_delete` parameter.

## [0.0.1] - 2025-05-31

First version. `check_bookmarks_html_urls` may have unresolved issues.

[unreleased]: https://github.com/Tatsh/deltona/compare/v0.1.4...HEAD
[0.1.4]: https://github.com/Tatsh/deltona/compare/v0.1.3...v0.1.4
[0.1.3]: https://github.com/Tatsh/deltona/compare/v0.1.2...v0.1.3
[0.1.2]: https://github.com/Tatsh/deltona/compare/v0.1.1...v0.1.2
[0.1.1]: https://github.com/Tatsh/deltona/compare/v0.1.0...v0.1.1
[0.1.0]: https://github.com/Tatsh/deltona/compare/v0.0.3...v0.1.0
[0.0.3]: https://github.com/Tatsh/deltona/compare/v0.0.2...v0.0.3
[0.0.2]: https://github.com/Tatsh/deltona/compare/v0.0.1...v0.0.2
[0.0.1]: https://github.com/Tatsh/deltona/releases/tag/v0.0.1
