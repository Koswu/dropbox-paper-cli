"""OutputFormatter: JSON/human-readable output, success/error formatting."""

from __future__ import annotations

import json
import sys
from typing import Any


class OutputFormatter:
    """Formats CLI output as JSON or human-readable text.

    - success() writes to stdout
    - error() writes to stderr
    - verbose() writes diagnostic info to stderr (only when verbose=True)
    """

    def __init__(self, *, json_mode: bool = False, verbose: bool = False) -> None:
        self.json_mode = json_mode
        self._verbose = verbose

    def success(self, data: Any) -> None:
        """Write success output to stdout."""
        if self.json_mode:
            if isinstance(data, str):
                data = {"message": data}
            print(json.dumps(data, default=str), file=sys.stdout)
        else:
            if isinstance(data, dict):
                # Format dict as key: value lines for human reading
                for key, value in data.items():
                    print(f"{key}: {value}", file=sys.stdout)
            else:
                print(str(data), file=sys.stdout)

    def error(self, message: str, *, code: str = "GENERAL_FAILURE") -> None:
        """Write error output to stderr."""
        if self.json_mode:
            error_obj = {"error": message, "code": code}
            print(json.dumps(error_obj), file=sys.stderr)
        else:
            print(f"Error: {message}", file=sys.stderr)

    def verbose(self, message: str) -> None:
        """Write diagnostic info to stderr (only when verbose mode is enabled)."""
        if self._verbose:
            print(f"[verbose] {message}", file=sys.stderr)
