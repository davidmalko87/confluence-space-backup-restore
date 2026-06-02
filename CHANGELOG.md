# Changelog

All notable changes to this project are documented here. The format is based on
[Keep a Changelog](https://keepachangelog.com/), and the project adheres to
[Semantic Versioning](https://semver.org/).

## [1.0.1] - 2026-06-02

### Fixed
- Comment attribution now records the original creation date (comments store it
  under `version.createdAt`, not top-level `createdAt`), so the footer note no
  longer shows "unknown date".

### Added
- Restore now rewrites `ri:space-key` on links that point back into the space
  being restored (source space key → target space key), so a link that carried
  the source key resolves in the new space. Links to other spaces are left
  untouched. (Most Cloud links are stored by title and already survive restore
  natively — this covers the cross-space edge case.)
- A pytest suite (offline unit tests) run in CI across Python 3.10–3.13.

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

### Verified
- Round-trip proven end-to-end against a live Confluence Cloud site: a space was
  backed up, restored into a fresh space, and diffed via the API — page count,
  hierarchy, and attachment bytes all matched.

### Empirically-found Cloud behaviors handled
- Attachment download uses the v1 content endpoint
  (`/rest/api/content/{id}/child/attachment/{attId}/download`); the
  `_links.download` link Atlassian advertises is deprecated and 401s under token
  auth.
- Attachment upload uses a non-browser User-Agent (a browser-like UA makes
  Confluence's XSRF filter reject the `X-Atlassian-Token: no-check` bypass) and
  PUT for idempotent re-runs.
- Restore adopts the space's auto-created homepage instead of leaving a duplicate.
- Space resolution uses `description-format=plain` (spaces accept PLAIN/VIEW only).

### Known limitations
- Cannot restore original timestamps, creator, or version history (Confluence
  Cloud API constraints). Inline-comment re-anchoring and space-permission
  re-application are not performed automatically. See the README limitations
  table for the full list and how each degrades.
- The native XML export path uses undocumented endpoints and is unverified in
  this release — confirm on a non-prod site before relying on it.
