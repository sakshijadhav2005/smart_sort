import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from sortsmart import Sorter  # noqa: E402


@pytest.fixture
def workspace(tmp_path):
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    return tmp_path


@pytest.fixture
def make_config(workspace):
    def _make(**extra):
        cfg = {
            "inbox": str(workspace / "inbox"),
            "destination": str(workspace / "sorted"),
            "catalog": str(workspace / "catalog.db"),
            "logging": {"dir": str(workspace / "logs")},
            "plugins": {"dir": str(workspace / "plugins")},
            "stability": {"interval": 0.1, "checks": 2, "timeout": 10},
            "retry": {"attempts": 3, "delay": 0.01},
        }
        for k, v in extra.items():
            if isinstance(v, dict) and isinstance(cfg.get(k), dict):
                cfg[k] = {**cfg[k], **v}
            else:
                cfg[k] = v
        return cfg
    return _make


@pytest.fixture
def sorter_factory(make_config):
    made = []

    def _make(**extra):
        plugins = extra.pop("plugin_objects", None)
        s = Sorter(make_config(**extra), plugins=plugins)
        made.append(s)
        return s
    yield _make
    for s in made:
        s.close()


@pytest.fixture
def sorter(sorter_factory):
    return sorter_factory()


@pytest.fixture
def inbox(workspace):
    return workspace / "inbox"


@pytest.fixture
def dest(workspace):
    return workspace / "sorted"
