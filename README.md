# Confluence Space Backup & Restore

[![CI](https://github.com/davidmalko87/confluence-space-backup-restore/actions/workflows/ci.yml/badge.svg?branch=main)](https://github.com/davidmalko87/confluence-space-backup-restore/actions/workflows/ci.yml)
[![PyPI version](https://img.shields.io/pypi/v/confluence-space-backup-restore.svg)](https://pypi.org/project/confluence-space-backup-restore/)
[![PyPI downloads](https://img.shields.io/pypi/dm/confluence-space-backup-restore.svg)](https://pypi.org/project/confluence-space-backup-restore/)
[![Python](https://img.shields.io/pypi/pyversions/confluence-space-backup-restore.svg?logo=python&logoColor=white)](https://pypi.org/project/confluence-space-backup-restore/)
[![Confluence Cloud](https://img.shields.io/badge/Confluence-Cloud-0052CC.svg?logo=confluence&logoColor=white)](https://www.atlassian.com/software/confluence)
[![License](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)
[![Platform](https://img.shields.io/badge/platform-Windows%20%7C%20macOS%20%7C%20Linux-lightgrey.svg)](#)
[![Round-trip](https://img.shields.io/badge/round--trip-verified-success.svg)](#-round-trip-verified)
[![Last commit](https://img.shields.io/github/last-commit/davidmalko87/confluence-space-backup-restore.svg)](https://github.com/davidmalko87/confluence-space-backup-restore/commits/main)
[![GitHub issues](https://img.shields.io/github/issues/davidmalko87/confluence-space-backup-restore.svg)](https://github.com/davidmalko87/confluence-space-backup-restore/issues)

Backup and restore individual **Confluence Cloud spaces** via REST API — pages, hierarchy, attachments, comments, labels, properties, restrictions, and blog posts. Fully resumable, with an interactive menu and CLI mode. The Confluence sibling of [jira-project-backup-restore](https://github.com/davidmalko87/jira-project-backup-restore).

> ⚠️ **A REST restore is content-faithful, not forensic.** It rebuilds pages, hierarchy, attachments, comments and labels — but **cannot** restore original authors, timestamps, or version history (Confluence Cloud has no API to set them). Read [Known Limitations](#-known-limitations) before relying on this for disaster recovery.

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
| **Full space backup** | Pages (storage format) + hierarchy, blog posts, attachments, footer/inline comments, labels, content & space properties, restrictions, permissions |
| **9-phase restore** | Space → pages (parent-first) → blog posts → macro/ID remap → attachments → comments → labels → properties → restrictions |
| **Two-pass ID remap** | Rewrites `ri:content-id` references after new page IDs are minted, so include/excerpt/pagetree macros don't break |
| **New-space default** | Restore creates a **new** space; never clobbers a live space without `--overwrite` + typed confirmation |
| **Homepage adoption** | Reuses the space's auto-created homepage instead of leaving a duplicate |
| **Multi-space** | Back up several spaces in a single run |
| **Resumable** | Re-run after interruption — completed phases and items are skipped; a phase completes only when fail count is 0 |
| **Memory efficient** | Pages/comments/attachments stream to disk — large spaces won't OOM a small host |
| **Dry-run mode** | Preview every restore action without making changes |
| **Rate-limit aware** | Exponential backoff with `429 / Retry-After` detection |
| **CSV export** | Export space content to CSV for reporting and sharing |
| **Backup inspection** | Content-type breakdown, page-status counts, disk size |
| **Integrity validation** | sha256 manifest verification of every backed-up file |
| **Connection test** | Pre-flight: authentication + space listing |
| **Interactive menu + CLI** | Guided workflow, or `--backup` / `--restore` / `--export-csv` flags for scripts and cron |
| **Native XML export** | Optional best-effort high-fidelity ZIP for manual UI import (`--native-export`) |

---

## 🚀 Quick Start

### 1. Install

**Via PyPI (recommended)** — provides the `confluence-backup` command:

```bash
pip install confluence-space-backup-restore
confluence-backup
```

**Or clone for development:**

```bash
git clone https://github.com/davidmalko87/confluence-space-backup-restore.git
cd confluence-space-backup-restore
pip install -r requirements.txt
python main.py
```

### 2. Configure

```bash
cp .env.example .env
```

Edit `.env` with your Confluence Cloud credentials:

```ini
CONFLUENCE_URL=https://your-domain.atlassian.net/wiki   # must include /wiki
CONFLUENCE_EMAIL=you@example.com
CONFLUENCE_API_TOKEN=your-api-token
```

> Generate an API token at [id.atlassian.com/manage-api-tokens](https://id.atlassian.com/manage-api-tokens). Auth is **Basic (email + token)** — no session-cookie refresh toil.

### 3. Run

**Interactive menu:**

```bash
python main.py
```

```
==============================================================
  Confluence Space Backup & Restore  v1.0.0
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
python main.py --backup DOCS
python main.py --backup DOCS,TEAM
python main.py --backup DOCS --native-export
```

**CLI — restore:**

```bash
python main.py --restore backups/DOCS_20260602_091819 --target-key DOCSR --dry-run
python main.py --restore backups/DOCS_20260602_091819 --target-key DOCSR
```

**CLI — inspect & export:**

```bash
python main.py --list
python main.py --validate backups/DOCS_20260602_091819
python main.py --export-csv backups/DOCS_20260602_091819
```

Exit codes: `0` success · `1` failure · `2` bad/insufficient arguments.

---

## 📦 What Gets Backed Up

| File | Contents |
|---|---|
| `space.json` | Space metadata + description |
| `pages.json` | Pages with storage-format body (streamed) |
| `blogposts.json` | Blog posts (streamed) |
| `attachments.json` | Attachment metadata index (streamed) |
| `attachments/<id>/` | Attachment binary files, streamed to disk |
| `comments/footer.json` | Footer comments |
| `comments/inline.json` | Inline comments (metadata; see limitations) |
| `labels.json` | Page, blog, and space labels |
| `properties/*.json` | Content properties + space properties |
| `restrictions.json` | Per-page restrictions (v1) |
| `permissions.json` | Space permissions |
| `versions/<pageId>.json` | Optional page version-metadata sidecar |
| `native/<KEY>_native.xml.zip` | Optional native XML export |
| `manifest.json` | File index + sha256 + `"complete": true` — presence marks the backup complete |

---

## 🔄 Restore Phases

Each phase is resumable via `restore_progress.json`, and is marked complete only when it finishes with zero failures:

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

Old→new content-ID mapping is saved in `id_maps.json` inside the backup directory.

---

## ⚠️ Known Limitations

These are **Confluence Cloud REST API constraints — not tool bugs**. The tool preserves everything it can and records the rest.

| Data | Status | Notes / degrades to |
|---|---|---|
| Page bodies (storage format) | ✅ Restored | round-trippable |
| Page hierarchy (parent/child) | ✅ Restored | rebuilt via `parentId`, parent-before-child |
| Page links (same space) | ✅ Restored | Cloud stores links by **title**, which is preserved — they resolve natively in the new space, no remap needed |
| Cross-space links to the source space | ✅ Restored | `ri:space-key` rewritten source→target in the remap pass; links to *other* spaces untouched |
| Blog posts | ✅ Restored | flat |
| Attachments (latest version) | ✅ Restored | v1 content download/upload; original filename kept |
| Footer comments | ✅ Restored | original author + date added as a footer note |
| Labels (page/blog) | ✅ Restored | v1 |
| Page restrictions | ⚠️ Best-effort | identities must resolve in the target tenant |
| Content / space properties | ⚠️ Best-effort | system-managed properties may reject writes |
| Inline comments | ❌ Backup only | text re-anchoring is unreliable via API; kept in backup |
| Space labels | ❌ Not restored | no API to set space-level labels |
| Space permissions | ❌ Manual | cross-tenant identity remap; saved for review |
| **Original author / creator** | ❌ Not settable | becomes the API user; original → footer note **+** `original_provenance` property |
| **Original created / updated dates** | ❌ Not settable | become the restore run time |
| **Version history** | ❌ Not replayed | optional metadata sidecar only |
| **Page / content IDs** | ♻️ Reassigned | new IDs minted; old→new map kept |
| ID-referencing macros (`include`, `excerpt-include`, ID-rooted `children`/`pagetree`) | ⚠️ Remapped (defensive) | `ri:content-id` rewritten in a 2nd pass; unmapped refs break. Most Cloud links use titles (above), so this mainly covers macros/migrated content that embed a numeric content ID |

---

## 🛡️ Restore Safety

- **Default: a NEW space is created.** The tool refuses to modify an existing space key.
- **Touching an existing space requires `--overwrite` *and* typing the space key to confirm** (the menu always prompts; non-interactive CLI honors the flag). Even then, restore is **additive** — it never deletes content.
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

---

## ✅ Round-trip Verified

The REST backup→restore round-trip has been **proven end-to-end against a live Confluence Cloud site**: a space was backed up, restored into a fresh space, and diffed via the API — **page count, hierarchy, and attachment bytes all matched**. A backup is only proven once it has been restored end-to-end and verified; structural checks alone are necessary but not sufficient.

To prove it yourself on a non-prod site: `--backup SOURCE` → `--restore <dir> --target-key SCRATCH --dry-run` → `--restore <dir> --target-key SCRATCH`, then compare page count + hierarchy, bodies, attachment count + sizes, comments, and labels.

---

## 🗂️ Project Structure

```
confluence-space-backup-restore/
├── main.py                   # Entry point — interactive menu + CLI flags
├── .env.example              # Configuration template
├── requirements.txt          # Python dependencies
│
├── confluence_tool/
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
│   ├── cli.py                # Console-script entry point
│   └── utils.py              # Logging, JSON streaming I/O, utilities
│
└── backups/                  # Backup output directory (gitignored)
    └── DOCS_20260602_091819/
        ├── manifest.json     # Completion marker + file index
        ├── pages.json
        ├── attachments/
        └── ...
```

---

## ⚙️ Configuration Reference

All settings live in `.env` (copy from `.env.example`):

| Variable | Required | Default | Description |
|---|---|---|---|
| `CONFLUENCE_URL` | Yes | — | Cloud base URL — **must include `/wiki`** |
| `CONFLUENCE_EMAIL` | Yes* | — | Account email for API token auth |
| `CONFLUENCE_API_TOKEN` | Yes* | — | API token — [generate here](https://id.atlassian.com/manage-api-tokens) |
| `CONFLUENCE_COOKIE_HEADER` | Alt* | — | Full `Cookie:` header value for SSO auth |
| `CONFLUENCE_VERIFY_SSL` | No | `true` | Set `false` to skip SSL verification |
| `BACKUP_ROOT` | No | `./backups` | Directory where backups are written |
| `PAGE_SIZE` | No | `250` | Items per API page (Cloud v2 max 250) |
| `MAX_RETRIES` | No | `5` | Retry count on transient failures |
| `READ_TIMEOUT` | No | `30` | HTTP read timeout in seconds |
| `API_DELAY` | No | `0.2` | Seconds to wait between API calls |
| `CHUNK_SIZE` | No | `8388608` | Bytes per chunk for streaming downloads |
| `BODY_FORMAT` | No | `storage` | `storage` (recommended) or `atlas_doc_format` |
| `INCLUDE_ATTACHMENTS` | No | `true` | Download attachment binary files |
| `INCLUDE_COMMENTS` | No | `true` | Back up footer + inline comments |
| `INCLUDE_BLOGPOSTS` | No | `true` | Back up blog posts |
| `INCLUDE_RESTRICTIONS` | No | `true` | Back up per-page restrictions |
| `INCLUDE_VERSIONS` | No | `false` | Save version-metadata sidecar (reference only) |
| `NATIVE_EXPORT` | No | `false` | Also attempt a native XML export (best-effort) |
| `NATIVE_EXPORT_TIMEOUT` | No | `1800` | Max seconds to wait for a native export |

> \* Either `CONFLUENCE_EMAIL` + `CONFLUENCE_API_TOKEN` **or** `CONFLUENCE_COOKIE_HEADER` is required.

---

## 🐍 Requirements

- Python **3.10+** (tested on 3.10–3.13)
- [`requests`](https://pypi.org/project/requests/) >= 2.28
- [`python-dotenv`](https://pypi.org/project/python-dotenv/) >= 1.0
- Optional: [`rich`](https://pypi.org/project/rich/) for colored output (`pip install .[ui]`)

---

## 📝 Changelog

See [CHANGELOG.md](CHANGELOG.md) for the full version history.

## 📄 License

[MIT](LICENSE)
