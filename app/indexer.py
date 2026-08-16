"""Run the graphrag CLI (init / index / prompt-tune) and stream output to the UI."""
from __future__ import annotations

import os
import shlex
import sys
from pathlib import Path

from PySide6.QtCore import QObject, QProcess, QProcessEnvironment, Signal

from .project import GraphRAGProject


def _graphrag_executable() -> str:
    """Return the path to the graphrag CLI living in our venv (preferred)."""
    here = Path(__file__).resolve()
    # app/indexer.py -> project root has .venv
    for parent in (here.parent.parent, *here.parents):
        candidate = parent / ".venv" / "bin" / "graphrag"
        if candidate.exists():
            return str(candidate)
    return "graphrag"  # rely on PATH


# Heuristic milestones used to nudge the progress bar forward.
PROGRESS_MILESTONES: list[tuple[str, int]] = [
    ("create_base_text_units", 10),
    ("create_final_documents", 20),
    ("extract_graph", 35),
    ("finalize_graph", 50),
    ("create_communities", 65),
    ("create_final_text_units", 75),
    ("create_community_reports", 90),
    ("generate_text_embeddings", 95),
]


class Indexer(QObject):
    """QProcess wrapper. Emits log lines and a coarse progress percentage."""

    line_received = Signal(str)
    progress = Signal(int)
    started = Signal()
    finished = Signal(int)  # exit code
    failed_to_start = Signal(str)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._proc: QProcess | None = None
        self._last_progress: int = 0

    # ---- public actions ----
    def init_project(
        self,
        project: GraphRAGProject,
        *,
        model: str = "gpt-4o",
        embedding: str = "text-embedding-3-large",
    ) -> None:
        project.root.mkdir(parents=True, exist_ok=True)
        self._run(
            [
                "init",
                "--root", str(project.root),
                "--model", model,
                "--embedding", embedding,
                "--force",
            ],
            project,
        )

    def index(self, project: GraphRAGProject, *, method: str = "standard") -> None:
        self._run(
            ["index", "--root", str(project.root), "--method", method],
            project,
        )

    def prompt_tune(
        self,
        project: GraphRAGProject,
        *,
        domain: str = "",
        language: str = "",
        limit: int = 15,
        chunk_size: int = 0,
        selection_method: str = "",
        discover_entity_types: bool = False,
    ) -> None:
        args = ["prompt-tune", "--root", str(project.root), "--limit", str(limit)]
        if domain:
            args += ["--domain", domain]
        if language:
            args += ["--language", language]
        if chunk_size > 0:
            args += ["--chunk-size", str(chunk_size)]
        if selection_method:
            args += ["--selection-method", selection_method]
        if discover_entity_types:
            args += ["--discover-entity-types"]
        self._run(args, project)

    def cancel(self) -> None:
        if self._proc and self._proc.state() != QProcess.NotRunning:
            self._proc.terminate()
            if not self._proc.waitForFinished(2000):
                self._proc.kill()

    def is_running(self) -> bool:
        return bool(self._proc and self._proc.state() != QProcess.NotRunning)

    # ---- internals ----
    def _run(self, args: list[str], project: GraphRAGProject) -> None:
        if self.is_running():
            self.line_received.emit("[gui] already running — ignoring new request")
            return

        self._last_progress = 0
        self.progress.emit(0)

        proc = QProcess(self)
        proc.setProcessChannelMode(QProcess.MergedChannels)
        proc.setWorkingDirectory(str(project.root))

        env = QProcessEnvironment.systemEnvironment()
        # Load .env contents to override / supply OPENAI_API_KEY etc.
        if project.env_path.exists():
            for raw in project.env_path.read_text().splitlines():
                line = raw.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, v = line.split("=", 1)
                env.insert(k.strip(), v.strip().strip('"').strip("'"))
        env.insert("PYTHONUNBUFFERED", "1")
        proc.setProcessEnvironment(env)

        exe = _graphrag_executable()
        self.line_received.emit(f"$ {exe} {' '.join(shlex.quote(a) for a in args)}")
        self.line_received.emit(f"  (cwd: {project.root})")

        proc.readyReadStandardOutput.connect(lambda: self._on_output(proc))
        proc.errorOccurred.connect(self._on_error)
        proc.finished.connect(self._on_finished)
        proc.started.connect(self.started.emit)

        proc.start(exe, args)
        self._proc = proc

    def _on_output(self, proc: QProcess) -> None:
        data = bytes(proc.readAllStandardOutput()).decode("utf-8", errors="replace")
        for line in data.splitlines():
            if not line.strip():
                continue
            self.line_received.emit(line)
            self._maybe_advance_progress(line)

    def _maybe_advance_progress(self, line: str) -> None:
        lowered = line.lower()
        for token, pct in PROGRESS_MILESTONES:
            if token in lowered and pct > self._last_progress:
                self._last_progress = pct
                self.progress.emit(pct)
                return

    def _on_error(self, err) -> None:
        # QProcess::ProcessError
        if self._proc is None:
            return
        msg = self._proc.errorString() or str(err)
        self.failed_to_start.emit(msg)

    def _on_finished(self, code: int, _status) -> None:
        if code == 0:
            self.progress.emit(100)
        self.finished.emit(int(code))
