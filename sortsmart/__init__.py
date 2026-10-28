"""SortSmart: a reusable file intake engine.

    from sortsmart import Sorter
    sorter = Sorter(config="rules.yaml")
    result = sorter.process("uploads/file123")
"""
from .core.config import Config, ConfigError
from .core.detection import CATEGORIES, FileType, detect
from .core.engine import Classification, ProcessResult, Sorter

__version__ = "0.1.0"
__all__ = ["Sorter", "ProcessResult", "Classification", "Config", "ConfigError",
           "FileType", "detect", "CATEGORIES", "__version__"]
