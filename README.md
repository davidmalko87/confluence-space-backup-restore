# Confluence Space Backup & Restore

[![CI](https://github.com/davidmalko87/confluence-space-backup-restore/actions/workflows/ci.yml/badge.svg?branch=main)](https://github.com/davidmalko87/confluence-space-backup-restore/actions/workflows/ci.yml)
[![PyPI version](https://img.shields.io/pypi/v/confluence-space-backup-restore.svg)](https://pypi.org/project/confluence-space-backup-restore/)
[![PyPI downloads](https://img.shields.io/pypi/dm/confluence-space-backup-restore.svg)](https://pypi.org/project/confluence-space-backup-restore/)
[![Python](https://img.shields.io/pypi/pyversions/confluence-space-backup-restore.svg?logo=python&logoColor=white)](https://pypi.org/project/confluence-space-backup-restore/)
[![Confluence Cloud](https://img.shields.io/badge/Confluence-Cloud-0052CC.svg?logo=confluence&logoColor=white)](https://www.atlassian.com/software/confluence)
[![License](https://img.shields.io/badge/license-MIT-green.svg)](https://github.com/davidmalko87/confluence-space-backup-restore/blob/main/LICENSE)
[![Platform](https://img.shields.io/badge/platform-Windows%20%7C%20macOS%20%7C%20Linux-lightgrey.svg)](#)
[![Round-trip](https://img.shields.io/badge/round--trip-verified-success.svg)](#-round-trip-verified)
[![Last commit](https://img.shields.io/github/last-commit/davidmalko87/confluence-space-backup-restore.svg)](https://github.com/davidmalko87/confluence-space-backup-restore/commits/main)
[![GitHub issues](https://img.shields.io/github/issues/davidmalko87/confluence-space-backup-restore.svg)](https://github.com/davidmalko87/confluence-space-backup-restore/issues)

Backup and restore individual **Confluence Cloud spaces** via REST API — pages, hierarchy, attachments, comments, labels, properties, restrictions, and blog posts. Resumable restore, with an interactive menu and CLI mode. The Confluence sibling of [jira-project-backup-restore](https://github.com/davidmalko87/jira-project-backup-restore).

> ⚠️ **A REST restore is content-faithful, not forensic.** It rebuilds pages, hierarchy, attachments, comments and labels — but **cannot** restore original authors, timestamps, or version history (Confluence Cloud has no API to set them). Read [Known Limitations](#%EF%B8%8F-known-limitations) before relying on this for disaster recovery.

---

## 🤔 Why?

Confluence Cloud has **no supported public API** for native space export or import ([CONFCLOUD-40457](https://jira.atlassian.com/browse/CONFCLOUD-40457), open for years):

- **Native import is UI-only** (Settings → Data management → Import spaces, site-admin) and **cannot overwrite** an existing space key — there's no way to automate or verify it end-to-end.
- **Native export** is reachable only through *undocumented* `.action` endpoints that Atlassian can change at any time.

So an **automated, verifiable** backup *and restore* must be built on the REST API. That's the backbone here. A native XML export is offered as an *optional, best-effort, off-by-default* high-fidelity artifact for manual import — never the primary guarantee.

---

## ✨ Features

| Feature | Description |
|---|---|
| **Space backup** | Current pages (storage format) + hierarchy, blog posts, attachments, footer/inline comments, labels, content & space properties, restrictions, permissions — what is *not* captured is listed under [Known Limitations](#%EF%B8%8F-known-limitations) |
| **9-phase restore** | Space → pages (parent-first) → blog posts → macro/ID remap → attachments → comments → labels → properties → restrictions |
| **Two-pass ID remap** | Rewrites `ri:content-id` references after new page IDs are minted, so include/excerpt/pagetree macros don't break |
| **New-space default** | Restore creates a **new** space; refuses an existing key without `--overwrite` + typed confirmation (one caveat: see [Restore Safety](#%EF%B8%8F-restore-safety)) |
| **Homepage adoption** | Reuses the space's auto-created homepage instead of leaving a duplicate |
| **Multi-space** | Back up several spaces in a single run |
| **Resumable restore** | Re-run an interrupted restore — completed phases and items are skipped (limits: see [Restore Phases](#-restore-phases)). Backups are not resumable: each run writes a new folder, so re-run an interrupted backup from scratch |
| **Memory-efficient backup** | Pages/comments/attachments stream to disk during backup — large spaces won't OOM a small host. Restore, CSV export and inspection load each JSON file (including all page bodies) into memory |
| **Dry-run mode** | Preview every restore action without making changes |
| **Rate-limit aware** | Exponential backoff with `429 / Retry-After` detection |
| **CSV export** | Export space content to CSV for reporting and sharing |
| **Backup inspection** | Content-type breakdown, page-status counts, disk size (menu option 6 — crashes with a `TypeError` in 1.0.1, a known bug) |
| **Integrity validation** | sha256 manifest verification of every backed-up file (it cannot detect content that failed to download — see [Known Limitations](#%EF%B8%8F-known-limitations)) |
| **Connection test** | Pre-flight: authentication + space listing |
| **Interactive menu + CLI** | Guided workflow, or `--backup` / `--restore` / `--export-csv` flags for scripts and cron |
| **Native XML export** | Optional best-effort high-fidelity ZIP for manual UI import (`--native-export`) |

---

## 🚀 Quick Start

### 1. Install

**Via PyPI (recommended)** — provides the `confluence-backup` command:

```bash
pip install confluence-space-backup-restore
pip install "confluence-space-backup-restore[ui]"      # optional: colored menu output (rich)
```

**Or as an isolated app with [pipx](https://pipx.pypa.io/)** — keeps its dependencies out of your global Python:

```bash
pipx install confluence-space-backup-restore
pipx install "confluence-space-backup-restore[ui]"     # with the optional extra
```

**Upgrade:**

```bash
pip install -U confluence-space-backup-restore         # pipx: pipx upgrade confluence-space-backup-restore
```

**Or clone and run from source** (development):

```bash
git clone https://github.com/davidmalko87/confluence-space-backup-restore.git
cd confluence-space-backup-restore
pip install -r requirements.txt
python main.py --help                                  # same flags as confluence-backup
```

> **Where files live:** `confluence-backup` reads `.env` from the folder you run it in, or from `--env PATH`; that file must exist even when the variables are already exported (exported values take precedence over the file). Backups and one log file per run (`confluence_tool_<timestamp>.log`) go to `BACKUP_ROOT` — default `./backups`, resolved against the current folder, not the `.env` location — so set an absolute `BACKUP_ROOT` for cron; CSV exports (`csv_export/`) and restore state files are written inside the backup folder you point them at. A clone behaves the same way (`python main.py` also reads `./.env`).

### 2. Configure

Create a file named `.env` in the folder you will run `confluence-backup` from (in a clone: `cp .env.example .env`) and add your Confluence Cloud credentials:

```ini
CONFLUENCE_URL=https://your-domain.atlassian.net/wiki   # /wiki is appended if omitted
CONFLUENCE_EMAIL=you@example.com
CONFLUENCE_API_TOKEN=your-api-token
```

The full template with every setting, `.env.example`, is not included in the PyPI package. To start from it instead:

```bash
curl -o .env https://raw.githubusercontent.com/davidmalko87/confluence-space-backup-restore/main/.env.example
```

Every command except `--help` and `--version` — including the offline `--list`, `--validate` and `--export-csv` — needs this file with the credentials filled in; otherwise it exits with `Config file not found` or a validation error.

> Generate an API token at [id.atlassian.com/manage-api-tokens](https://id.atlassian.com/manage-api-tokens). Auth is **Basic (email + token)** — no session-cookie refresh toil.

### 3. Run

**Help and interactive menu:**

```bash
confluence-backup --help          # all flags
confluence-backup                 # interactive menu
confluence-backup --version       # print the installed version
```

From a clone, use `python main.py` in place of `confluence-backup` — the flags are identical (exit codes are not, see below).

```
==============================================================
  Confluence Space Backup & Restore  v1.0.1
==============================================================
  Site: https://your-domain.atlassian.net   Auth: API token   Backups: ./backups
--------------------------------------------------------------
  --- Backup & Restore ---
   1) Backup space(s)
   2) Restore space from backup
  --- Browse & Analyze ---
   3) List existing backups
   4) Validate backup integrity
   5) Export backup to CSV
   6) Inspect backup details
  --- Settings & Tools ---
   7) Test Confluence connection
   8) Show current configuration
   9) Cleanup incomplete backups
   0) Exit
```

**CLI — backup:**

```bash
confluence-backup --backup DOCS                                      # one space
confluence-backup --backup DOCS,TEAM --no-attachments                # several spaces, skip attachments
confluence-backup --backup DOCS --native-export --include-versions   # + native XML ZIP + version sidecar
```

**CLI — restore:**

```bash
confluence-backup --restore backups/DOCS_20260602_091819 --target-key DOCSR --dry-run    # preview, writes nothing
confluence-backup --restore backups/DOCS_20260602_091819 --target-key DOCSR --target-name "Docs (restored)"
confluence-backup --restore backups/DOCS_20260602_091819 --target-key DOCS --overwrite   # into an EXISTING space
```

**CLI — inspect & export:**

```bash
confluence-backup --list                                             # backups in BACKUP_ROOT
confluence-backup --validate backups/DOCS_20260602_091819            # sha256 + size check
confluence-backup --export-csv backups/DOCS_20260602_091819          # CSVs -> <dir>/csv_export/
confluence-backup --env ~/.config/confluence-backup/.env --list      # use a .env stored elsewhere
```

**CLI reference:**

| Flag | Purpose |
|---|---|
| `-h`, `--help` | Show all flags and exit (works without `.env`) |
| `--version` | Print the version and exit |
| `--env PATH` | `.env` file to load (default: `./.env` in the current folder) |
| `--backup KEY[,KEY...]` | Back up one or more spaces (comma-separated) into `BACKUP_ROOT/<KEY>_<UTC timestamp>/` |
| `--no-attachments` | Backup: skip attachments (index and binaries) |
| `--include-versions` | Backup: also save the page version-metadata sidecar (`versions/`) |
| `--native-export` | Backup: also try the native XML space export (best-effort) |
| `--restore DIR` | Restore from a backup directory (requires `--target-key`) |
| `--target-key KEY` | Target space key — a new space unless `--overwrite` is given |
| `--target-name NAME` | Name for the new target space (default: the source space name) |
| `--overwrite` | Allow restoring into an existing space; asks you to type the key when run in a terminal, auto-confirms otherwise |
| `--dry-run` | Restore: preview every action without writing anything |
| `--list` | List backups in `BACKUP_ROOT` and exit |
| `--validate DIR` | Verify a backup's manifest (sha256 + sizes) and exit |
| `--export-csv DIR` | Write pages/blogposts/comments/attachments CSVs to `DIR/csv_export/` |

Use one action per run: if several are given, only the first of `--list`, `--validate`, `--export-csv`, `--backup`, `--restore` runs and the rest are ignored.

Exit codes (`confluence-backup`): `0` success · `1` failure · `2` bad/insufficient arguments. Known gaps in 1.0.1: a restore that leaves failed items and a backup whose attachment downloads or reads failed both exit `0` (check the log for warnings such as `had N failure(s)` or `Could not download attachment`), and `python main.py` discards the result code, so a backup, restore or `--validate` that reports failure still exits `0` — for scripts and cron use `confluence-backup` (in a clone: `pip install -e .`).

---

## 📦 What Gets Backed Up

| File | Contents |
|---|---|
| `space.json` | Space metadata + description |
| `pages.json` | Current pages with storage-format body (streamed); archived pages are not included |
| `blogposts.json` | Blog posts (streamed) |
| `attachments.json` | Attachment metadata index (streamed) |
| `attachments/<id>/` | Attachment binary files, streamed to disk |
| `comments/footer.json` | Top-level footer comments on pages and blog posts (replies are not included) |
| `comments/inline.json` | Top-level inline comments on pages (metadata; see limitations) |
| `labels.json` | Page, blog, and space labels |
| `properties/*.json` | Content properties + space properties |
| `restrictions.json` | Per-page restrictions (v1) |
| `permissions.json` | Space permissions |
| `versions/<pageId>.json` | Optional page version-metadata sidecar |
| `native/<KEY>_native.xml.zip` | Optional native XML export |
| `manifest.json` | File index + sha256 + `"complete": true` — written when the run finishes; presence marks the backup complete (failed downloads/reads are only logged, see [Known Limitations](#%EF%B8%8F-known-limitations)) |

---

## 🔄 Restore Phases

Progress is saved in `restore_progress.json`, so an interrupted restore can be re-run: completed phases and items are skipped. Pages, blog posts, attachments and comments are marked complete only when they finish with zero failures. Remap, labels, properties and restrictions never count failures, and comments on content that was not created are skipped rather than counted — so these phases can be marked complete with items missing. If a page fails to create, a re-run creates it but does not remap its body or add its comments, labels, properties or restrictions, and its child pages (already created without a parent) stay under the space homepage.

| # | Phase | What happens | Endpoint |
|---|---|---|---|
| 1 | Space | Create the target space (new key by default) | `POST /rest/api/space` |
| 2 | Pages | Create parent-before-child; record old→new ID map | `POST /wiki/api/v2/pages` |
| 3 | Blog posts | Create flat blog posts | `POST /wiki/api/v2/blogposts` |
| 4 | Remap | Rewrite `ri:content-id` + source-space `ri:space-key` references | `PUT /wiki/api/v2/pages` |
| 5 | Attachments | Upload binaries (idempotent PUT) | `PUT /rest/api/content/{id}/child/attachment` |
| 6 | Comments | Footer comments; author/date prepended as text | `POST /wiki/api/v2/footer-comments` |
| 7 | Labels | Re-apply page/blog labels | `POST /rest/api/content/{id}/label` |
| 8 | Properties | Recreate content & space properties | `POST /wiki/api/v2/{type}/{id}/properties` |
| 9 | Restrictions | Re-apply page restrictions (best-effort) | `PUT /rest/api/content/{id}/restriction` |

Restore state is saved inside the backup directory: `restore_progress.json`, `id_maps.json` (old→new content IDs) and `user_cache.json` (author-name lookups). It is not tied to the target space key — see [Restore Safety](#%EF%B8%8F-restore-safety) before restoring the same backup a second time.

---

## ⚠️ Known Limitations

Most of these are **Confluence Cloud REST API constraints — not tool bugs**. The tool preserves everything it can and records the rest. Rows marked *(tool gap)* are things this version does not handle yet.

| Data | Status | Notes / degrades to |
|---|---|---|
| Page bodies (storage format) | ✅ Restored | round-trippable; an attribution paragraph is added at the top of each restored body |
| Page hierarchy (parent/child) | ✅ Restored | rebuilt via `parentId`, parent-before-child. *(tool gap)* Top-level pages other than the homepage are nested under the new homepage, and children of a page that failed to create land under the homepage (see [Restore Phases](#-restore-phases)) |
| Page links (same space) | ✅ Restored | Cloud stores links by **title**, which is preserved — they resolve natively in the new space, no remap needed |
| Cross-space links to the source space | ✅ Restored | `ri:space-key` rewritten source→target in the remap pass; links to *other* spaces untouched |
| Blog posts | ✅ Restored | flat |
| Attachments (latest version) | ✅ Restored | v1 content download/upload; original filename kept |
| Footer comments | ✅ Restored | top-level comments; original author + date added as a note at the top of the comment |
| Comment replies (footer + inline) | ❌ Not backed up *(tool gap)* | only top-level comments are read; replies are skipped |
| Labels (page/blog) | ✅ Restored | v1 |
| Page restrictions | ⚠️ Best-effort | identities must resolve in the target tenant |
| Content / space properties | ⚠️ Best-effort | system-managed properties may reject writes |
| Inline comments | ❌ Backup only | text re-anchoring is unreliable via API; kept in backup. *(tool gap)* Pages only — inline comments on blog posts are not backed up |
| Archived pages | ❌ Not backed up *(tool gap)* | backup reads current pages only |
| Folders, whiteboards, databases, Smart Link embeds, app custom content | ❌ Not backed up *(tool gap)* | only pages and blog posts are read; a page inside a folder (or under any of these) is restored directly under the space homepage |
| Failed attachment downloads / per-page reads during backup | ⚠️ Logged only *(tool gap)* | logged as warnings, but the backup is still marked complete, passes `--validate` and exits `0` — check the log |
| Space labels | ❌ Not restored | no API to set space-level labels |
| Space permissions | ❌ Manual | cross-tenant identity remap; saved for review |
| **Original author / creator** | ❌ Not settable | becomes the API user; original → attribution note at the top of the body (storage format) **+** `original_provenance` property |
| **Original created / updated dates** | ❌ Not settable | become the restore run time |
| **Version history** | ❌ Not replayed | optional metadata sidecar only |
| **Page / content IDs** | ♻️ Reassigned | new IDs minted; old→new map kept |
| ID-referencing macros (`include`, `excerpt-include`, ID-rooted `children`/`pagetree`) | ⚠️ Remapped (defensive) | `ri:content-id` rewritten in a 2nd pass; unmapped refs break. Most Cloud links use titles (above), so this mainly covers macros/migrated content that embed a numeric content ID |

---

## 🛡️ Restore Safety

- **Default: a NEW space is created.** The tool refuses to modify an existing space key.
- **Restore state belongs to the backup directory, not to the target key.** Before restoring the same backup to a *different* key (for example the real restore after a `SCRATCH` test), delete `restore_progress.json` and `id_maps.json` from the backup directory. Otherwise 1.0.1 skips the space phase, including the existing-space check above: if the new key does not exist yet, the restore aborts with `Could not determine target space id`; if it does exist, the restore writes into that space without `--overwrite` and skips everything the earlier run already restored (after a finished run it reports success while restoring nothing).
- **Touching an existing space requires `--overwrite` *and* typing the space key to confirm** (the menu always prompts; non-interactive CLI honors the flag). Even then, restore is **additive** — it deletes no pages — but the existing space's **homepage title and body are replaced** by the backup's homepage (the previous version stays in page history).
- **Dry-run** (`--dry-run`) prints the full plan and writes nothing.
- A **trashed (not-yet-purged) space key** is detected — restore stops and tells you to purge it (Settings → Data Management → Trashed Spaces) or pick another key.

---

## 🗜️ Native XML Export (optional, off by default)

With `NATIVE_EXPORT=true` / `--native-export`, each backup *also* attempts a native XML space export and stores the ZIP under `native/`. This is a high-fidelity DR artifact (preserves history/authors/timestamps) that you import **manually** via the Confluence UI ("Import a space").

> ⚠️ It drives **undocumented** endpoints that Atlassian can change without notice. It is best-effort (failure is logged, never fails the REST backup) and **unverified in this build** — confirm it works on a non-prod site before relying on it.

---

## 🔒 Data Handling & Security

- **Backups are stored UNENCRYPTED** — plain JSON plus attachment binaries (and, if enabled, a native XML ZIP). They contain **real space content**; securing/encrypting the backup directory is **your responsibility**.
- Gitignored by default — never commit: `backups/`, `*.log`, `csv_export/`, native `*.zip`/`*.xml`, and `.env`.
- **Logs can leak content**: the DEBUG file log records truncated API response bodies (page text). Treat log files as sensitive.
- Credentials live only in `.env` (gitignored). No site, space, email, or token is ever hardcoded.
- **Keep `BACKUP_ROOT` for backups only.** Menu option 9 (*Cleanup incomplete backups*) deletes every subfolder of `BACKUP_ROOT` that has no complete `manifest.json` — without asking and without checking the folder name — including a backup another run is still writing.

---

## ✅ Round-trip Verified

The REST backup→restore round-trip has been **proven end-to-end against a live Confluence Cloud site**: a space was backed up, restored into a fresh space, and diffed via the API — **page count, hierarchy, and attachment bytes all matched**. A backup is only proven once it has been restored end-to-end and verified; structural checks alone are necessary but not sufficient.

To prove it yourself on a non-prod site: `--backup SOURCE` → `--restore <dir> --target-key SCRATCH --dry-run` → `--restore <dir> --target-key SCRATCH`, then compare page count + hierarchy, bodies, attachment count + sizes, comments, and labels. Before restoring that backup anywhere else, reset its restore state (see [Restore Safety](#%EF%B8%8F-restore-safety)).

---

## 🗂️ Project Structure

```
confluence-space-backup-restore/
├── main.py                   # Clone convenience wrapper — same flags as confluence-backup
├── pyproject.toml            # Packaging metadata; defines the confluence-backup command
├── requirements.txt          # Python dependencies
├── .env.example              # Configuration template (not in the PyPI package)
├── CHANGELOG.md              # Version history
├── CONTRIBUTING.md           # Versioning and release process
├── LICENSE                   # MIT
│
├── confluence_tool/
│   ├── __init__.py           # Package version (__version__)
│   ├── config.py             # .env loader and validation
│   ├── auth.py               # Session builder (API token / cookie auth)
│   ├── api_client.py         # HTTP client with retry + rate-limit handling
│   ├── backup.py             # BackupManager — per-space backup
│   ├── restore.py            # RestoreManager — 9-phase restore
│   ├── macros.py             # Storage-format content-ID remapper
│   ├── native_export.py      # Optional native XML export (best-effort)
│   ├── manifest.py           # Manifest build/validate (sha256 + complete flag)
│   ├── progress.py           # Resumability tracker (old→new ID maps, phases)
│   ├── export.py             # CSV export and backup statistics
│   ├── menu.py               # Interactive CLI menu
│   ├── cli.py                # Console-script entry point (confluence-backup)
│   └── utils.py              # Logging, JSON streaming I/O, utilities
│
├── tests/                    # Offline pytest suite
├── .github/workflows/        # ci.yml (ruff + pytest), publish.yml (PyPI on GitHub Release)
│
└── backups/                  # Default BACKUP_ROOT (gitignored)
    ├── confluence_tool_<timestamp>.log   # One log file per run
    └── DOCS_20260602_091819/
        ├── manifest.json     # Completion marker + file index
        ├── pages.json
        ├── attachments/
        └── ...
```

---

## ⚙️ Configuration Reference

All settings live in `.env` (see [Configure](#2-configure)); variables already exported in the environment take precedence:

| Variable | Required | Default | Description |
|---|---|---|---|
| `CONFLUENCE_URL` | Yes | — | Cloud base URL, e.g. `https://your-domain.atlassian.net/wiki` (`/wiki` is appended if omitted) |
| `CONFLUENCE_EMAIL` | Yes* | — | Account email for API token auth |
| `CONFLUENCE_API_TOKEN` | Yes* | — | API token — [generate here](https://id.atlassian.com/manage-api-tokens) |
| `CONFLUENCE_COOKIE_HEADER` | Alt* | — | Full `Cookie:` header value for SSO auth |
| `CONFLUENCE_VERIFY_SSL` | No | `true` | Set `false` to skip SSL verification |
| `BACKUP_ROOT` | No | `./backups` | Directory for backups and log files; a relative path resolves against the current folder |
| `PAGE_SIZE` | No | `250` | Items per API page (Cloud v2 max 250) |
| `MAX_RETRIES` | No | `5` | Total attempts per request, including the first (`0` makes every call fail) |
| `READ_TIMEOUT` | No | `30` | HTTP read timeout in seconds for API calls (`0` = none); attachment downloads use a fixed 600 s, uploads have no timeout |
| `API_DELAY` | No | `0.2` | Seconds to wait between API calls |
| `CHUNK_SIZE` | No | `8388608` | Bytes per chunk for streaming downloads |
| `BODY_FORMAT` | No | `storage` | `storage` (recommended) or `atlas_doc_format`. Restore reads bodies in this format, so keep it the same as when the backup was taken (a mismatch restores empty pages) |
| `INCLUDE_ATTACHMENTS` | No | `true` | Download attachment binary files |
| `INCLUDE_COMMENTS` | No | `true` | Back up footer + inline comments |
| `INCLUDE_BLOGPOSTS` | No | `true` | Back up blog posts |
| `INCLUDE_RESTRICTIONS` | No | `true` | Back up per-page restrictions |
| `INCLUDE_VERSIONS` | No | `false` | Save version-metadata sidecar (reference only) |
| `NATIVE_EXPORT` | No | `false` | Also attempt a native XML export (best-effort) |
| `NATIVE_EXPORT_TIMEOUT` | No | `1800` | Max seconds to wait for a native export |

> \* Either `CONFLUENCE_EMAIL` + `CONFLUENCE_API_TOKEN` **or** `CONFLUENCE_COOKIE_HEADER` is required.
>
> On/off settings count only `true`, `1` or `yes` (any case) as on. Any other value — including an empty one such as `CONFLUENCE_VERIFY_SSL=` — means **off**, so a blank `CONFLUENCE_VERIFY_SSL` disables certificate checks.

---

## 🐍 Requirements

- Python **3.10+** (tested on 3.10–3.13)
- [`requests`](https://pypi.org/project/requests/) >= 2.28
- [`python-dotenv`](https://pypi.org/project/python-dotenv/) >= 1.0
- Optional: [`rich`](https://pypi.org/project/rich/) for colored output (`pip install "confluence-space-backup-restore[ui]"`; in a clone: `pip install -e ".[ui]"`)

---

## 📝 Changelog

See [CHANGELOG.md](https://github.com/davidmalko87/confluence-space-backup-restore/blob/main/CHANGELOG.md) for the full version history.

## 📄 License

[MIT](https://github.com/davidmalko87/confluence-space-backup-restore/blob/main/LICENSE)
