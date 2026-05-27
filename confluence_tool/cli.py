# cli.py — Command-line entry point (interactive menu + argparse automation)
# Author: David Malko
# Date: 2026-05-27
# Version: 1.0.0

"""Entry point. With no actionable flags it launches the interactive menu;
with flags it runs non-interactively for automation/CI.

Exit codes:  0 = success · 1 = failure · 2 = bad/insufficient arguments.
"""

import argparse
import sys
from pathlib import Path

from confluence_tool import __version__
from confluence_tool.api_client import ConfluenceClient
from confluence_tool.auth import build_session
from confluence_tool.config import ConfluenceConfig, load_config
from confluence_tool.utils import setup_logging


def build_client(config: ConfluenceConfig) -> ConfluenceClient:
    """Construct an authenticated ConfluenceClient from config."""
    session = build_session(config)
    return ConfluenceClient(session, config.confluence_url, config)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="confluence-backup",
        description="Backup and restore individual Confluence Cloud spaces via REST.",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    parser.add_argument("--env", metavar="PATH", help="Path to the .env file (default: ./.env)")

    # Backup & restore
    parser.add_argument("--backup", metavar="KEY[,KEY...]",
                        help="Back up one or more space keys (comma-separated)")
    parser.add_argument("--restore", metavar="DIR", help="Restore from a backup directory")
    parser.add_argument("--target-key", metavar="KEY",
                        help="Target space key for restore (required with --restore)")
    parser.add_argument("--target-name", metavar="NAME", help="Target space name for restore")
    parser.add_argument("--overwrite", action="store_true",
                        help="Allow restoring INTO an existing space (guarded by confirmation)")
    parser.add_argument("--dry-run", action="store_true",
                        help="Preview a restore without writing anything")

    # Browse & analyze
    parser.add_argument("--list", action="store_true", help="List existing backups and exit")
    parser.add_argument("--validate", metavar="DIR", help="Validate a backup's integrity and exit")
    parser.add_argument("--export-csv", metavar="DIR", help="Export a backup directory to CSV")

    # Toggles
    parser.add_argument("--native-export", action="store_true",
                        help="Also attempt a native XML export (best-effort, undocumented)")
    parser.add_argument("--no-attachments", action="store_true",
                        help="Skip attachment binaries during backup")
    parser.add_argument("--include-versions", action="store_true",
                        help="Save page version metadata sidecar during backup")
    return parser


def _apply_overrides(config: ConfluenceConfig, args: argparse.Namespace) -> None:
    """Let CLI flags override .env toggles."""
    if args.native_export:
        config.native_export = True
    if args.no_attachments:
        config.include_attachments = False
    if args.include_versions:
        config.include_versions = True


def confirm_overwrite(target_key: str) -> bool:
    """Require the operator to type the space key to authorize an overwrite.

    Non-interactive sessions (no TTY) treat the explicit --overwrite flag as the
    authorization, so automation isn't blocked.
    """
    if not sys.stdin.isatty():
        print(f"[INFO] Non-interactive: honoring --overwrite for '{target_key}'.")
        return True
    print(f"[!] This will modify the EXISTING space '{target_key}'.")
    typed = input(f"    Type the space key '{target_key}' to confirm: ").strip()
    return typed == target_key


def main(argv: list[str] | None = None) -> int:
    """Program entry point. Returns a process exit code."""
    args = _build_parser().parse_args(argv)
    config = load_config(args.env)
    _apply_overrides(config, args)
    logger = setup_logging(log_dir=config.backup_root)

    # Actions that need no live connection.
    if args.list:
        from confluence_tool.menu import print_backup_list
        print_backup_list(config.backup_root)
        return 0
    if args.validate:
        from confluence_tool import manifest
        ok, issues = manifest.validate(Path(args.validate))
        for issue in issues:
            logger.warning("  - %s", issue)
        logger.info("Backup integrity: %s", "OK" if ok else "FAILED")
        return 0 if ok else 1
    if args.export_csv:
        from confluence_tool.export import export_backup_to_csv
        written = export_backup_to_csv(args.export_csv)
        for name, rows in written.items():
            logger.info("  %s: %d rows", name, rows)
        return 0

    # Actions that need a connection.
    if args.backup:
        from confluence_tool.backup import BackupManager
        client = build_client(config)
        manager = BackupManager(client, config)
        ok_all = True
        for key in [k.strip() for k in args.backup.split(",") if k.strip()]:
            if manager.backup_space(key) is None:
                ok_all = False
        return 0 if ok_all else 1

    if args.restore:
        if not args.target_key:
            logger.error("--restore requires --target-key")
            return 2
        from confluence_tool.restore import RestoreManager
        client = build_client(config)
        if args.overwrite and not args.dry_run and not confirm_overwrite(args.target_key):
            logger.error("Overwrite not confirmed; aborting.")
            return 1
        manager = RestoreManager(client, config, dry_run=args.dry_run)
        ok = manager.restore(
            args.restore, args.target_key,
            target_name=args.target_name, overwrite=args.overwrite,
        )
        return 0 if ok else 1

    # No actionable flag -> interactive menu.
    from confluence_tool.menu import run_menu
    run_menu(config)
    return 0


if __name__ == "__main__":
    sys.exit(main())
