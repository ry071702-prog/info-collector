"""Structured logging with loguru."""
from __future__ import annotations
import os
import sys
from pathlib import Path
from typing import Any

from loguru import logger

from .config import logs_dir

_initialized = False


def setup() -> None:
    global _initialized
    if _initialized:
        return
    logger.remove()
    level = os.environ.get("LOG_LEVEL", "INFO").upper()
    logger.add(
        sys.stderr,
        level=level,
        format="<green>{time:YYYY-MM-DD HH:mm:ss}</green> | <level>{level: <8}</level> | <cyan>{name}</cyan> - {message}",
    )
    # Structured JSONL log for analytics
    logger.add(
        logs_dir() / "{time:YYYY-MM-DD}.jsonl",
        level=level,
        serialize=True,
        rotation="00:00",
    )
    _initialized = True


def get(name: str) -> Any:
    setup()
    return logger.bind(module=name)
