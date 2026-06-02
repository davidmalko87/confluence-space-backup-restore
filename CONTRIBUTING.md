# Contributing

## Versioning

This project uses [Semantic Versioning](https://semver.org/) (`MAJOR.MINOR.PATCH`):

| Change type | Bump | Example |
|---|---|---|
| Backward-incompatible change | MAJOR | `1.x.x` → `2.0.0` |
| New backward-compatible feature | MINOR | `1.2.x` → `1.3.0` |
| Bug fix or small improvement | PATCH | `1.2.1` → `1.2.2` |

### How to bump the version

1. **Edit `confluence_tool/__init__.py`** — the single source of truth:
   ```python
   __version__ = "1.0.1"   # update this line
   ```
   `pyproject.toml` reads this dynamically (`[tool.setuptools.dynamic]`), and it
   also appears in the interactive menu header and every backup `manifest.json`
   (`tool_version` field).

2. **Add an entry to `CHANGELOG.md`** at the top of the file:
   ```markdown
   ## [1.0.1] - YYYY-MM-DD

   ### Fixed
   - Short description of the change.
   ```

Both files must be updated together in the same commit as the change that
warrants the bump.

---

## Publishing a release

Releases publish to PyPI automatically via **Trusted Publishing (OIDC)** — there
are no API tokens or repository secrets. The `Publish to PyPI` workflow
(`.github/workflows/publish.yml`) runs whenever a `v*` tag is pushed.

> **One-time setup** (see the README / repo maintainer notes): a *pending*
> Trusted Publisher must be registered on PyPI and a GitHub deployment
> environment named `pypi` must exist before the first release.

1. Bump the version and update docs:
   - `confluence_tool/__init__.py` — update `__version__`
   - `CHANGELOG.md` — add a new entry at the top
2. Commit and push to `main`:
   ```bash
   git add confluence_tool/__init__.py CHANGELOG.md
   git commit -m "Bump version to X.Y.Z"
   git push
   ```
3. **Create a GitHub Release** — this is what publishes to PyPI. Either:
   - On GitHub: **Releases → Create a new release** → choose/create the tag
     `vX.Y.Z` (must match `__version__`, prefixed with `v`) → title `vX.Y.Z` →
     paste the new `CHANGELOG.md` section as the description → **Publish release**.
   - Or via CLI:
     ```bash
     gh release create vX.Y.Z --title "vX.Y.Z" --latest --notes "…changelog section…"
     ```
   Publishing the release creates the tag (if needed), marks it **Latest**, and
   triggers the `Publish to PyPI` workflow.
4. Watch **Actions → Publish to PyPI**. If the `pypi` environment has a
   protection rule, approve the run. Verify at
   <https://pypi.org/project/confluence-space-backup-restore/>.

> The publish workflow triggers on a **published GitHub Release** (not a bare
> tag push), so the release and the PyPI upload happen in one step.

> ⚠️ **PyPI versions are immutable** — a version can never be re-uploaded or
> replaced, even after deletion. Any change requires a **new** version number.
