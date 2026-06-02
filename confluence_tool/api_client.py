# api_client.py — HTTP client for the Confluence REST API
# Author: David Malko
# Date: 2026-05-27
# Version: 1.0.0

"""ConfluenceClient wraps a requests.Session with exponential backoff, 429
rate-limit handling (Retry-After), cursor pagination (v2) and offset pagination
(v1 fallback), streaming downloads, and multipart uploads.
"""

import logging
import os
import time
from typing import Any, Iterator
from urllib.parse import parse_qs, urlparse

import requests
from requests.exceptions import ChunkedEncodingError, ConnectionError, ReadTimeout

from confluence_tool.config import ConfluenceConfig

logger = logging.getLogger("confluence_tool")

# Transient HTTP status codes worth retrying.
RETRYABLE_STATUS = {429, 500, 502, 503, 504}


class ConfluenceApiError(Exception):
    """Raised when the Confluence API returns a non-retryable error.

    The truncated body aids debugging but may contain space content, so it must
    only ever reach the gitignored DEBUG log, never a committed artifact.
    """

    def __init__(self, status_code: int, url: str, body: str) -> None:
        self.status_code = status_code
        self.url = url
        self.body = body
        super().__init__(f"HTTP {status_code} from {url}: {body[:300]}")


class ConfluenceClient:
    """HTTP client for the Confluence Cloud REST API.

    Paths passed to the methods are relative to the configured ``/wiki`` base,
    e.g. ``/api/v2/spaces`` (v2) or ``/rest/api/space`` (v1 fallback).
    """

    def __init__(
        self,
        session: requests.Session,
        base_url: str,
        config: ConfluenceConfig,
    ) -> None:
        self.session = session
        self.base_url = base_url.rstrip("/")
        self.config = config
        # Scheme://host with no path, for resolving site-root-relative links
        # (some download links already include the /wiki context path).
        parsed = urlparse(self.base_url)
        self.origin = f"{parsed.scheme}://{parsed.netloc}"

    # ------------------------------------------------------------------
    # Core HTTP verbs
    # ------------------------------------------------------------------

    def get(self, path: str, params: dict | None = None) -> dict:
        """GET with retry and rate-limit handling. Returns parsed JSON."""
        return self._request("GET", path, params=params)

    def post(self, path: str, body: Any = None) -> dict:
        """POST JSON (dict or list) with retry and rate-limit handling."""
        return self._request("POST", path, json_body=body)

    def put(self, path: str, body: Any = None) -> dict:
        """PUT JSON (dict or list) with retry and rate-limit handling."""
        return self._request("PUT", path, json_body=body)

    def delete(self, path: str, params: dict | None = None) -> dict:
        """DELETE with retry and rate-limit handling."""
        return self._request("DELETE", path, params=params)

    # ------------------------------------------------------------------
    # Pagination
    # ------------------------------------------------------------------

    def paginate_iter(
        self,
        path: str,
        params: dict | None = None,
        result_key: str = "results",
        page_size: int | None = None,
    ) -> Iterator[dict]:
        """Yield items from a cursor-paginated v2 endpoint, one at a time.

        Confluence v2 returns an opaque cursor in ``_links.next``; the correct
        approach is to extract that cursor query param and resend it (never
        build cursors by hand). Yielding instead of accumulating keeps memory
        flat on large spaces.

        Args:
            path: API path (e.g. /api/v2/spaces/{id}/pages).
            params: Base query params (limit/cursor are managed here).
            result_key: JSON key holding the page of items (v2 uses "results").
            page_size: Override page size for this call.

        Yields:
            Each item dict across all pages.
        """
        size = page_size or self.config.page_size
        query = dict(params or {})
        query["limit"] = size

        while True:
            data = self.get(path, params=query)
            items = data.get(result_key) or []
            for item in items:
                yield item

            next_href = (data.get("_links") or {}).get("next")
            if not next_href or not items:
                break
            cursor = _extract_query_param(next_href, "cursor")
            if not cursor:
                break
            query["cursor"] = cursor

    def paginate(
        self,
        path: str,
        params: dict | None = None,
        result_key: str = "results",
        page_size: int | None = None,
    ) -> list[dict]:
        """Collect all items from a cursor-paginated v2 endpoint into a list.

        Convenience for small collections (spaces, labels, permissions). For
        large collections (pages, comments, attachments) prefer paginate_iter
        and stream to disk.
        """
        return list(self.paginate_iter(path, params, result_key, page_size))

    def paginate_offset(
        self,
        path: str,
        params: dict | None = None,
        result_key: str = "results",
        page_size: int | None = None,
    ) -> list[dict]:
        """Collect all items from an offset-paginated v1 endpoint (start/limit).

        Used for v1-only data (page restrictions, templates) that has no v2
        equivalent.
        """
        all_items: list[dict] = []
        start = 0
        size = page_size or self.config.page_size
        base = dict(params or {})

        while True:
            page = {**base, "start": start, "limit": size}
            data = self.get(path, params=page)
            items = data.get(result_key) or []
            all_items.extend(items)
            if len(items) < size or not items:
                break
            start += size

        return all_items

    # ------------------------------------------------------------------
    # Binary transfer
    # ------------------------------------------------------------------

    def download_file(self, url: str, dest_path: str) -> bool:
        """Stream a file (e.g. an attachment) to disk, following redirects.

        Attachment download links usually 302-redirect to a pre-signed media
        URL; requests follows redirects and carries auth. A link may be absolute,
        already include the /wiki context path, or be relative to /wiki — all
        three are resolved here. Returns True on success, False after retries.
        """
        if url.startswith("http"):
            pass
        elif url.startswith("/wiki/"):
            url = self.origin + url
        elif url.startswith("/"):
            url = self.base_url + url

        # Binary endpoints 302-redirect to a presigned media.atlassian.com URL.
        # requests follows it and strips the Authorization header on the
        # cross-host hop (correct — the media URL is presigned). Override Accept
        # so a content-negotiating endpoint streams bytes, not a JSON error.
        dl_headers = {"Accept": "*/*"}

        for attempt in range(1, self.config.max_retries + 1):
            try:
                resp = self.session.get(
                    url, stream=True, timeout=(10, 600), headers=dl_headers,
                )

                if resp.status_code == 429:
                    self._handle_rate_limit(resp, attempt)
                    continue
                if resp.status_code != 200:
                    logger.warning(
                        "Download HTTP %d attempt %d/%d: %s",
                        resp.status_code, attempt, self.config.max_retries, url,
                    )
                    if attempt < self.config.max_retries:
                        time.sleep(min(2 ** attempt, 30))
                    continue

                os.makedirs(os.path.dirname(dest_path) or ".", exist_ok=True)
                with open(dest_path, "wb") as f:
                    for chunk in resp.iter_content(chunk_size=self.config.chunk_size):
                        if chunk:
                            f.write(chunk)
                logger.debug("Downloaded: %s", dest_path)
                return True

            except (ChunkedEncodingError, ConnectionError, ReadTimeout) as exc:
                logger.warning(
                    "Download error %d/%d: %s — %s",
                    attempt, self.config.max_retries, url, exc,
                )
            except OSError as exc:
                logger.error("Filesystem error downloading %s: %s", url, exc)
                break

            # Remove any partial file before the next attempt.
            if os.path.exists(dest_path):
                try:
                    os.remove(dest_path)
                except OSError:
                    pass

        return False

    def upload_file(
        self,
        path: str,
        file_path: str,
        filename: str | None = None,
        extra_fields: dict | None = None,
    ) -> dict:
        """Upload a file as multipart form data (v1 attachment endpoint).

        Uses **PUT**, which is idempotent: it adds the attachment or, if one with
        the same filename already exists, stores a new version. (POST creates
        only and 400s on a duplicate name, which breaks re-runnable restores.)

        Confluence requires the ``X-Atlassian-Token: no-check`` header for
        multipart uploads; the session sets it globally and we reassert it here.
        The session's non-browser User-Agent is essential — a browser-like UA
        makes the XSRF filter reject the no-check bypass (see auth.py).

        Args:
            path: API path (e.g. /rest/api/content/{id}/child/attachment).
            file_path: Local path to the file.
            filename: Filename sent to Confluence (default: basename).
            extra_fields: Additional form fields (e.g. {"minorEdit": "true"}).

        Returns:
            Parsed JSON response.

        Raises:
            ConfluenceApiError: On a non-retryable HTTP error or exhausted retries.
        """
        if filename is None:
            filename = os.path.basename(file_path)
        url = f"{self.base_url}{path}"
        headers = {"X-Atlassian-Token": "no-check"}

        for attempt in range(1, self.config.max_retries + 1):
            try:
                with open(file_path, "rb") as f:
                    files: dict[str, Any] = {"file": (filename, f)}
                    resp = self.session.put(
                        url, headers=headers, files=files, data=extra_fields or {},
                    )
                time.sleep(self.config.api_delay)

                if resp.status_code in (200, 201):
                    try:
                        return resp.json() if resp.text else {}
                    except ValueError:
                        return {}
                if resp.status_code == 429:
                    self._handle_rate_limit(resp, attempt)
                    continue
                if resp.status_code in RETRYABLE_STATUS:
                    logger.warning(
                        "Upload retry %d/%d for %s: HTTP %d",
                        attempt, self.config.max_retries, filename, resp.status_code,
                    )
                    time.sleep(min(2 ** attempt, 30))
                    continue
                raise ConfluenceApiError(resp.status_code, url, resp.text)

            except (ConnectionError, ReadTimeout) as exc:
                logger.warning(
                    "Upload connection error %d/%d for %s: %s",
                    attempt, self.config.max_retries, filename, exc,
                )
                if attempt == self.config.max_retries:
                    raise
                time.sleep(min(2 ** attempt, 30))

        raise ConfluenceApiError(0, url, "Max retries exceeded for upload")

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _request(
        self,
        method: str,
        path: str,
        params: dict | None = None,
        json_body: Any = None,
    ) -> dict:
        """Execute an HTTP request with retry and rate-limit handling."""
        url = f"{self.base_url}{path}"

        for attempt in range(1, self.config.max_retries + 1):
            try:
                resp = self.session.request(
                    method, url,
                    params=params,
                    json=json_body,
                    timeout=self.config.read_timeout or None,
                )
                time.sleep(self.config.api_delay)
                logger.debug("%s %s -> %d", method, path, resp.status_code)

                # 202 Accepted is returned by async operations (e.g. space delete).
                if resp.status_code in (200, 201, 202, 204):
                    if resp.status_code in (202, 204) or not resp.text:
                        return {}
                    try:
                        return resp.json()
                    except ValueError:
                        # A 2xx with a non-JSON body must not crash a long restore.
                        logger.debug("Non-JSON 2xx from %s %s: %.120s",
                                     method, path, resp.text)
                        return {}
                if resp.status_code == 429:
                    self._handle_rate_limit(resp, attempt)
                    continue
                if resp.status_code in RETRYABLE_STATUS:
                    wait = min(2 ** attempt, 30)
                    logger.warning(
                        "Retry %d/%d: %s %s -> %d",
                        attempt, self.config.max_retries, method, path, resp.status_code,
                    )
                    time.sleep(wait)
                    continue

                raise ConfluenceApiError(resp.status_code, url, resp.text)

            except (ConnectionError, ReadTimeout) as exc:
                logger.warning(
                    "Connection error %d/%d: %s %s — %s",
                    attempt, self.config.max_retries, method, path, exc,
                )
                if attempt == self.config.max_retries:
                    raise
                time.sleep(min(2 ** attempt, 30))

        raise ConfluenceApiError(0, url, "Max retries exceeded")

    def _handle_rate_limit(self, resp: requests.Response, attempt: int) -> None:
        """Sleep per the Retry-After header, or exponential backoff if absent."""
        retry_after = resp.headers.get("Retry-After")
        if retry_after:
            try:
                wait = int(retry_after)
            except ValueError:
                wait = min(2 ** attempt, 60)
        else:
            wait = min(2 ** attempt, 60)
        logger.warning(
            "Rate limited (429). Waiting %ds before retry %d/%d.",
            wait, attempt, self.config.max_retries,
        )
        time.sleep(wait)


def _extract_query_param(href: str, key: str) -> str | None:
    """Return a single query-parameter value from a URL or path, or None."""
    try:
        qs = parse_qs(urlparse(href).query)
    except ValueError:
        return None
    values = qs.get(key)
    return values[0] if values else None
