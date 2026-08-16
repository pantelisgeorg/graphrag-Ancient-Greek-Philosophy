"""Query tab — global / local / drift / basic with token streaming."""
from __future__ import annotations

import json
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont, QTextCursor
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSpinBox,
    QSplitter,
    QTextEdit,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ..paths import history_path
from ..project import GraphRAGProject
from ..query_runner import QueryRunner


METHODS = [
    ("global", "Global (community reports, map-reduce)"),
    ("local", "Local (entity-anchored graph traversal)"),
    ("drift", "DRIFT (HyDE + iterative refinement)"),
    ("basic", "Basic (vector RAG over text units)"),
]

RESPONSE_TYPES = [
    "Multiple Paragraphs",
    "Single Paragraph",
    "List of 3-7 Points",
    "Multi-page Report",
]


class QueryTab(QWidget):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._project: GraphRAGProject | None = None
        self._runner = QueryRunner(self)
        self._runner.token.connect(self._on_token)
        self._runner.context_ready.connect(self._on_context)
        self._runner.finished_ok.connect(self._on_done)
        self._runner.failed.connect(self._on_failed)
        self._runner.info.connect(self._append_info)
        self._answer_started_at: float = 0.0

        root = QVBoxLayout(self)

        # ---- parameters ----
        params_group = QGroupBox("Parameters")
        pf = QFormLayout(params_group)

        self._method_combo = QComboBox()
        for key, label in METHODS:
            self._method_combo.addItem(label, key)

        self._community_level = QSpinBox()
        self._community_level.setRange(0, 5)
        self._community_level.setValue(2)

        self._dyn_community = QCheckBox("Dynamic community selection (global only)")

        self._response_type = QComboBox()
        for r in RESPONSE_TYPES:
            self._response_type.addItem(r)

        pf.addRow("Method:", self._method_combo)
        pf.addRow("Community level:", self._community_level)
        pf.addRow("", self._dyn_community)
        pf.addRow("Response type:", self._response_type)
        root.addWidget(params_group)

        # ---- query input ----
        self._query_edit = QPlainTextEdit()
        self._query_edit.setPlaceholderText(
            "Type your question, e.g. 'How does a company choose between RAG, fine-tuning, and different PEFT approaches?'"
        )
        self._query_edit.setMaximumHeight(110)
        root.addWidget(self._query_edit)

        # ---- actions ----
        actions = QHBoxLayout()
        self._ask_btn = QPushButton("Ask")
        self._ask_btn.setDefault(True)
        self._cancel_btn = QPushButton("Cancel")
        self._cancel_btn.setEnabled(False)
        self._clear_btn = QPushButton("Clear answer")
        self._copy_btn = QPushButton("Copy answer")
        self._save_btn = QPushButton("Save transcript…")
        actions.addWidget(self._ask_btn)
        actions.addWidget(self._cancel_btn)
        actions.addStretch(1)
        actions.addWidget(self._clear_btn)
        actions.addWidget(self._copy_btn)
        actions.addWidget(self._save_btn)
        root.addLayout(actions)

        # ---- answer + context split ----
        splitter = QSplitter(Qt.Vertical)
        self._answer = QTextEdit()
        self._answer.setReadOnly(True)
        f = QFont()
        f.setPointSize(11)
        self._answer.setFont(f)
        self._answer.setPlaceholderText("Streaming answer will appear here…")
        splitter.addWidget(self._answer)

        ctx_group = QGroupBox("Context / sources used by the engine")
        cv = QVBoxLayout(ctx_group)
        self._context_tree = QTreeWidget()
        self._context_tree.setHeaderLabels(["Type", "Detail"])
        self._context_tree.setRootIsDecorated(True)
        cv.addWidget(self._context_tree)
        self._info_log = QPlainTextEdit()
        self._info_log.setReadOnly(True)
        self._info_log.setMaximumHeight(90)
        self._info_log.setPlaceholderText("Status messages and errors…")
        cv.addWidget(self._info_log)
        splitter.addWidget(ctx_group)
        splitter.setSizes([600, 250])
        root.addWidget(splitter, 1)

        self._ask_btn.clicked.connect(self._on_ask)
        self._cancel_btn.clicked.connect(self._on_cancel)
        self._clear_btn.clicked.connect(self._on_clear)
        self._copy_btn.clicked.connect(self._on_copy)
        self._save_btn.clicked.connect(self._on_save)

    # ---- public ----
    def set_project(self, project: GraphRAGProject | None) -> None:
        self._project = project

    # ---- handlers ----
    def _on_ask(self) -> None:
        if not self._project:
            QMessageBox.warning(self, "No project", "Open a project first.")
            return
        if not self._project.is_indexed():
            QMessageBox.warning(self, "Not indexed", "This project has no output/entities.parquet yet.")
            return
        query = self._query_edit.toPlainText().strip()
        if not query:
            QMessageBox.information(self, "Query", "Type a question first.")
            return

        self._answer.clear()
        self._context_tree.clear()
        self._info_log.clear()
        self._set_busy(True)
        self._answer_started_at = time.monotonic()

        method = self._method_combo.currentData()
        self._runner.run(
            self._project,
            method,
            query,
            community_level=self._community_level.value(),
            dynamic_community_selection=self._dyn_community.isChecked(),
            response_type=self._response_type.currentText(),
        )

    def _on_cancel(self) -> None:
        self._runner.cancel()
        self._append_info("[gui] cancel requested")

    def _on_clear(self) -> None:
        self._answer.clear()
        self._context_tree.clear()
        self._info_log.clear()

    def _on_copy(self) -> None:
        from PySide6.QtGui import QGuiApplication
        QGuiApplication.clipboard().setText(self._answer.toPlainText())

    def _on_save(self) -> None:
        if not self._answer.toPlainText().strip():
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "Save transcript", "transcript.md", "Markdown (*.md);;Text (*.txt)"
        )
        if not path:
            return
        method = self._method_combo.currentData()
        body = (
            f"# GraphRAG transcript\n\n"
            f"- method: **{method}**\n"
            f"- community level: {self._community_level.value()}\n"
            f"- response type: {self._response_type.currentText()}\n\n"
            f"## Question\n\n{self._query_edit.toPlainText().strip()}\n\n"
            f"## Answer\n\n{self._answer.toPlainText().strip()}\n"
        )
        Path(path).write_text(body)

    # ---- runner slots ----
    def _on_token(self, chunk: str) -> None:
        cursor = self._answer.textCursor()
        cursor.movePosition(QTextCursor.End)
        cursor.insertText(chunk)
        self._answer.setTextCursor(cursor)
        self._answer.ensureCursorVisible()

    def _on_context(self, ctx: Any) -> None:
        self._populate_context_tree(ctx)

    def _populate_context_tree(self, ctx: Any) -> None:
        self._context_tree.clear()
        if isinstance(ctx, dict):
            for k, v in ctx.items():
                parent_item = QTreeWidgetItem([str(k), self._summarize_value(v)])
                self._context_tree.addTopLevelItem(parent_item)
                self._add_subitems(parent_item, v)
            self._context_tree.expandToDepth(0)
        elif isinstance(ctx, list):
            top = QTreeWidgetItem(["list", f"{len(ctx)} items"])
            self._context_tree.addTopLevelItem(top)
            self._add_subitems(top, ctx)
        else:
            self._context_tree.addTopLevelItem(QTreeWidgetItem(["context", str(ctx)]))

    def _summarize_value(self, v: Any) -> str:
        try:
            import pandas as pd
            if isinstance(v, pd.DataFrame):
                return f"DataFrame ({len(v)} rows × {len(v.columns)} cols)"
        except Exception:  # noqa: BLE001
            pass
        if isinstance(v, list):
            return f"list ({len(v)})"
        if isinstance(v, dict):
            return f"dict ({len(v)} keys)"
        s = str(v)
        return s if len(s) <= 80 else s[:79] + "…"

    def _add_subitems(self, parent: QTreeWidgetItem, value: Any, depth: int = 0) -> None:
        if depth > 2:
            return
        try:
            import pandas as pd
            if isinstance(value, pd.DataFrame):
                # show up to 30 rows
                preview = value.head(30)
                for _, row in preview.iterrows():
                    label = row.get("title") or row.get("id") or row.get("source") or row.iloc[0]
                    detail = ", ".join(f"{c}={row[c]}" for c in preview.columns[1:6] if c in preview.columns)
                    parent.addChild(QTreeWidgetItem([str(label), detail[:300]]))
                if len(value) > 30:
                    parent.addChild(QTreeWidgetItem(["…", f"{len(value) - 30} more rows"]))
                return
        except Exception:  # noqa: BLE001
            pass
        if isinstance(value, dict):
            for k, v in value.items():
                child = QTreeWidgetItem([str(k), self._summarize_value(v)])
                parent.addChild(child)
                self._add_subitems(child, v, depth + 1)
        elif isinstance(value, list):
            for i, v in enumerate(value[:30]):
                child = QTreeWidgetItem([f"[{i}]", self._summarize_value(v)])
                parent.addChild(child)
                self._add_subitems(child, v, depth + 1)
            if len(value) > 30:
                parent.addChild(QTreeWidgetItem(["…", f"{len(value) - 30} more"]))

    def _on_done(self) -> None:
        elapsed = time.monotonic() - self._answer_started_at
        self._append_info(f"[gui] done in {elapsed:.1f}s")
        self._set_busy(False)
        self._save_history_entry()

    def _on_failed(self, msg: str) -> None:
        self._append_info("[error] " + msg)
        self._set_busy(False)

    # ---- helpers ----
    def _append_info(self, line: str) -> None:
        self._info_log.appendPlainText(line)
        self._info_log.moveCursor(QTextCursor.End)

    def _set_busy(self, busy: bool) -> None:
        self._ask_btn.setEnabled(not busy)
        self._cancel_btn.setEnabled(busy)

    def _save_history_entry(self) -> None:
        try:
            entry = {
                "ts": datetime.utcnow().isoformat() + "Z",
                "project": str(self._project.root) if self._project else "",
                "method": self._method_combo.currentData(),
                "community_level": self._community_level.value(),
                "response_type": self._response_type.currentText(),
                "query": self._query_edit.toPlainText().strip(),
                "answer": self._answer.toPlainText().strip(),
            }
            with history_path().open("a") as f:
                f.write(json.dumps(entry) + "\n")
        except Exception:  # noqa: BLE001
            pass
