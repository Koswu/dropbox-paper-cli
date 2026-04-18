"""Dropbox service: async file/folder operations via DropboxHttpClient."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from dropbox_paper_cli.lib.errors import ValidationError
from dropbox_paper_cli.models.items import DropboxItem, PaperCreateResult, PaperUpdateResult

if TYPE_CHECKING:
    from dropbox_paper_cli.lib.http_client import DropboxHttpClient

_VALID_IMPORT_FORMATS = {"markdown", "html", "plain_text"}
_VALID_UPDATE_POLICIES = {"overwrite", "update", "prepend", "append"}


class DropboxService:
    """Wraps Dropbox API v2 file and folder operations.

    All methods are async and use DropboxHttpClient for HTTP communication.
    """

    def __init__(self, client: DropboxHttpClient) -> None:
        self._client = client

    # ── Browse Operations ─────────────────────────────────────────

    async def list_folder(self, path: str, *, recursive: bool = False) -> list[DropboxItem]:
        """List files and folders at a Dropbox path with pagination.

        Args:
            path: Dropbox path (empty string for root).
            recursive: If True, list all items recursively.

        Returns:
            List of DropboxItem objects.
        """
        if path == "/":
            path = ""
        result = await self._client.rpc(
            "files/list_folder",
            {"path": path, "recursive": recursive},
        )
        items: list[DropboxItem] = []
        items.extend(DropboxItem.from_api(entry) for entry in result["entries"])

        while result.get("has_more"):
            result = await self._client.rpc(
                "files/list_folder/continue",
                {"cursor": result["cursor"]},
            )
            items.extend(DropboxItem.from_api(entry) for entry in result["entries"])

        return items

    async def get_metadata(self, path: str) -> DropboxItem:
        """Get metadata for a specific file or folder.

        Raises:
            NotFoundError: If the path does not exist.
        """
        result = await self._get_metadata_raw(path)
        return DropboxItem.from_api(result)

    async def get_shared_folder_id(self, path: str) -> str | None:
        """Get the shared_folder_id for a folder, or None if not shared."""
        result = await self._get_metadata_raw(path)
        sharing_info = result.get("sharing_info", {})
        return sharing_info.get("shared_folder_id")

    async def _get_metadata_raw(self, path: str) -> dict:
        """Fetch raw metadata dict from Dropbox API."""
        return await self._client.rpc("files/get_metadata", {"path": path})

    async def get_or_create_sharing_link(self, path: str) -> dict[str, str]:
        """Get or create a sharing link for a file.

        Returns:
            Dict with url, name, and id keys.
        """
        try:
            result = await self._client.rpc(
                "sharing/create_shared_link_with_settings",
                {"path": path, "settings": {}},
            )
            return {"url": result["url"], "name": result["name"], "id": result["id"]}
        except ValidationError as e:
            msg = str(e)
            if "shared_link_already_exists" in msg:
                # Parse the existing link from the error body
                body_json = msg.split(":", 1)[1] if ":" in msg else "{}"
                try:
                    body = json.loads(body_json)
                    existing = (
                        body.get("error", {})
                        .get("shared_link_already_exists", {})
                        .get("metadata", {})
                    )
                    if existing:
                        return {
                            "url": existing["url"],
                            "name": existing["name"],
                            "id": existing["id"],
                        }
                except (json.JSONDecodeError, KeyError):
                    pass
            raise

    # ── Organize Operations ───────────────────────────────────────

    async def move_item(self, from_path: str, to_path: str) -> DropboxItem:
        """Move a file or folder."""
        result = await self._client.rpc(
            "files/move_v2",
            {"from_path": from_path, "to_path": to_path},
        )
        return DropboxItem.from_api(result["metadata"])

    async def copy_item(self, from_path: str, to_path: str) -> DropboxItem:
        """Copy a file or folder."""
        result = await self._client.rpc(
            "files/copy_v2",
            {"from_path": from_path, "to_path": to_path},
        )
        return DropboxItem.from_api(result["metadata"])

    async def delete_item(self, path: str) -> DropboxItem:
        """Delete a file or folder."""
        result = await self._client.rpc("files/delete_v2", {"path": path})
        return DropboxItem.from_api(result["metadata"])

    async def create_folder(self, path: str) -> DropboxItem:
        """Create a new folder."""
        result = await self._client.rpc("files/create_folder_v2", {"path": path})
        return DropboxItem.from_api(result["metadata"])

    # ── Read Content ──────────────────────────────────────────────

    async def export_paper_content(self, path: str) -> str:
        """Export a Paper document as Markdown.

        Returns:
            Markdown string content.
        """
        content_bytes, _metadata = await self._client.content_download(
            "files/export",
            {"path": path, "export_format": "markdown"},
        )
        return content_bytes.decode()

    # ── URL Resolution ────────────────────────────────────────────

    async def resolve_shared_link_url(self, url: str) -> str:
        """Resolve a Dropbox shared link URL to a file/folder ID."""
        result = await self._client.rpc(
            "sharing/get_shared_link_metadata",
            {"url": url},
        )
        return result["id"]

    # ── Write Content ─────────────────────────────────────────────

    async def create_paper_doc(
        self,
        path: str,
        content: bytes,
        *,
        import_format: str = "markdown",
    ) -> PaperCreateResult:
        """Create a new Paper document.

        Args:
            path: Dropbox path (must end with .paper).
            content: Document content as bytes.
            import_format: "markdown", "html", or "plain_text".
        """
        if import_format not in _VALID_IMPORT_FORMATS:
            raise ValidationError(
                f"Invalid import format: {import_format!r}. "
                f"Choose from: {', '.join(sorted(_VALID_IMPORT_FORMATS))}"
            )
        result = await self._client.content_upload(
            "files/paper/create",
            {"path": path, "import_format": {".tag": import_format}},
            content,
            host="api",
        )
        return PaperCreateResult.from_api(result)

    async def update_paper_doc(
        self,
        path: str,
        content: bytes,
        *,
        import_format: str = "markdown",
        policy: str = "overwrite",
        paper_revision: int | None = None,
    ) -> PaperUpdateResult:
        """Update an existing Paper document's content.

        Args:
            path: Dropbox path or file ID.
            content: New document content as bytes.
            import_format: "markdown", "html", or "plain_text".
            policy: "overwrite", "update", "prepend", or "append".
            paper_revision: Required when policy is "update".
        """
        if import_format not in _VALID_IMPORT_FORMATS:
            raise ValidationError(
                f"Invalid import format: {import_format!r}. "
                f"Choose from: {', '.join(sorted(_VALID_IMPORT_FORMATS))}"
            )
        if policy not in _VALID_UPDATE_POLICIES:
            raise ValidationError(
                f"Invalid update policy: {policy!r}. Choose from: {', '.join(sorted(_VALID_UPDATE_POLICIES))}"
            )
        if policy == "update" and paper_revision is None:
            raise ValidationError("--revision is required when policy is 'update'")
        params: dict = {
            "path": path,
            "import_format": {".tag": import_format},
            "doc_update_policy": {".tag": policy},
        }
        if paper_revision is not None:
            params["paper_revision"] = paper_revision
        result = await self._client.content_upload(
            "files/paper/update",
            params,
            content,
            host="api",
        )
        return PaperUpdateResult.from_api(result)
