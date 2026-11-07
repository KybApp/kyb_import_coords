# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.16.4] - 2026-11-07
### Fixed
- Copy in preview table: whole selection via context menu and Ctrl+C (row, rectangle, Ctrl+click)

## [0.16.3] - 2026-11-01
### Fixed
- Critical: removed `QCoreApplication.installTranslator()` which broke the QGIS 4 (Qt6) UI (labels disappeared). Translations now live in a module variable `_active_translator` and are applied only through `tr(context, text)`, isolated to this plugin.
- Removed `DOCTYPE` declarations from `.ts` files to ensure compatibility with QGIS 3.28 where `defusedxml` is unavailable.

## [0.16.2] - 2026-11-01
### Security
- Added protection against XML bombs (XXE attacks) when parsing translation files.

## [0.16.1] - 2026-11-01
### Added
- Translations are now loaded directly from `.ts` files without the need for `lrelease`.

### Fixed
- Settings now persist correctly across language switches.
- Fixed a `KeyError` that occurred on non-Russian locales.

## [0.16.0] - 2026-11-01
### Added
- Added localization for 8 languages (ru, en, de, fr, es, it, zh, kk).
- Translated the UI, metadata, and standard dialog buttons.

## [0.15.18] - 2026-10-30
### Fixed
- Fixed a critical bug where the plugin failed to load on QGIS 3.28 (PyQt5) due to an `ImportError: QAction`.