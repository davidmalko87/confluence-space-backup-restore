# auth.py — Build an authenticated requests.Session for the Confluence API
# Author: David Malko
# Date: 2026-05-27
# Version: 1.0.0

"""Session builder supporting API-token (Basic auth) with a cookie fallback.

Confluence Cloud's REST API accepts Basic auth (email + API token), which is
the recommended path and avoids the ~30-day session-cookie refresh toil. A raw
Cookie header is supported only as an SSO/SAML fallback.
"""

import requests
import urllib3

from confluence_tool import __version__
from confluence_tool.config import ConfluenceConfig

# A deliberately NON-browser User-Agent. Confluence's XSRF filter classifies any
# browser-like UA (one containing "Mozilla") as a browser request and then
# ignores the `X-Atlassian-Token: no-check` bypass — causing 403 "XSRF check
# failed" on multipart attachment uploads (verified empirically). A plain UA
# keeps the bypass effective and works for every REST and download call.
_USER_AGENT = f"confluence-space-backup-restore/{__version__}"


def build_session(config: ConfluenceConfig) -> requests.Session:
    """Create an authenticated requests.Session for Confluence Cloud.

    API token auth (recommended):
        HTTPBasicAuth with email + token.

    Cookie auth (fallback for SSO/SAML):
        Injects a raw Cookie header captured from browser DevTools.

    Args:
        config: A validated ConfluenceConfig.

    Returns:
        A configured requests.Session ready for API calls.

    Raises:
        ValueError: If no authentication method is configured.
    """
    if not config.verify_ssl:
        # Keep the console readable behind a TLS-intercepting corporate proxy.
        urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

    session = requests.Session()
    session.verify = config.verify_ssl
    session.headers.update({
        "Accept": "application/json",
        "User-Agent": _USER_AGENT,
        # Bypasses Atlassian's XSRF check for token-authenticated write/upload
        # calls (attachments, native export). Harmless on read calls.
        "X-Atlassian-Token": "no-check",
    })

    if config.api_token and config.email:
        session.auth = (config.email, config.api_token)
    elif config.cookie_header:
        session.headers["Cookie"] = config.cookie_header
    else:
        raise ValueError(
            "No authentication configured. "
            "Set CONFLUENCE_API_TOKEN + CONFLUENCE_EMAIL or CONFLUENCE_COOKIE_HEADER."
        )

    return session
