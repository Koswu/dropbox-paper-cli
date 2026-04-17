"""Tests for resolve_target() URL detection, ID passthrough, and path normalization."""

from __future__ import annotations

from dropbox_paper_cli.lib.url_parser import is_dropbox_url, resolve_target


class TestResolveTargetUrl:
    """Dropbox URLs are returned as-is for SDK resolution."""

    def test_standard_paper_url_returned_as_is(self):
        url = "https://www.dropbox.com/scl/fi/abc123def/My+Document.paper?rlkey=xyz&dl=0"
        assert resolve_target(url) == url

    def test_url_without_www(self):
        url = "https://dropbox.com/scl/fi/xyz789/Test.paper?rlkey=abc"
        assert resolve_target(url) == url

    def test_any_dropbox_url_returned_as_is(self):
        url = "https://www.dropbox.com/sh/something/path"
        assert resolve_target(url) == url


class TestIsDropboxUrl:
    """is_dropbox_url detection."""

    def test_detects_dropbox_url(self):
        assert is_dropbox_url("https://www.dropbox.com/scl/fi/abc/doc.paper?rlkey=x")

    def test_detects_without_www(self):
        assert is_dropbox_url("https://dropbox.com/scl/fi/abc/doc.paper")

    def test_rejects_non_dropbox_url(self):
        assert not is_dropbox_url("https://google.com/something")

    def test_rejects_path(self):
        assert not is_dropbox_url("/Documents/Notes.paper")

    def test_rejects_id(self):
        assert not is_dropbox_url("id:abc123")


class TestResolveTargetId:
    """Raw Dropbox IDs starting with 'id:' pass through unchanged."""

    def test_id_passthrough(self):
        assert resolve_target("id:abc123") == "id:abc123"

    def test_id_with_long_value(self):
        assert resolve_target("id:AADxxxxxxxxxxxxxx") == "id:AADxxxxxxxxxxxxxx"


class TestResolveTargetPath:
    """Non-URL, non-ID strings are treated as Dropbox paths."""

    def test_path_passthrough(self):
        assert resolve_target("/Documents/Notes.paper") == "/Documents/Notes.paper"

    def test_root_path(self):
        assert resolve_target("") == ""

    def test_path_with_spaces(self):
        assert (
            resolve_target("/My Documents/Meeting Notes.paper")
            == "/My Documents/Meeting Notes.paper"
        )

    def test_non_dropbox_url_treated_as_path(self):
        result = resolve_target("https://google.com/something")
        assert result == "https://google.com/something"
