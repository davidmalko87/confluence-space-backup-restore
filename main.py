#!/usr/bin/env python3
# main.py — Entry point for Confluence Space Backup & Restore Tool (repo clone usage)
# Author: David Malko
# Date: 2026-05-27
# Version: 1.0.0

"""Confluence Cloud per-space Backup & Restore Tool.

Usage:
    python main.py                                  # Interactive menu
    python main.py --backup SPACEKEY                # Backup a space (non-interactive)
    python main.py --backup KEY1,KEY2               # Backup multiple spaces
    python main.py --restore DIR --target-key NEW   # Restore into a NEW space
    python main.py --restore DIR --target-key NEW --dry-run
"""

from confluence_tool.cli import main

if __name__ == "__main__":
    main()
