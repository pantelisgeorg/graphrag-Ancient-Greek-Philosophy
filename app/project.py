"""GraphRAG project model — locates artifacts, loads parquet outputs."""
from __future__ import annotations

import json
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

    # Back-compat alias (older code may still reference this name).
    @property
    def pyvis_html_path(self) -> Path:  # noqa: D401
        return self.graph_html_path

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


# ---------------- recents store ----------------

def load_recent_projects() -> list[Path]:
    p = recents_path()
    if not p.exists():
        # seed with the bundled ragtest if it exists next to the app
        candidate = Path(__file__).resolve().parents[1] / "ragtest"
        if candidate.exists():
            return [candidate]
        return []
    try:
        return [Path(x) for x in json.loads(p.read_text())]
    except Exception:  # noqa: BLE001
        return []


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
