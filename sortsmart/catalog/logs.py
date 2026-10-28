"""Structured JSON-lines logging with rotation (FR7)."""
from __future__ import annotations

import json
import logging
import logging.handlers
from datetime import datetime, timezone
from pathlib import Path

LOGGER_NAME = "sortsmart"
_STANDARD = set(vars(logging.makeLogRecord({}))) | {"message", "asctime", "taskName"}


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        data = {
            "time": datetime.fromtimestamp(record.created, timezone.utc)
                            .isoformat(timespec="milliseconds"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        for key, value in vars(record).items():
            if key not in _STANDARD and not key.startswith("_"):
                data[key] = value
        if record.exc_info:
            data["exc"] = self.formatException(record.exc_info)
        return json.dumps(data, default=str, ensure_ascii=False)


def setup_logging(log_dir: Path, *, level="INFO", max_bytes=5 * 2**20, backups=5,
                  console=False) -> list[logging.Handler]:
    """Attach handlers to the ``sortsmart`` logger and return them so the
    owner can detach them again (see ``teardown_logging``)."""
    logger = logging.getLogger(LOGGER_NAME)
    logger.setLevel(getattr(logging, str(level).upper(), logging.INFO))
    handlers: list[logging.Handler] = []
    log_dir = Path(log_dir)
    log_dir.mkdir(parents=True, exist_ok=True)
    fh = logging.handlers.RotatingFileHandler(
        log_dir / "sortsmart.log", maxBytes=int(max_bytes), backupCount=int(backups),
        encoding="utf-8", delay=True)
    fh.setFormatter(JsonFormatter())
    handlers.append(fh)
    if console:
        ch = logging.StreamHandler()
        ch.setFormatter(logging.Formatter("%(asctime)s %(levelname)-7s %(message)s", "%H:%M:%S"))
        handlers.append(ch)
    for h in handlers:
        logger.addHandler(h)
    return handlers


def teardown_logging(handlers: list[logging.Handler]):
    logger = logging.getLogger(LOGGER_NAME)
    for h in handlers:
        logger.removeHandler(h)
        h.close()
