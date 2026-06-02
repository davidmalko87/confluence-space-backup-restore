# Confluence Space Backup & Restore

Granular, **per-space** backup and restore for **Confluence Cloud**, via the REST
API. The Confluence sibling of
[jira-project-backup-restore](https://github.com/davidmalko87/jira-project-backup-restore) —
same architecture, same UX, same honesty about what the Atlassian API can and
cannot do.

> **Read the [Limitations](#limitations--what-can-and-cannot-be-restored) section
> before relying on this for disaster recovery.** A REST-based restore is
> *content-faithful, not forensic*: it rebuilds pages, hierarchy, attachments,
> comments and labels, but it **cannot** restore original authors, timestamps, or
> version history (Confluence Cloud has no API to set them). For maximum fidelity
> the tool can *optionally* also produce a native XML export ZIP that you import
> manually through the Confluence UI.

---

## Why REST (and not native space export/import)?

Confluence Cloud has **no supported public API** for native space export or
import ([CONFCLOUD-40457](https://jira.atlassian.com/browse/CONFCLOUD-40457),
open for years):

- **Native import is UI-only** (Settings → Data management → Import spaces,
  site-admin), and it **cannot overwrite** an existing space key. There is no way
  to automate or verify it end-to-end.
- **Native export** is reachable only through *undocumented* `.action` endpoints
  that Atlassian can change at any time.

So a tool that promises an **automated, verifiable backup *and restore*** must be
built on the REST API. That is the backbone here. The native XML export is offered
as an *optional, best-effort, off-by-default* high-fidelity artifact for manual
import — never the primary guarantee.

---

## Features

- **Per-space backup** over REST v2 (v1 where v2 has gaps), streamed to disk so
  large spaces don't exhaust memory on small hosts.
- **Phased, resumable restore** into a **new** space (never clobbers a live space
  by default), with a two-pass macro/link **ID remap**.
- **Dry-run** restore preview — shows what would be created without writing.
- **CSV export**, **backup inspection** (counts, status breakdown, disk size),
  **integrity validation** (sha256), **connection test**, **config viewer**,
  **cleanup** of incomplete backups.
- Interactive menu **and** an argparse CLI for automation/CI.
- Optional native XML export artifact (`--native-export`).
- ASCII-safe console output (won't crash a legacy Windows cp1252 console);
  `rich` is an optional extra for color.

## Requirements

- Python 3.10+ (tested on 3.10–3.13)
- `requests`, `python-dotenv` (only required deps)

## Installation

```bash
# From a clone
git clone https://github.com/davidmalko87/confluence-space-backup-restore
cd confluence-space-backup-restore
pip install -r requirements.txt
python main.py

# Or as a package (provides the `confluence-backup` command)
pip install .
confluence-backup
```

## Configuration

Copy `.env.example` to `.env` and fill it in (`.env` is gitignored — never commit
it):

```ini
CONFLUENCE_URL=https://your-domain.atlassian.net/wiki   # must include /wiki
CONFLUENCE_EMAIL=you@example.com
CONFLUENCE_API_TOKEN=                                    # id.atlassian.com/manage-api-tokens
```

Auth is **Basic (email + API token)** — recommended, and it avoids the ~30-day
session-cookie refresh that UI-gated endpoints require. A raw `CONFLUENCE_COOKIE_HEADER`
is supported only as an SSO/SAML fallback. See `.env.example` for all tunables
(page size, retries, body format, include toggles, native export).

## Usage

### Interactive menu

```
=== Backup & Restore ===          === Browse & Analyze ===        === Settings & Tools ===
 1) Backup space(s)                3) List existing backups         7) Test Confluence connection
 2) Restore space from backup      4) Validate backup integrity     8) Show current configuration
                                    5) Export backup to CSV          9) Cleanup incomplete backups
                                    6) Inspect backup details        0) Exit
```

### CLI (automation)

```bash
confluence-backup --backup DOCS                       # back up space DOCS
confluence-backup --backup DOCS,TEAM --native-export  # multiple + native ZIP
confluence-backup --restore ./backups/DOCS_2026... --target-key DOCSR --dry-run
confluence-backup --restore ./backups/DOCS_2026... --target-key DOCSR
confluence-backup --list
confluence-backup --validate ./backups/DOCS_2026...
confluence-backup --export-csv ./backups/DOCS_2026...
```

Exit codes: `0` success · `1` failure · `2` bad/insufficient arguments.

## What gets backed up (on-disk layout)

```
backups/<SPACEKEY>_<UTC-timestamp>/
├── space.json                # space meta + description
├── pages.json                # pages with storage body (streamed)
├── blogposts.json            # blog posts (streamed)
├── attachments.json          # attachment metadata (streamed)
├── attachments/<id>/...      # attachment binaries
├── comments/footer.json      # footer comments
├── comments/inline.json      # inline comments (metadata; see limitations)
├── labels.json               # page/blog/space labels
├── properties/{space,content}_properties.json
├── restrictions.json         # per-page restrictions (v1)
├── permissions.json          # space permissions
├── versions/<pageId>.json    # OPTIONAL version metadata sidecar
├── native/<KEY>_native.xml.zip   # OPTIONAL native export
└── manifest.json             # written LAST: file index + sha256 + "complete": true
```

## Limitations — what can and cannot be restored

These are **Confluence Cloud REST API constraints, not tool bugs**. The tool
preserves everything it can and records the rest.

| Data | Backed up | Restored | Notes / degrades to |
|---|:---:|:---:|---|
| Page bodies (storage format) | ✅ | ✅ | round-trippable |
| Page hierarchy (parent/child) | ✅ | ✅ | rebuilt via `parentId`, parent-before-child |
| Blog posts | ✅ | ✅ | flat |
| Attachments (latest version) | ✅ | ✅ | v1 content download endpoint (the `_links.download` link Atlassian advertises is deprecated and 401s under token auth); v1 upload; original filename kept |
| Attachment version history | latest only | latest only | older versions not captured |
| Footer comments | top-level | ✅ | original author/date added as a footer note |
| Comment threads / replies | ❌ (v1.0) | ❌ | deferred |
| Inline comments | metadata | ❌ (default) | text re-anchoring is unreliable via API; kept in backup |
| Labels (page/blog) | ✅ | ✅ | v1 |
| Space labels | ✅ | ❌ | no API to set space-level labels |
| Page restrictions | ✅ | best-effort | identities must resolve in the target tenant |
| Space permissions | ✅ | ❌ (auto) | cross-tenant identity remap; saved for manual review |
| Content / space properties | ✅ | best-effort | system-managed properties may reject writes |
| **Original author / creator** | recorded | ❌ | live author becomes the API user; original → footer note **+** `original_provenance` content property |
| **Original created / updated dates** | recorded | ❌ | dates become the restore run time |
| **Version history** | optional sidecar | ❌ | never replayed (no API); reference only |
| **Page / content IDs** | ✅ | reassigned | new IDs minted; old→new map kept |
| ID-referencing macros (`include`, `excerpt-include`, ID-rooted `children`/`pagetree`, content-id links) | ✅ | best-effort | `ri:content-id` rewritten in a 2nd pass; unmapped refs break; **title+spaceKey refs survive natively** |

## Restore safety

- **Default: a NEW space is created.** The tool refuses to modify an existing
  space key.
- **Touching an existing space requires `--overwrite` *and* typing the space key
  to confirm** (the menu always prompts; non-interactive CLI honors the flag).
  Even then restore is **additive** — it never deletes content.
- **Dry-run** (`--dry-run`) prints the full plan and writes nothing.
- If the target key belongs to a **trashed (not yet purged) space**, restore stops
  and tells you to purge it (Settings → Data Management → Trashed Spaces) or pick
  another key.

## Native XML export (optional, best-effort, OFF by default)

With `NATIVE_EXPORT=true` / `--native-export`, each backup *also* attempts a native
XML space export and stores the ZIP under `native/`. This is a high-fidelity DR
artifact (preserves history/authors/timestamps) that you import **manually** via
the Confluence UI ("Import a space").

> ⚠️ It drives **undocumented** endpoints that Atlassian can change without notice.
> It is best-effort (a failure is logged and never fails the REST backup) and is
> **unverified in this build** — confirm it works on a non-prod site before relying
> on it. See [Verifying behavior](#verifying-behavior-on-a-non-prod-site).

## Data handling & security

- **Backups are stored UNENCRYPTED** — plain JSON plus attachment binaries (and,
  if enabled, a native XML ZIP). They contain **real space content**. Securing /
  encrypting the backup directory is **your responsibility**.
- The following may contain sensitive content and are **gitignored** by default —
  never commit them: `backups/`, `*.log`, `csv_export/`, native `*.zip`/`*.xml`,
  and `.env`.
- **Logs can leak content**: the DEBUG file log records truncated API response
  bodies (page text) to aid troubleshooting. Treat log files as sensitive.
- Credentials live only in `.env` (gitignored). No site, space, email, or token
  is ever hardcoded.

## Verifying behavior on a non-prod site

This build's REST behavior was confirmed against Atlassian's documentation, the
`atlassian-python-api` source, and the sibling tools; the **native export path is
unverified**. Confirm the key behaviors on a throwaway space before production use
(replace placeholders; the output contains live tokens/content — do not share it):

```bash
SITE="https://<your-site>.atlassian.net/wiki"; AUTH="<email>:<api_token>"
# read: body requires body-format
curl -su "$AUTH" "$SITE/api/v2/spaces?keys=SPACEKEY"
# write: confirm author/date are NOT settable (should be ignored / = now)
curl -su "$AUTH" -X POST "$SITE/api/v2/pages" -H 'Content-Type: application/json' \
  -d '{"spaceId":"<id>","status":"current","title":"rt-test","body":{"representation":"storage","value":"<p>hi</p>"}}'
```

### Round-trip status: verified

The REST backup→restore round-trip has been **proven end-to-end against a live
Confluence Cloud site**: a space was backed up, restored into a fresh space, and
diffed via the API — **page count, hierarchy, and attachment bytes all matched**.
The native XML export path remains unverified (see above).

### Proving a restore (round-trip checklist)

A backup is only proven once it has been **restored and verified**. On a non-prod
site:

1. `confluence-backup --backup SOURCE`
2. `confluence-backup --restore <dir> --target-key SCRATCH --dry-run` (review the plan)
3. `confluence-backup --restore <dir> --target-key SCRATCH`
4. Compare SCRATCH against SOURCE: page **count + hierarchy**, page **bodies**,
   **attachment count + sizes**, **comments**, **labels**.
5. Record what survived vs. didn't against the table above.

## Project layout

```
confluence_tool/
├── config.py        auth.py        api_client.py
├── backup.py        restore.py     macros.py        native_export.py
├── manifest.py      progress.py    export.py
├── menu.py          cli.py         utils.py         __init__.py
main.py              # clone entry point
```

## License

MIT — see [LICENSE](LICENSE).
