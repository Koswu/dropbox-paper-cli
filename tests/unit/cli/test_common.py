"""Tests for cli/common.py – safe_command context manager."""

from __future__ import annotations

import pytest
import typer

from dropbox_paper_cli.cli.common import safe_command
from dropbox_paper_cli.lib.errors import AppError, ExitCode
from dropbox_paper_cli.lib.output import OutputFormatter


@pytest.fixture
def fmt() -> OutputFormatter:
    return OutputFormatter(json_mode=False, verbose=False)


class TestSafeCommand:
    """Tests for the safe_command context manager."""

    def test_no_error(self, fmt: OutputFormatter) -> None:
        """Normal execution should not raise."""
        with safe_command(fmt):
            pass  # no error

    def test_app_error_exits_with_error_code(self, fmt: OutputFormatter) -> None:
        with pytest.raises(typer.Exit) as exc_info, safe_command(fmt):
            raise AppError("not found", code="NOT_FOUND", exit_code=ExitCode.NOT_FOUND)
        assert exc_info.value.exit_code == ExitCode.NOT_FOUND

    def test_value_error_exits_with_code_4(self, fmt: OutputFormatter) -> None:
        with pytest.raises(typer.Exit) as exc_info, safe_command(fmt):
            raise ValueError("bad url")
        assert exc_info.value.exit_code == 4

    def test_generic_exception_exits_with_code_1(self, fmt: OutputFormatter) -> None:
        with pytest.raises(typer.Exit) as exc_info, safe_command(fmt):
            raise RuntimeError("unexpected")
        assert exc_info.value.exit_code == 1

    def test_typer_exit_re_raised(self, fmt: OutputFormatter) -> None:
        """typer.Exit must pass through unchanged."""
        with pytest.raises(typer.Exit) as exc_info, safe_command(fmt):
            raise typer.Exit(code=42)
        assert exc_info.value.exit_code == 42

    def test_app_error_formats_output(
        self, fmt: OutputFormatter, capsys: pytest.CaptureFixture[str]
    ) -> None:
        with pytest.raises(typer.Exit), safe_command(fmt):
            raise AppError("oops", code="MY_CODE", exit_code=ExitCode.GENERAL_ERROR)
        captured = capsys.readouterr()
        assert "MY_CODE" in captured.err or "oops" in captured.err

    def test_general_failure_formats_output(
        self, fmt: OutputFormatter, capsys: pytest.CaptureFixture[str]
    ) -> None:
        with pytest.raises(typer.Exit), safe_command(fmt):
            raise RuntimeError("boom")
        captured = capsys.readouterr()
        assert "GENERAL_FAILURE" in captured.err or "boom" in captured.err
