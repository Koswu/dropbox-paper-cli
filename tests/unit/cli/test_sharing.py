"""Tests for sharing CLI info command."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from typer.testing import CliRunner

from dropbox_paper_cli.app import app
from dropbox_paper_cli.lib.errors import NotFoundError
from dropbox_paper_cli.models.sharing import MemberInfo, SharingInfo


@pytest.fixture
def runner():
    return CliRunner()


@pytest.fixture
def mock_services():
    """Patch the HTTP client and services used by async sharing CLI commands.

    The CLI commands now use this pattern:
        client = _get_services()
        async with client:
            dbx_svc = DropboxService(client=client)
            share_svc = SharingService(client=client)
            result = await dbx_svc.some_method(...)
    We patch _get_services to return an async-context-manager mock,
    and patch DropboxService / SharingService constructors to return
    shared mock services whose methods are AsyncMock.
    """
    mock_client = MagicMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    dbx_svc = MagicMock()
    dbx_svc.get_shared_folder_id = AsyncMock()
    dbx_svc.resolve_shared_link_url = AsyncMock()

    share_svc = MagicMock()
    share_svc.get_sharing_info = AsyncMock()

    with (
        patch("dropbox_paper_cli.cli.sharing._get_services", return_value=mock_client),
        patch("dropbox_paper_cli.cli.sharing.DropboxService", return_value=dbx_svc),
        patch("dropbox_paper_cli.cli.sharing.SharingService", return_value=share_svc),
    ):
        yield dbx_svc, share_svc


class TestSharingInfo:
    """paper sharing info <TARGET>"""

    def test_info_success(self, runner, mock_services):
        dbx_svc, share_svc = mock_services

        dbx_svc.get_shared_folder_id.return_value = "sf:123"

        share_svc.get_sharing_info.return_value = SharingInfo(
            shared_folder_id="sf:123",
            name="Project Notes",
            path_display="/Project Notes",
            members=[
                MemberInfo("dbid:1", "Jane Doe", "jane@ex.com", "owner"),
                MemberInfo("dbid:2", "Bob Smith", "bob@ex.com", "editor"),
            ],
        )

        result = runner.invoke(app, ["sharing", "info", "/Project Notes"])
        assert result.exit_code == 0
        assert "Project Notes" in result.stdout
        assert "Jane Doe" in result.stdout
        assert "owner" in result.stdout

    def test_info_json_output(self, runner, mock_services):
        dbx_svc, share_svc = mock_services

        dbx_svc.get_shared_folder_id.return_value = "sf:123"

        share_svc.get_sharing_info.return_value = SharingInfo(
            shared_folder_id="sf:123",
            name="Project Notes",
            members=[
                MemberInfo("dbid:1", "Jane Doe", "jane@ex.com", "owner"),
            ],
        )

        result = runner.invoke(app, ["--json", "sharing", "info", "/Project Notes"])
        assert result.exit_code == 0
        data = json.loads(result.stdout)
        assert data["shared_folder_id"] == "sf:123"
        assert len(data["members"]) == 1
        assert data["members"][0]["display_name"] == "Jane Doe"

    def test_info_not_found(self, runner, mock_services):
        dbx_svc, _ = mock_services
        dbx_svc.get_shared_folder_id.side_effect = NotFoundError("Folder not found")

        result = runner.invoke(app, ["sharing", "info", "/nonexistent"])
        assert result.exit_code == 3

    def test_info_not_a_shared_folder(self, runner, mock_services):
        dbx_svc, _ = mock_services
        dbx_svc.get_shared_folder_id.return_value = None

        result = runner.invoke(app, ["sharing", "info", "/test-folder"])
        assert result.exit_code == 4
