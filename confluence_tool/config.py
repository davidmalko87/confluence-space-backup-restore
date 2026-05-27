# config.py — Load and validate configuration from .env
# Author: David Malko
# Date: 2026-05-27
# Version: 1.0.0

"""Configuration loader for the Confluence Space Backup & Restore Tool.

Reads settings from a .env file using python-dotenv. All credentials and
tunables are centralized here. Nothing site-specific is ever hardcoded.
"""

import os
import sys
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


@dataclass
class ConfluenceConfig:
    """All configuration for the Confluence Space Backup & Restore tool."""

    # Confluence instance
    confluence_url: str = ""          # MUST include the /wiki suffix
    email: str = ""
    api_token: str = ""
    cookie_header: str = ""
    verify_ssl: bool = True

    # Backup settings
    backup_root: str = "./backups"
    page_size: int = 250              # Confluence Cloud v2 caps at 250
    max_retries: int = 5
    read_timeout: int = 30            # seconds per request; 0 = no timeout
    api_delay: float = 0.2
    chunk_size: int = 8 * 1024 * 1024  # 8 MiB streaming chunk
    body_format: str = "storage"      # storage | atlas_doc_format

    # Backup toggles
    include_attachments: bool = True
    include_comments: bool = True
    include_blogposts: bool = True
    include_restrictions: bool = True
    include_versions: bool = False    # metadata sidecar only; never replayed

    # Native XML export (optional, off by default — fragile undocumented path)
    native_export: bool = False
    native_export_timeout: int = 1800

    def validate(self) -> list[str]:
        """Return a list of validation errors (empty when the config is valid).

        Also normalizes ``confluence_url`` in place: strips a trailing slash and
        appends the required ``/wiki`` suffix if the user omitted it.
        """
        errors: list[str] = []

        if not self.confluence_url:
            errors.append("CONFLUENCE_URL is required (e.g. https://you.atlassian.net/wiki)")
        else:
            self.confluence_url = self.confluence_url.rstrip("/")
            if not self.confluence_url.endswith("/wiki"):
                # The v2/v1 API lives under /wiki; add it so callers needn't.
                self.confluence_url = self.confluence_url + "/wiki"

        if not self.api_token and not self.cookie_header:
            errors.append("Either CONFLUENCE_API_TOKEN or CONFLUENCE_COOKIE_HEADER must be set")

        if self.api_token and not self.email:
            errors.append("CONFLUENCE_EMAIL is required when using API token auth")

        if self.page_size < 1 or self.page_size > 250:
            errors.append("PAGE_SIZE must be between 1 and 250")

        if self.body_format not in ("storage", "atlas_doc_format"):
            errors.append("BODY_FORMAT must be 'storage' or 'atlas_doc_format'")

        return errors

    @property
    def site_origin(self) -> str:
        """Scheme + host (no path), e.g. https://you.atlassian.net."""
        url = self.confluence_url
        if "://" in url:
            scheme, rest = url.split("://", 1)
            host = rest.split("/", 1)[0]
            return f"{scheme}://{host}"
        return url

    @property
    def site_slug(self) -> str:
        """Short host label for manifests/logs, e.g. 'you' from you.atlassian.net."""
        host = self.site_origin.split("://")[-1]
        return host.split(".")[0] if host else ""


def load_config(env_path: str | None = None) -> ConfluenceConfig:
    """Load configuration from a .env file.

    Args:
        env_path: Path to the .env file; defaults to ./.env.

    Returns:
        A populated, validated ConfluenceConfig.

    Raises:
        SystemExit: If the .env file is missing or validation fails (exit 1).
    """
    dotenv_path = Path(env_path) if env_path else Path(".env")

    if not dotenv_path.exists():
        print(f"[!] Config file not found: {dotenv_path.resolve()}")
        print("    Copy .env.example to .env and fill in your values.")
        sys.exit(1)

    load_dotenv(dotenv_path)

    def _bool(key: str, default: bool = True) -> bool:
        return os.getenv(key, str(default)).strip().lower() in ("true", "1", "yes")

    def _int(key: str, default: int) -> int:
        try:
            return int(os.getenv(key, str(default)))
        except ValueError:
            return default

    def _float(key: str, default: float) -> float:
        try:
            return float(os.getenv(key, str(default)))
        except ValueError:
            return default

    config = ConfluenceConfig(
        confluence_url=os.getenv("CONFLUENCE_URL", ""),
        email=os.getenv("CONFLUENCE_EMAIL", ""),
        api_token=os.getenv("CONFLUENCE_API_TOKEN", ""),
        cookie_header=os.getenv("CONFLUENCE_COOKIE_HEADER", ""),
        verify_ssl=_bool("CONFLUENCE_VERIFY_SSL", True),
        backup_root=os.getenv("BACKUP_ROOT", "./backups"),
        page_size=_int("PAGE_SIZE", 250),
        max_retries=_int("MAX_RETRIES", 5),
        read_timeout=_int("READ_TIMEOUT", 30),
        api_delay=_float("API_DELAY", 0.2),
        chunk_size=_int("CHUNK_SIZE", 8 * 1024 * 1024),
        body_format=os.getenv("BODY_FORMAT", "storage").strip().lower(),
        include_attachments=_bool("INCLUDE_ATTACHMENTS", True),
        include_comments=_bool("INCLUDE_COMMENTS", True),
        include_blogposts=_bool("INCLUDE_BLOGPOSTS", True),
        include_restrictions=_bool("INCLUDE_RESTRICTIONS", True),
        include_versions=_bool("INCLUDE_VERSIONS", False),
        native_export=_bool("NATIVE_EXPORT", False),
        native_export_timeout=_int("NATIVE_EXPORT_TIMEOUT", 1800),
    )

    errors = config.validate()
    if errors:
        print("[!] Configuration errors:")
        for err in errors:
            print(f"    - {err}")
        sys.exit(1)

    return config
