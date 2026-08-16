"""Streaming query bridge — runs graphrag.api.*_streaming on a worker thread,
forwards tokens via Qt signals."""
from __future__ import annotations

import asyncio
import os
import traceback
from pathlib import Path
from typing import Any, Optional

from PySide6.QtCore import QObject, QThread, Signal

from .project import GraphRAGProject


def _load_env_from_project(project: GraphRAGProject) -> None:
    """Read project's .env into os.environ so graphrag picks up ${OPENAI_API_KEY} etc."""
    if not project.env_path.exists():
        return
    for raw in project.env_path.read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


class _QueryWorker(QThread):
    """Owns its own asyncio event loop. Streams tokens and context back to the UI."""

    token = Signal(str)
    context_ready = Signal(object)
    finished_ok = Signal()
    failed = Signal(str)
    info = Signal(str)

    def __init__(
        self,
        project: GraphRAGProject,
        method: str,
        query: str,
        *,
        community_level: int = 2,
        dynamic_community_selection: bool = False,
        response_type: str = "Multiple Paragraphs",
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self.project = project
        self.method = method
        self.query = query
        self.community_level = community_level
        self.dynamic_community_selection = dynamic_community_selection
        self.response_type = response_type
        self._cancel = False

    def request_cancel(self) -> None:
        self._cancel = True

    # ---------- main entry ----------
    def run(self) -> None:  # noqa: C901
        try:
            asyncio.run(self._run_async())
        except Exception as exc:  # noqa: BLE001
            self.failed.emit(f"{exc}\n{traceback.format_exc()}")

    async def _run_async(self) -> None:
        # Late imports to keep app startup snappy and avoid heavy imports on UI thread.
        from graphrag.config.load_config import load_config
        from graphrag.callbacks.query_callbacks import QueryCallbacks
        import graphrag.api as api

        _load_env_from_project(self.project)

        self.info.emit(f"Loading config from {self.project.settings_path}…")
        config = load_config(self.project.root)

        self.info.emit("Loading parquet outputs…")
        entities = self.project.load_parquet("entities")
        communities = self.project.load_parquet("communities")
        community_reports = self.project.load_parquet("community_reports")
        text_units = self.project.load_parquet("text_units")
        relationships = self.project.load_parquet("relationships")

        if entities.empty:
            raise RuntimeError(
                "No entities.parquet found in the project's output/. "
                "Run indexing first."
            )

        worker = self

        class _Callbacks(QueryCallbacks):
            def on_context(self, context: Any) -> None:
                worker.context_ready.emit(context)

        callbacks = [_Callbacks()]

        self.info.emit(f"Running {self.method} search (streaming)…")

        if self.method == "global":
            stream = api.global_search_streaming(
                config=config,
                entities=entities,
                communities=communities,
                community_reports=community_reports,
                community_level=self.community_level,
                dynamic_community_selection=self.dynamic_community_selection,
                response_type=self.response_type,
                query=self.query,
                callbacks=callbacks,
            )
        elif self.method == "local":
            stream = api.local_search_streaming(
                config=config,
                entities=entities,
                communities=communities,
                community_reports=community_reports,
                text_units=text_units,
                relationships=relationships,
                covariates=None,
                community_level=self.community_level,
                response_type=self.response_type,
                query=self.query,
                callbacks=callbacks,
            )
        elif self.method == "drift":
            stream = api.drift_search_streaming(
                config=config,
                entities=entities,
                communities=communities,
                community_reports=community_reports,
                text_units=text_units,
                relationships=relationships,
                community_level=self.community_level,
                response_type=self.response_type,
                query=self.query,
                callbacks=callbacks,
            )
        elif self.method == "basic":
            stream = api.basic_search_streaming(
                config=config,
                text_units=text_units,
                response_type=self.response_type,
                query=self.query,
                callbacks=callbacks,
            )
        else:
            raise ValueError(f"Unknown method: {self.method}")

        async for chunk in stream:
            if self._cancel:
                break
            self._emit_chunk(chunk)

        self.finished_ok.emit()

    def _emit_chunk(self, chunk: Any) -> None:
        """graphrag emits either strings or dict/list events depending on the method."""
        if isinstance(chunk, str):
            self.token.emit(chunk)
            return
        # DRIFT emits structured events; pull readable text out of each kind.
        if isinstance(chunk, dict):
            for key in ("response", "answer", "content", "text", "token"):
                v = chunk.get(key)
                if isinstance(v, str) and v:
                    self.token.emit(v)
                    return
            self.info.emit(f"[event] {list(chunk.keys())}")
            return
        # Fallback
        self.token.emit(str(chunk))


class QueryRunner(QObject):
    """Thin facade so the UI doesn't see threads directly."""

    token = Signal(str)
    context_ready = Signal(object)
    finished_ok = Signal()
    failed = Signal(str)
    info = Signal(str)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._worker: Optional[_QueryWorker] = None

    def is_running(self) -> bool:
        return bool(self._worker and self._worker.isRunning())

    def run(
        self,
        project: GraphRAGProject,
        method: str,
        query: str,
        *,
        community_level: int = 2,
        dynamic_community_selection: bool = False,
        response_type: str = "Multiple Paragraphs",
    ) -> None:
        if self.is_running():
            self.info.emit("[gui] previous query still running — cancel it first")
            return
        worker = _QueryWorker(
            project,
            method,
            query,
            community_level=community_level,
            dynamic_community_selection=dynamic_community_selection,
            response_type=response_type,
        )
        worker.token.connect(self.token)
        worker.context_ready.connect(self.context_ready)
        worker.finished_ok.connect(self.finished_ok)
        worker.failed.connect(self.failed)
        worker.info.connect(self.info)
        worker.finished.connect(self._on_thread_done)
        self._worker = worker
        worker.start()

    def cancel(self) -> None:
        if self._worker:
            self._worker.request_cancel()

    def _on_thread_done(self) -> None:
        self._worker = None
