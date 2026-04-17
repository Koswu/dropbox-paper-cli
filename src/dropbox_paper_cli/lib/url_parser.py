"""resolve_target(): URL detection, raw ID passthrough, path normalization."""

from __future__ import annotations

import re

# Pattern to detect any Dropbox URL
_DROPBOX_URL_RE = re.compile(r"https?://(?:www\.)?dropbox\.com/")


def is_dropbox_url(target: str) -> bool:
    """Check if a target string is a Dropbox URL."""
    return bool(_DROPBOX_URL_RE.match(target))


def resolve_target(target: str) -> str:
    """Resolve a user-provided target to a Dropbox path or ID.

    For URLs, this returns the raw URL — the caller must use
    DropboxService.resolve_shared_link_url() to convert to a file ID.

    Resolution order:
    1. Dropbox URL → return as-is (needs SDK resolution)
    2. Raw ID (starts with 'id:') → passthrough
    3. Everything else → treat as Dropbox path
    """
    # URLs are returned as-is; the CLI layer resolves them via the SDK
    if is_dropbox_url(target):
        return target

    # Raw ID or path passthrough
    return target
