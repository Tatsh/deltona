<!-- markdownlint-configure-file {"MD024": { "siblings_only": true } } -->

# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/), and this project
adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [unreleased]

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

[unreleased]: https://github.com/Tatsh/deltona/compare/v0.0.3...HEAD
