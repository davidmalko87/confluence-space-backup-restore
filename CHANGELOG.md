# Changelog

All notable changes to this project are documented here. The format is based on
[Keep a Changelog](https://keepachangelog.com/), and the project adheres to
[Semantic Versioning](https://semver.org/).

## [1.0.0] - 2026-05-27

### Added
- Per-space backup over the Confluence Cloud REST API (v2 primary, v1 fallback),
  with streaming writes to disk for large spaces.
- Backs up pages (storage body) + hierarchy, blog posts, attachments (binaries),
  footer/inline comments, labels, content/space properties, page restrictions,
  space permissions, and an optional page-version metadata sidecar.
- Phased, resumable restore into a NEW space (parent-before-child page creation,
  two-pass `ri:content-id` macro/link remap), with dry-run preview.
- Restore safety: new-space default, `--overwrite` + typed confirmation guard,
  never deletes content.
- Original author/date preserved as a footer note plus an `original_provenance`
  content property (REST cannot set the live author/timestamp).
- Optional, best-effort native XML space export artifact (`--native-export`,
  off by default) for manual UI import.
- CSV export, backup statistics/inspection, sha256 integrity validation,
  connection test, config viewer, incomplete-backup cleanup.
- Interactive menu and argparse CLI; manifest with sha256 + `complete` flag.

### Known limitations
- Cannot restore original timestamps, creator, or version history (Confluence
  Cloud API constraints). Inline-comment re-anchoring and space-permission
  re-application are not performed automatically. See the README limitations
  table for the full list and how each degrades.
- The native XML export path uses undocumented endpoints and is unverified in
  this release — confirm on a non-prod site before relying on it.
