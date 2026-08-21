<!-- markdownlint-configure-file {"MD024": { "siblings_only": true } } -->

# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.1/), and this project
adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [unreleased]

## [0.3.0] - 2026-08-21

### Added

- `retry-gh-jobs` to run failed GitHub Actions jobs again where the failure was not the code's
  fault. Only the jobs that failed are restarted. A failure qualifies only when both the name of
  the failing step and the text of the job's log match the same rule, because a step name on its
  own is too coarse: `Install dependencies` covers a rate limit, a stale lockfile, and a build
  failure, and only the first is worth another run. The rules cover a Coveralls server error, a
  package source refusing a request, and python-appimage hitting an anonymous API rate limit.
  Dependabot update runs are never restarted; they are recreated with `@dependabot recreate`
  instead. Options: `-b`/`--base-url` for enterprise, `-c`/`--concurrency` to cap repositories
  examined in parallel, `-n`/`--dry-run` to report without starting anything, `-m`/`--max-attempts`
  to leave a run alone once it has been attempted that many times, `-r`/`--repo` (repeatable) to
  limit the repositories examined, `-s`/`--since` to bound how far back runs are considered
  (defaults to a day ago), and `-u`/`--username` for the keyring lookup.
- `deltona.actions` module with `find_retryable_runs` and `rerun_failed_jobs`, the `RetryRule` and
  `RetryCandidate` named tuples, and the `RETRY_RULES` and `NEVER_RETRY_EVENTS` constants. The
  rules live in code rather than in configuration, since deciding that a failure was not the code's
  fault deserves review.
- `fix-mime-assocs` to reconcile selected desktop applications in the `[Removed Associations]`
  section of `mimeapps.list`, with options to choose the desktop-entry directory, MIME-types file,
  and `mimeapps.list` path, plus a dry-run mode.
- `merge-dependabot-prs` and `merge-pre-commit-prs` `-A`/`--archive-email` to archive the Gmail
  thread notifying about each merged pull request, and `-E`/`--email` to choose the address.
  Without `-E` the address on the authenticated GitHub account is used. Credentials are read from
  the keyring under the service `deltona:mpr:google` keyed on the address, and must be an
  authorized user JSON containing `client_id`, `client_secret`, and `refresh_token`. Threads are
  matched on the GitHub `List-ID` and the `(PR #N)` subject suffix, then archived and marked read
  by removing the `INBOX` and `UNREAD` labels. The search covers all mail rather than only the
  inbox, so a thread archived by an earlier run is still marked read. Only Gmail is supported.
  Requesting `-A` without working credentials is an error that stops the run and prints how to set
  them up, as is a token Gmail rejects, since neither fixes itself on the next pull request. The
  message quotes what Google reported rather than guessing at it, and names the full command to
  run. A lapsed authorisation only asks for `--authorize-gmail --email`, since nothing about the
  OAuth client has to change. Any other archiving failure is logged and does not count the pull
  request as unmerged.
- `merge-dependabot-prs` and `merge-pre-commit-prs` `--authorize-gmail`, which runs the Google
  consent flow with `--email` and stores the resulting credentials. `--client-secret` is needed
  only the first time; afterwards the OAuth client stored beside the refresh token is reused, so
  authorising again requires nothing from the Google Cloud console. The credentials go into the
  keyring and the command exits without merging anything. It prints a URL to open in a browser on
  any machine and reads back the address the browser was redirected to, so nothing is served
  locally and no browser is started. That is what makes it usable over SSH.
- `deltona.string.pluralize` to select a noun's singular or plural form for a count, with an
  optional irregular plural. Messages that used to write `thread(s)` or `repository(ies)` now read
  correctly for the number they report.
- `deltona.gmail` module with `archive_github_pull_request_email`, `authorize`, and
  `get_access_token`, plus the `KEYRING_SERVICE` and `SCOPE` constants and a
  `GmailConfigurationError` raised when Gmail support is requested but is not set up correctly.
- `merge-dependabot-prs` and `merge-pre-commit-prs` `-N`/`--mark-notifications-done` to mark the
  GitHub notification thread for each merged pull request as done. Off by default. The
  `merge_dependabot_pull_requests` and `merge_pre_commit_ci_pull_requests` functions accept a
  matching `mark_notifications_done` keyword. Requires a token with the `notifications` or `repo`
  scope; a failure to mark a thread is logged and does not count the pull request as unmerged.

### Changed

- The GitHub client now uses [gidgethub](https://gidgethub.readthedocs.io/) instead of PyGithub.
  This makes the GitHub helpers natively asynchronous (no thread pool) and replaces the `pygithub`
  optional dependency with `gidgethub`. `get_github_default_branch` is now a coroutine.

### Fixed

- `merge-dependabot-prs` no longer skips repositories that are configured with a Dependabot
  configuration file. Detection probed `.github/workflows/dependabot.yml`, which is not a path
  GitHub recognises; `.github/dependabot.yml` and `.github/dependabot.yaml` are now checked
  instead. Private repositories were affected the most, because GitHub omits
  `security_and_analysis` for them and the file probe was the only remaining signal.
- `merge-dependabot-prs` and `merge-pre-commit-prs` now log at debug level when a repository is
  skipped, so `-d` reports why a repository was passed over instead of omitting it silently.

## [0.2.4] - 2026-05-23

### Added

- `smv` now reads `~/.ssh/config` by default, applying `HostName`, `User`, `Port`, `IdentityFile`,
  `Compression`, and `ConnectTimeout` directives. Explicit CLI flags still take precedence.
- `smv` `-F`/`--ssh-config` option to load an alternative ssh_config file (mirrors `scp -F`).
- `smv` `--no-ssh-config` option to disable ssh_config reading entirely.
- `smv` `-o KEY=VALUE` (repeatable) to pass ssh_config-style options on the command line. Supported
  keys: `Compression`, `ConnectTimeout`, `HostName`, `IdentityFile`, `Port`, and `User`. Unknown
  keys are rejected with a clear error. Precedence: explicit CLI flag > `-o` > `-F` >
  `~/.ssh/config` > built-in defaults (matches `scp`).
- `smv` `-q`/`--quiet` to silence INFO-level log output (errors are still printed).
- `smv` `-v`/`--verbose` as an alias for `-d`/`--debug` (matches `scp -v`).
- `smv` `-B` for scp batch-mode compatibility. Accepted as a no-op because paramiko is already
  non-interactive by default.
- `smv` `-J [user@]host[:port][,...]` to route the SFTP connection through one or more SSH jump
  hosts (`scp -J` equivalent). Multiple hops are comma-separated. Each hop's port defaults to 22
  and the user falls back to the target user if omitted.
- `smv` `-o ProxyJump=...` is now also honoured (added to the `-o` whitelist). Same chain syntax
  as `-J`. Explicit `-J` takes precedence over `-o ProxyJump`.
- `smv` `-l KBIT_PER_SEC` to throttle SFTP uploads in Kbit/s. The limit is applied per file (each
  upload is independently bounded to the rate). Implemented as a sleep-based callback passed to
  paramiko's `sftp.put`.
- `secure_move_path` accepts a new `bandwidth_limit_kbits: float | None = None` keyword for the
  same effect when calling the library directly.

### Changed

- `merge-dependabot-prs` and `merge-pre-commit-ci-prs` no longer print a full traceback when a pull
  request fails to merge during normal runs. A concise warning is logged instead, noting that the
  pull request will be retried. The full traceback is still emitted under `-d`/`--debug`.
- `smv` `-i`/`--key` now takes a path argument (validated for existence) instead of a file handle,
  so the option is actually usable; previously a file-handle object was passed to paramiko, which
  expects a path.

### Fixed

- `smv` (and the underlying `secure_move_path` utility) no longer fails with `OSError: Failure`
  when the remote target is a directory (for example `smv file.zip host:~/Downloads/`). The source
  basename is now appended to directory-style targets, matching `scp` behaviour, while plain
  renames still work when the target does not exist remotely.
- `smv` no longer mis-parses `user@host:path` targets; the `user@` prefix is now correctly
  separated from the hostname before being handed to paramiko, which previously failed DNS
  resolution.

## [0.2.3] - 2026-05-08

### Changed

- `merge-dependabot-prs` and `merge-pre-commit-ci-prs` now silently skip repositories whose pull
  requests endpoint returns 404 (for example, repositories that have pull requests disabled).
  Previously this was logged as an error with a stack trace; it is now a single informational log
  line.
- On retry after `BotMergeError` (Dependabot or pre-commit.ci), only the repositories that still
  have unmerged pull requests are re-fetched. Previously every repository was re-processed on each
  retry.
- Snapcraft and Flatpak manifests now build from the released git tag instead of the current source
  directory, so packagers and CI use a stable, reproducible source.

### Fixed

- `merge-dependabot-prs` and `merge-pre-commit-ci-prs` no longer abort the entire run when one
  repository's API call fails (for example, when listing pull requests returns an unexpected
  error). The failing repository is logged and the command continues processing the remaining
  repositories.

## [0.2.2] - 2026-05-02

### Added

- New `merge-pre-commit-prs` CLI command that merges PRs opened by pre-commit.ci. Mirrors the
  options of `merge-dependabot-prs` (`--base-url`, `--delay`, `--concurrency`,
  `-M`/`--max-concurrent-http-requests`, `-r`/`--repo`). Skips repositories without a top-level
  `.pre-commit-config.yaml`, and posts `pre-commit.ci autofix` on the PR (deduped against the
  latest comment) when a merge attempt fails.
- Public async function `deltona.git.merge_pre_commit_ci_pull_requests` mirroring
  `merge_dependabot_pull_requests`.
- `deltona.git.BotMergeError` base class for bot-PR merge failures, carrying `remaining` and a
  human-readable `bot_label`. `DependabotMergeError` is now a subclass and remains
  backward-compatible.
- `deltona.git.PreCommitCIMergeError` raised when one or more pre-commit.ci pull requests cannot be
  merged.

## [0.2.1] - 2026-04-26

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

[unreleased]: https://github.com/Tatsh/deltona/compare/v0.3.0...HEAD
[0.3.0]: https://github.com/Tatsh/deltona/compare/v0.2.4...v0.3.0
[0.2.4]: https://github.com/Tatsh/deltona/compare/v0.2.3...v0.2.4
[0.2.3]: https://github.com/Tatsh/deltona/compare/v0.2.2...v0.2.3
[0.2.2]: https://github.com/Tatsh/deltona/compare/v0.2.1...v0.2.2
[0.2.1]: https://github.com/Tatsh/deltona/compare/v0.2.0...v0.2.1
[0.2.0]: https://github.com/Tatsh/deltona/compare/v0.1.4...v0.2.0
[0.1.4]: https://github.com/Tatsh/deltona/compare/v0.1.3...v0.1.4
[0.1.3]: https://github.com/Tatsh/deltona/compare/v0.1.2...v0.1.3
[0.1.2]: https://github.com/Tatsh/deltona/compare/v0.1.1...v0.1.2
[0.1.1]: https://github.com/Tatsh/deltona/compare/v0.1.0...v0.1.1
[0.1.0]: https://github.com/Tatsh/deltona/compare/v0.0.3...v0.1.0
[0.0.3]: https://github.com/Tatsh/deltona/compare/v0.0.2...v0.0.3
[0.0.2]: https://github.com/Tatsh/deltona/compare/v0.0.1...v0.0.2
[0.0.1]: https://github.com/Tatsh/deltona/releases/tag/v0.0.1
