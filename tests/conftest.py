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


@pytest.fixture
def tmp_data_dirs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, Path]:
    """Provide temporary raw and processed data directories."""
    data_dir = tmp_path / "data"
    raw = data_dir / "raw"
    processed = data_dir / "processed"
    raw.mkdir(parents=True)
    processed.mkdir(parents=True)

    def mock_raw_dir(date_str: str | None = None):
        if date_str:
            d = raw / date_str
            d.mkdir(parents=True, exist_ok=True)
            return d
        return raw

    def mock_processed_dir(date_str: str | None = None):
        if date_str:
            d = processed / date_str
            d.mkdir(parents=True, exist_ok=True)
            return d
        return processed

    import src.config
    monkeypatch.setattr(src.config, "raw_dir", mock_raw_dir)
    monkeypatch.setattr(src.config, "processed_dir", mock_processed_dir)

    return {"raw": raw, "processed": processed}


@pytest.fixture
def tmp_circuit_breaker(tmp_cache_dir: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Provide a temporary circuit breaker state file."""
    breaker_file = tmp_cache_dir / "circuit_breakers.json"

    import src.circuit_breaker
    monkeypatch.setattr(src.circuit_breaker, "STATE_FILE", breaker_file)

    return breaker_file
