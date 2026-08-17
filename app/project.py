"""GraphRAG project model — locates artifacts, loads parquet outputs."""
from __future__ import annotations

import json
import os
import shutil
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from .paths import recents_path


@dataclass(frozen=True)
class GraphRAGProject:
    root: Path

    @property
    def settings_path(self) -> Path:
        return self.root / "settings.yaml"

    @property
    def env_path(self) -> Path:
        return self.root / ".env"

    @property
    def input_dir(self) -> Path:
        return self.root / "input"

    @property
    def output_dir(self) -> Path:
        return self.root / "output"

    @property
    def prompts_dir(self) -> Path:
        return self.root / "prompts"

    @property
    def cache_dir(self) -> Path:
        return self.root / "cache"

    @property
    def logs_dir(self) -> Path:
        return self.root / "logs"

    @property
    def graphml_path(self) -> Path:
        return self.output_dir / "graph.graphml"

    @property
    def graph_html_path(self) -> Path:
        return self.output_dir / "_graph_preview.html"

    @property
    def stats_path(self) -> Path:
        return self.output_dir / "stats.json"

    PARQUETS: tuple[str, ...] = (
        "entities",
        "relationships",
        "communities",
        "community_reports",
        "text_units",
        "documents",
    )

    def parquet_path(self, name: str) -> Path:
        return self.output_dir / f"{name}.parquet"

    def is_initialized(self) -> bool:
        return self.settings_path.exists()

    def is_indexed(self) -> bool:
        return self.parquet_path("entities").exists()

    def load_parquet(self, name: str) -> pd.DataFrame:
        path = self.parquet_path(name)
        if not path.exists():
            return pd.DataFrame()
        return pd.read_parquet(path)

    def stats(self) -> dict:
        if not self.stats_path.exists():
            return {}
        try:
            return json.loads(self.stats_path.read_text())
        except Exception:  # noqa: BLE001
            return {}

    def ensure_dirs(self) -> None:
        """Create the standard project subdirectories if they're missing."""
        for d in (self.input_dir, self.output_dir, self.cache_dir, self.logs_dir):
            d.mkdir(parents=True, exist_ok=True)

    # ---- mutation ----
    def reset(self, *, output: bool, cache: bool, logs: bool) -> list[str]:
        """Delete chosen subtrees. Returns a list of removed paths."""
        removed: list[str] = []
        targets: list[Path] = []
        if output:
            targets.append(self.output_dir)
        if cache:
            targets.append(self.cache_dir)
        if logs:
            targets.append(self.logs_dir)
        for t in targets:
            if t.exists():
                shutil.rmtree(t)
                removed.append(str(t))
            t.mkdir(parents=True, exist_ok=True)
        return removed


def load_project_env(project: GraphRAGProject) -> None:
    """Apply non-empty KEY=VALUE lines from the project's `.env` into `os.environ`.

    Values are assigned (not `setdefault`) so that edits to `.env` take effect even
    when an earlier read cached an empty value under the same key. Empty values are
    skipped so a blank template line (e.g. `NEO4J_PASSWORD=`) never clobbers a
    shell-exported secret such as `OPENAI_API_KEY`.
    """
    if not project.env_path.exists():
        return
    for raw in project.env_path.read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        key = k.strip()
        value = v.strip().strip('"').strip("'")
        if value:
            os.environ[key] = value


# ---------------- recents store ----------------

def load_recent_projects() -> list[Path]:
    p = recents_path()
    stored: list[Path] = []
    if p.exists():
        try:
            stored = [Path(x) for x in json.loads(p.read_text())]
        except Exception:  # noqa: BLE001
            stored = []

    # Drop entries that no longer exist on disk.
    stored = [x for x in stored if x.exists()]

    # Always keep the bundled sample project available, and default to it. It's
    # resolved relative to the app (not from a persisted absolute path) so it stays
    # correct when the repo is cloned or moved to a new location.
    bundled = Path(__file__).resolve().parents[1] / "ragtest"
    if bundled.exists() and not any(x.resolve() == bundled.resolve() for x in stored):
        stored.insert(0, bundled)

    return stored


def save_recent_projects(projects: list[Path]) -> None:
    unique: list[Path] = []
    seen: set[str] = set()
    for p in projects:
        s = str(p.resolve())
        if s in seen:
            continue
        seen.add(s)
        unique.append(p)
    recents_path().write_text(json.dumps([str(p) for p in unique], indent=2))
