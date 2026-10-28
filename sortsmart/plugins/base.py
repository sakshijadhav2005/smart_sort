"""The plugin interface (FR10).

Drop a ``.py`` file with a ``Detector`` or ``Action`` subclass into the
plugins folder; it is loaded at startup.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from ..core.text import extract_text


@dataclass
class FileInfo:
    """What a plugin sees about a file. ``text`` is extracted on first use."""
    path: Path
    name: str
    ext: str
    type: str
    mime: str
    category: str
    size: int
    hash: str
    is_text: bool = False
    _text: str | None = field(default=None, repr=False)

    @property
    def text(self) -> str:
        if self._text is None:
            self._text = extract_text(self.path, self.type, self.is_text)
        return self._text


class Plugin:
    name = "plugin"

    def setup(self, settings: dict) -> None:
        """Receives ``plugins.settings.<name>`` from the config."""


class Detector(Plugin):
    """Decides whether a file matches and where it goes.

    Detectors run before the built-in rules; the first match wins.
    """
    name = "detector"

    def matches(self, file: FileInfo) -> bool:
        raise NotImplementedError

    def destination(self, file: FileInfo) -> str:
        """Folder relative to the destination root, e.g. ``Documents/Invoices``."""
        raise NotImplementedError


class Action(Plugin):
    """Runs after a file has been handled."""
    name = "action"
    events = ("sorted", "duplicate", "quarantined", "failed")

    def run(self, result, file: FileInfo) -> None:
        """``result`` is the ProcessResult for the file."""

    def alert(self, message: str, details: dict) -> None:
        """Called when a health check turns unhealthy."""
