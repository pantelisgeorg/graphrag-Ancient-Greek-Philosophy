"""Filesystem path resolution for the GraphRAG GUI."""
from __future__ import annotations

import os
from pathlib import Path


def app_config_dir() -> Path:
    base = os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    d = Path(base) / "graphrag-gui"
    d.mkdir(parents=True, exist_ok=True)
    return d


def providers_path() -> Path:
    return app_config_dir() / "providers.json"


def recents_path() -> Path:
    return app_config_dir() / "recents.json"


def history_path() -> Path:
    return app_config_dir() / "history.jsonl"
