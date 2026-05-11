"""Shared pytest fixtures and configuration."""
from __future__ import annotations
import os
from pathlib import Path
from datetime import datetime
import json
import pytest


@pytest.fixture
def tmp_cache_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Provide a temporary cache directory and patch config.cache_dir()."""
    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()
    monkeypatch.setenv("DATA_DIR", str(tmp_path.parent))

    def mock_cache_dir():
        return cache_dir

    import src.config
    monkeypatch.setattr(src.config, "cache_dir", mock_cache_dir)
    return cache_dir


@pytest.fixture
def sample_dedup_cache(tmp_cache_dir: Path) -> Path:
    """Create a sample dedup cache file."""
    cache_file = tmp_cache_dir / "dedup_keys.json"
    data = {
        "old_key_1": datetime(2026, 5, 4, 10, 0, 0).isoformat(),
        "old_key_2": datetime(2026, 5, 5, 10, 0, 0).isoformat(),
        "recent_key_1": datetime(2026, 5, 10, 10, 0, 0).isoformat(),
    }
    cache_file.write_text(json.dumps(data), encoding="utf-8")
    return cache_file
