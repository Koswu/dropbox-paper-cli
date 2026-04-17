"""Tests for OutputFormatter JSON/human-readable formatting and error output."""

from __future__ import annotations

import json

from dropbox_paper_cli.lib.output import OutputFormatter


class TestOutputFormatterJson:
    """In JSON mode, output is structured JSON to stdout."""

    def test_success_outputs_json(self, capsys):
        fmt = OutputFormatter(json_mode=True)
        fmt.success({"status": "ok", "count": 5})
        captured = capsys.readouterr()
        data = json.loads(captured.out)
        assert data["status"] == "ok"
        assert data["count"] == 5

    def test_error_outputs_json_to_stderr(self, capsys):
        fmt = OutputFormatter(json_mode=True)
        fmt.error("something broke", code="GENERAL_FAILURE")
        captured = capsys.readouterr()
        data = json.loads(captured.err)
        assert data["error"] == "something broke"
        assert data["code"] == "GENERAL_FAILURE"
        assert captured.out == ""


class TestOutputFormatterHuman:
    """In human-readable mode, output is plain text."""

    def test_success_outputs_text(self, capsys):
        fmt = OutputFormatter(json_mode=False)
        fmt.success("All good!")
        captured = capsys.readouterr()
        assert "All good!" in captured.out

    def test_error_outputs_text_to_stderr(self, capsys):
        fmt = OutputFormatter(json_mode=False)
        fmt.error("something broke", code="GENERAL_FAILURE")
        captured = capsys.readouterr()
        assert "something broke" in captured.err


class TestOutputFormatterVerbose:
    """Verbose diagnostic messages go to stderr."""

    def test_verbose_message_to_stderr(self, capsys):
        fmt = OutputFormatter(json_mode=False, verbose=True)
        fmt.verbose("debug info here")
        captured = capsys.readouterr()
        assert "debug info here" in captured.err

    def test_verbose_suppressed_when_disabled(self, capsys):
        fmt = OutputFormatter(json_mode=False, verbose=False)
        fmt.verbose("should not appear")
        captured = capsys.readouterr()
        assert captured.err == ""
