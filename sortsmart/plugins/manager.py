"""Loads plugins and isolates their failures: a plugin that raises is
disabled and logged, and the core keeps running."""
from __future__ import annotations

import importlib
import importlib.util
import inspect
import logging
import sys
from pathlib import Path

from ..core.rules import safe_relative
from .base import Action, Detector, FileInfo

log = logging.getLogger("sortsmart.plugins")


class PluginManager:
    def __init__(self, settings: dict | None = None):
        self.settings = settings or {}
        self.detectors: list[Detector] = []
        self.actions: list[Action] = []
        self.disabled: list[dict] = []

    # -- loading --------------------------------------------------------
    def load_builtin(self, names):
        for name in names or []:
            try:
                module = importlib.import_module(f"{__package__}.builtin.{name}")
            except Exception as e:
                self._failed_load(name, e)
                continue
            self._register_module(module)

    def load_dir(self, folder: Path | None):
        if not folder or not Path(folder).is_dir():
            return
        for path in sorted(Path(folder).glob("*.py")):
            if path.name.startswith("_"):
                continue
            mod_name = f"sortsmart_plugin_{path.stem}"
            try:
                spec = importlib.util.spec_from_file_location(mod_name, path)
                module = importlib.util.module_from_spec(spec)
                sys.modules[mod_name] = module
                spec.loader.exec_module(module)
            except Exception as e:
                sys.modules.pop(mod_name, None)
                self._failed_load(path.name, e)
                continue
            self._register_module(module)

    def add(self, plugin):
        """Register a plugin instance (used by library callers and tests)."""
        try:
            plugin.setup(self.settings.get(plugin.name, {}) or {})
        except Exception as e:
            self._disable(plugin, "setup", e)
            return
        if isinstance(plugin, Detector):
            self.detectors.append(plugin)
        elif isinstance(plugin, Action):
            self.actions.append(plugin)
        else:
            raise TypeError("plugins must subclass Detector or Action")
        log.info("plugin loaded", extra={"event": "plugin_loaded", "plugin": plugin.name,
                                         "kind": "detector" if isinstance(plugin, Detector)
                                         else "action"})

    def _register_module(self, module):
        for _, cls in inspect.getmembers(module, inspect.isclass):
            if cls.__module__ != module.__name__ or cls in (Detector, Action):
                continue
            if issubclass(cls, (Detector, Action)):
                try:
                    plugin = cls()
                except Exception as e:
                    self._failed_load(getattr(cls, "name", cls.__name__), e)
                    continue
                self.add(plugin)

    def _failed_load(self, name, error):
        self.disabled.append({"name": str(name), "stage": "load", "error": repr(error)})
        log.error("plugin failed to load", extra={"event": "plugin_disabled", "plugin": str(name),
                                                  "error": repr(error)})

    def _disable(self, plugin, stage, error):
        for group in (self.detectors, self.actions):
            if plugin in group:
                group.remove(plugin)
        self.disabled.append({"name": plugin.name, "stage": stage, "error": repr(error)})
        log.error("plugin disabled after error", exc_info=error, extra={
            "event": "plugin_disabled", "plugin": plugin.name, "stage": stage})

    # -- running --------------------------------------------------------
    def detect(self, info: FileInfo):
        """Return (relative destination, plugin name) of the first match."""
        for detector in list(self.detectors):
            try:
                if detector.matches(info):
                    return str(safe_relative(detector.destination(info))), detector.name
            except Exception as e:
                self._disable(detector, "detect", e)
        return None

    def run_actions(self, result, info: FileInfo):
        for action in list(self.actions):
            if result.status not in action.events:
                continue
            try:
                action.run(result, info)
            except Exception as e:
                self._disable(action, "run", e)

    def alert(self, message: str, details: dict):
        for action in list(self.actions):
            try:
                action.alert(message, details)
            except Exception as e:
                self._disable(action, "alert", e)

    def describe(self) -> dict:
        return {"detectors": [d.name for d in self.detectors],
                "actions": [a.name for a in self.actions],
                "disabled": list(self.disabled)}
