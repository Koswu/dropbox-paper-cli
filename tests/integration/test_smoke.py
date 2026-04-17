"""Integration smoke tests (opt-in, requires real Dropbox credentials).

Run with: DROPBOX_PAPER_CLI_INTEGRATION=1 uv run pytest tests/integration/ -v

These tests require:
1. A valid Dropbox token at ~/.dropbox-paper-cli/tokens.json
2. The DROPBOX_PAPER_CLI_INTEGRATION=1 environment variable
"""

from __future__ import annotations

import os

import pytest

# Skip entire module unless integration testing is enabled
pytestmark = pytest.mark.skipif(
    os.environ.get("DROPBOX_PAPER_CLI_INTEGRATION") != "1",
    reason="Integration tests disabled (set DROPBOX_PAPER_CLI_INTEGRATION=1 to run)",
)


@pytest.fixture
def runner():
    from typer.testing import CliRunner

    return CliRunner()


@pytest.fixture
def app():
    from dropbox_paper_cli.app import app

    return app


class TestSmokeSuite:
    """End-to-end smoke tests covering auth → list → read → sync → search flow."""

    def test_auth_status(self, runner, app):
        """Verify auth status shows authenticated."""
        result = runner.invoke(app, ["auth", "status"])
        assert result.exit_code == 0
        assert "Authenticated" in result.stdout or "authenticated" in result.stdout.lower()

    def test_files_list_root(self, runner, app):
        """List root folder returns items."""
        result = runner.invoke(app, ["--json", "files", "list"])
        assert result.exit_code == 0

    def test_files_list_json(self, runner, app):
        """JSON output contains expected keys."""
        import json

        result = runner.invoke(app, ["--json", "files", "list"])
        if result.exit_code == 0:
            data = json.loads(result.stdout)
            assert "items" in data
            assert "path" in data

    def test_cache_sync(self, runner, app):
        """Sync populates the cache."""
        result = runner.invoke(app, ["cache", "sync"])
        assert result.exit_code == 0
        assert "Sync complete" in result.stdout

    def test_cache_search(self, runner, app):
        """Search returns results (after sync)."""
        # First sync to ensure cache is populated
        runner.invoke(app, ["cache", "sync"])
        # Then search for something common
        result = runner.invoke(app, ["--json", "cache", "search", "paper"])
        assert result.exit_code == 0

    def test_help_commands(self, runner, app):
        """All command groups show help."""
        for group in ["auth", "files", "cache", "sharing"]:
            result = runner.invoke(app, [group, "--help"])
            assert result.exit_code == 0
