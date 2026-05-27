# menu.py — Interactive CLI menu (organized into sections)
# Author: David Malko
# Date: 2026-05-27
# Version: 1.0.0

"""The interactive front-end. Mirrors the sibling Jira tool's UX: three labelled
sections, "Press Enter to return to menu" pauses, and 'b' to go back from a
selection prompt.
"""

import logging
from pathlib import Path

from confluence_tool import __version__, manifest
from confluence_tool.api_client import ConfluenceApiError, ConfluenceClient
from confluence_tool.auth import build_session
from confluence_tool.backup import BackupManager, cleanup_incomplete, list_backups
from confluence_tool.config import ConfluenceConfig
from confluence_tool.export import export_backup_to_csv, get_backup_statistics
from confluence_tool.restore import RestoreManager
from confluence_tool.utils import format_size, info, ok, warn, error, print_kv, section

logger = logging.getLogger("confluence_tool")


def run_menu(config: ConfluenceConfig) -> None:
    """Run the interactive menu loop until the user exits."""
    client: ConfluenceClient | None = None

    def get_client() -> ConfluenceClient | None:
        nonlocal client
        if client is None:
            try:
                client = ConfluenceClient(build_session(config), config.confluence_url, config)
            except ValueError as exc:
                error(str(exc))
                return None
        return client

    while True:
        _print_header(config)
        choice = input("\n  Select an option: ").strip().lower()

        if choice == "1":
            _menu_backup(config, get_client())
        elif choice == "2":
            _menu_restore(config, get_client())
        elif choice == "3":
            print_backup_list(config.backup_root)
            _pause()
        elif choice == "4":
            _menu_validate(config)
        elif choice == "5":
            _menu_export_csv(config)
        elif choice == "6":
            _menu_inspect(config)
        elif choice == "7":
            _menu_test_connection(get_client())
        elif choice == "8":
            _menu_show_config(config)
        elif choice == "9":
            _menu_cleanup(config)
        elif choice == "0":
            print("  Goodbye.")
            return
        else:
            warn("Unknown option.")


# ----------------------------------------------------------------------
# Header + option handlers
# ----------------------------------------------------------------------

def _print_header(config: ConfluenceConfig) -> None:
    auth = "API token" if config.api_token else ("cookie" if config.cookie_header else "none")
    print("\n" + "=" * 62)
    print(f"  Confluence Space Backup & Restore  v{__version__}")
    print("=" * 62)
    print(f"  Site: {config.site_origin}   Auth: {auth}   Backups: {config.backup_root}")
    print("-" * 62)
    print("  --- Backup & Restore ---")
    print("   1) Backup space(s)")
    print("   2) Restore space from backup")
    print("  --- Browse & Analyze ---")
    print("   3) List existing backups")
    print("   4) Validate backup integrity")
    print("   5) Export backup to CSV")
    print("   6) Inspect backup details")
    print("  --- Settings & Tools ---")
    print("   7) Test Confluence connection")
    print("   8) Show current configuration")
    print("   9) Cleanup incomplete backups")
    print("   0) Exit")


def _menu_backup(config: ConfluenceConfig, client: ConfluenceClient | None) -> None:
    if client is None:
        _pause()
        return
    raw = input("  Space key(s) to back up (comma-separated, 'b' to cancel): ").strip()
    if raw.lower() == "b" or not raw:
        return
    manager = BackupManager(client, config)
    for key in [k.strip() for k in raw.split(",") if k.strip()]:
        try:
            result = manager.backup_space(key)
            if result:
                ok(f"Backed up '{key}' -> {result}")
            else:
                error(f"Backup failed for '{key}'.")
        except ConfluenceApiError as exc:
            error(f"Backup error for '{key}': {exc}")
    _pause()


def _menu_restore(config: ConfluenceConfig, client: ConfluenceClient | None) -> None:
    if client is None:
        _pause()
        return
    backup_dir = _select_backup(config.backup_root)
    if not backup_dir:
        return
    target_key = input("  Target space key (a NEW space is created by default): ").strip()
    if not target_key:
        warn("No target key; cancelled.")
        return
    dry = input("  Dry-run preview first? [Y/n]: ").strip().lower() != "n"

    overwrite = False
    if not dry:
        # Detect an existing target to decide whether overwrite confirmation is needed.
        existing = _space_exists(client, target_key)
        if existing:
            warn(f"Space '{target_key}' already exists.")
            if input("  Restore INTO it (overwrite)? [y/N]: ").strip().lower() == "y":
                typed = input(f"  Type the space key '{target_key}' to confirm: ").strip()
                overwrite = typed == target_key
                if not overwrite:
                    error("Confirmation failed; cancelled.")
                    return
            else:
                return

    manager = RestoreManager(client, config, dry_run=dry)
    try:
        success = manager.restore(backup_dir, target_key, overwrite=overwrite)
        ok("Restore finished.") if success else error("Restore failed (see log).")
    except ConfluenceApiError as exc:
        error(f"Restore error: {exc}")
    _pause()


def _menu_validate(config: ConfluenceConfig) -> None:
    backup_dir = _select_backup(config.backup_root)
    if not backup_dir:
        return
    valid, issues = manifest.validate(Path(backup_dir))
    if valid:
        ok("Backup integrity OK (all checksums match).")
    else:
        error("Backup integrity FAILED:")
        for issue in issues:
            print(f"    - {issue}")
    _pause()


def _menu_export_csv(config: ConfluenceConfig) -> None:
    backup_dir = _select_backup(config.backup_root)
    if not backup_dir:
        return
    written = export_backup_to_csv(backup_dir)
    ok(f"CSV written to {backup_dir}/csv_export:")
    for name, rows in written.items():
        print(f"    {name}: {rows} rows")
    _pause()


def _menu_inspect(config: ConfluenceConfig) -> None:
    backup_dir = _select_backup(config.backup_root)
    if not backup_dir:
        return
    stats = get_backup_statistics(backup_dir)
    section(f"Backup: {stats['space_key']}")
    rows = [
        ("Created", stats["created"]),
        ("Complete", str(stats["complete"])),
        ("Disk size", stats["size_human"]),
        ("Native export", str(stats["native_export"].get("present", False))),
    ]
    print_kv(rows)
    print("\n  Counts:")
    for key, value in sorted(stats["counts"].items()):
        print(f"    {key:<18} {value}")
    if stats["page_status_breakdown"]:
        print("\n  Page status:")
        for status, count in stats["page_status_breakdown"].items():
            print(f"    {status:<18} {count}")
    _pause()


def _menu_test_connection(client: ConfluenceClient | None) -> None:
    if client is None:
        _pause()
        return
    section("Connection test")
    try:
        user = client.get("/rest/api/user/current")
        ok(f"1/3 Authenticated as: {user.get('displayName', '(unknown)')}")
    except ConfluenceApiError as exc:
        error(f"1/3 Auth failed: {exc}")
        _pause()
        return
    try:
        spaces = client.get("/api/v2/spaces", params={"limit": 5}).get("results", [])
        ok(f"2/3 Read access OK ({len(spaces)} space(s) visible in sample).")
        for sp in spaces:
            print(f"      - {sp.get('key')}: {sp.get('name')}")
    except ConfluenceApiError as exc:
        error(f"2/3 Space listing failed: {exc}")
        _pause()
        return
    ok("3/3 Connection looks good.")
    _pause()


def _menu_show_config(config: ConfluenceConfig) -> None:
    section("Current configuration")
    print_kv([
        ("Site URL", config.confluence_url),
        ("Email", config.email or "(not set)"),
        ("API token", _mask(config.api_token)),
        ("Cookie auth", "set" if config.cookie_header else "(not set)"),
        ("Verify SSL", str(config.verify_ssl)),
        ("Backup root", config.backup_root),
        ("Page size", str(config.page_size)),
        ("Body format", config.body_format),
        ("Include attachments", str(config.include_attachments)),
        ("Include comments", str(config.include_comments)),
        ("Include blog posts", str(config.include_blogposts)),
        ("Include restrictions", str(config.include_restrictions)),
        ("Include versions", str(config.include_versions)),
        ("Native export", str(config.native_export)),
    ])
    _pause()


def _menu_cleanup(config: ConfluenceConfig) -> None:
    removed = cleanup_incomplete(config.backup_root)
    if removed:
        ok(f"Removed {len(removed)} incomplete backup(s):")
        for path in removed:
            print(f"    - {path}")
    else:
        info("No incomplete backups found.")
    _pause()


# ----------------------------------------------------------------------
# Shared helpers
# ----------------------------------------------------------------------

def print_backup_list(backup_root: str) -> None:
    """Print all backups with index, status, and size (shared with --list)."""
    backups = list_backups(backup_root)
    section(f"Backups in {backup_root}")
    if not backups:
        info("No backups found.")
        return
    for i, b in enumerate(backups, 1):
        flag = "complete" if b["complete"] else "INCOMPLETE"
        print(f"   {i:>2}) {b['name']:<32} {flag:<10} {format_size(b['size'])}")


def _select_backup(backup_root: str) -> str | None:
    """Prompt the user to pick a backup directory; return its path or None."""
    backups = list_backups(backup_root)
    if not backups:
        warn("No backups found.")
        return None
    print_backup_list(backup_root)
    raw = input("  Select a backup number ('b' to go back): ").strip().lower()
    if raw == "b" or not raw:
        return None
    try:
        idx = int(raw) - 1
        if 0 <= idx < len(backups):
            return backups[idx]["dir"]
    except ValueError:
        pass
    warn("Invalid selection.")
    return None


def _space_exists(client: ConfluenceClient, key: str) -> bool:
    try:
        data = client.get("/api/v2/spaces", params={"keys": key, "limit": 1})
        return bool(data.get("results"))
    except ConfluenceApiError:
        return False


def _mask(secret: str) -> str:
    if not secret:
        return "(not set)"
    if len(secret) <= 6:
        return "***"
    return f"{secret[:3]}...{secret[-2:]} ({len(secret)} chars)"


def _pause() -> None:
    input("\n  Press Enter to return to menu...")
