"""Configuration loader: settings.toml + .env."""
from __future__ import annotations
import json
import os
from functools import lru_cache
from pathlib import Path

import tomli
from dotenv import load_dotenv

load_dotenv()

ROOT = Path(__file__).resolve().parents[1]
CONFIG_DIR = ROOT / "config"
DATA_DIR = ROOT / "data"
DOCS_DIR = ROOT / "docs"


@lru_cache(maxsize=1)
def settings() -> dict:
    """Load settings.toml."""
    path = CONFIG_DIR / "settings.toml"
    with path.open("rb") as f:
        return tomli.load(f)


def env(key: str, default: str | None = None, required: bool = False) -> str | None:
    val = os.environ.get(key, default)
    if required and not val:
        raise RuntimeError(f"Required env var {key} is not set")
    return val


def env_json(key: str, default=None, required: bool = False):
    raw = env(key, required=required)
    if not raw:
        return default
    return json.loads(raw)


def env_bool(key: str, default: bool = False) -> bool:
    val = env(key)
    if val is None:
        return default
    return val.lower() in ("1", "true", "yes", "on")


def is_dry_run() -> bool:
    return env_bool("DRY_RUN", False)


# Directory helpers
def raw_dir(date_str: str) -> Path:
    p = DATA_DIR / "raw" / date_str
    p.mkdir(parents=True, exist_ok=True)
    return p


def processed_dir(date_str: str) -> Path:
    p = DATA_DIR / "processed" / date_str
    p.mkdir(parents=True, exist_ok=True)
    return p


def cache_dir() -> Path:
    p = DATA_DIR / "cache"
    p.mkdir(parents=True, exist_ok=True)
    return p


def logs_dir() -> Path:
    p = DATA_DIR / "logs"
    p.mkdir(parents=True, exist_ok=True)
    return p


def digests_dir() -> Path:
    p = DOCS_DIR / "digests"
    p.mkdir(parents=True, exist_ok=True)
    return p
