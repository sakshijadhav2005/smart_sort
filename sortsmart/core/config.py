"""Configuration (FR2). Loaded from YAML, merged over defaults.

Relative paths are resolved against the folder holding the config file, or
the current directory when the config is given as a dict.
"""
from __future__ import annotations

import copy
import os
from pathlib import Path

import yaml

DEFAULTS: dict = {
    "inbox": None,
    "destination": None,           # default: <inbox>/Sorted, else ./sorted
    "catalog": "sortsmart.db",
    "recursive": False,
    "date_subfolders": False,
    "date_format": "%Y/%m",
    "date_source": "modified",     # modified | processed
    "quarantine_mismatch": True,
    "deep_check_max_mb": 200,
    "folders": {"duplicates": "Duplicates", "quarantine": "Quarantine"},
    "categories": {},              # {Category: [type or extension, ...]} overrides
    "rules": [],
    "ignore": ["*.part", "*.crdownload", "*.download", "*.tmp", "*.partial",
               "~$*", ".~lock*", ".DS_Store", "desktop.ini", "Thumbs.db"],
    "stability": {"interval": 0.5, "checks": 2, "timeout": 300},
    "retry": {"attempts": 3, "delay": 0.5},
    "logging": {"dir": "logs", "level": "INFO", "max_bytes": 5 * 2**20,
                "backups": 5, "console": False},
    "plugins": {"enabled": True, "dir": "plugins", "builtin": [], "settings": {}},
    "health": {"min_free_mb": 500, "stuck_after": 300, "interval": 60, "max_queue": 1000},
}


class ConfigError(ValueError):
    pass


def _merge(base: dict, extra: dict) -> dict:
    out = copy.deepcopy(base)
    for k, v in extra.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _merge(out[k], v)
        else:
            out[k] = v
    return out


class Config:
    def __init__(self, data: dict | None = None, base_dir: Path | None = None,
                 source: Path | None = None):
        data = data or {}
        if not isinstance(data, dict):
            raise ConfigError("config must be a mapping")
        unknown = set(data) - set(DEFAULTS)
        if unknown:
            raise ConfigError(f"unknown config keys: {', '.join(sorted(unknown))}")
        # an empty YAML section ("rules:") means "use the default"
        data = {k: v for k, v in data.items()
                if not (v is None and isinstance(DEFAULTS[k], (dict, list)))}
        self.data = _merge(DEFAULTS, data)
        self.base_dir = Path(base_dir or Path.cwd()).resolve()
        self.source = source
        self._validate()

    @classmethod
    def load(cls, config=None, **overrides) -> "Config":
        if isinstance(config, Config):
            data, base, source = copy.deepcopy(config.data), config.base_dir, config.source
        elif config is None:
            data, base, source = {}, None, None
        elif isinstance(config, dict):
            data, base, source = copy.deepcopy(config), None, None
        else:
            source = Path(config).resolve()
            if not source.is_file():
                raise ConfigError(f"config file not found: {source}")
            with open(source, encoding="utf-8") as f:
                data = yaml.safe_load(f) or {}
            base = source.parent
        overrides = {k: v for k, v in overrides.items() if v is not None}
        cfg = cls(data, base, source)
        if overrides:
            cfg.data = _merge(cfg.data, overrides)
            cfg._validate()
        return cfg

    def _validate(self):
        d = self.data
        if d["date_source"] not in ("modified", "processed"):
            raise ConfigError("date_source must be 'modified' or 'processed'")
        if not isinstance(d["rules"], list):
            raise ConfigError("rules must be a list")
        for i, rule in enumerate(d["rules"]):
            if not isinstance(rule, dict) or "destination" not in rule or "match" not in rule:
                raise ConfigError(f"rule #{i + 1} needs 'match' and 'destination'")
        if not isinstance(d["categories"], dict):
            raise ConfigError("categories must be a mapping of category -> list")

    def __getitem__(self, key):
        return self.data[key]

    def path(self, value) -> Path | None:
        if value is None:
            return None
        p = Path(os.path.expanduser(os.path.expandvars(str(value))))
        return (p if p.is_absolute() else self.base_dir / p).resolve()

    @property
    def inbox(self) -> Path | None:
        return self.path(self.data["inbox"])

    @property
    def destination(self) -> Path:
        if self.data["destination"]:
            return self.path(self.data["destination"])
        return self.inbox / "Sorted" if self.inbox else self.path("sorted")

    @property
    def catalog_path(self) -> Path:
        return self.path(self.data["catalog"])

    @property
    def log_dir(self) -> Path:
        return self.path(self.data["logging"]["dir"])

    @property
    def plugins_dir(self) -> Path:
        return self.path(self.data["plugins"]["dir"])

    @property
    def duplicates_dir(self) -> Path:
        return self.destination / self.data["folders"]["duplicates"]

    @property
    def quarantine_dir(self) -> Path:
        return self.destination / self.data["folders"]["quarantine"]
