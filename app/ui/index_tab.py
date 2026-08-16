"""Index tab — init / index / prompt-tune actions, reset/clear, live log."""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont, QTextCursor
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from ..indexer import Indexer
from ..project import GraphRAGProject


class ResetDialog(QDialog):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Clear / Reset index")
        v = QVBoxLayout(self)
        v.addWidget(QLabel(
            "Select what to delete from the project. The folders are recreated empty afterwards."
        ))
        self.cb_output = QCheckBox("output/  (entities, relationships, communities, lancedb, graphml)")
        self.cb_output.setChecked(True)
        self.cb_cache = QCheckBox("cache/   (LLM response cache — slows next run if removed)")
        self.cb_cache.setChecked(False)
        self.cb_logs = QCheckBox("logs/    (indexing logs)")
        self.cb_logs.setChecked(True)
        v.addWidget(self.cb_output)
        v.addWidget(self.cb_cache)
        v.addWidget(self.cb_logs)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        v.addWidget(bb)


class IndexTab(QWidget):
    reset_done = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._project: GraphRAGProject | None = None

        self._indexer = Indexer(self)
        self._indexer.line_received.connect(self._append_log)
        self._indexer.progress.connect(self._on_progress)
        self._indexer.finished.connect(self._on_finished)
        self._indexer.failed_to_start.connect(self._on_failed_to_start)
        self._indexer.started.connect(self._on_started)

        root = QVBoxLayout(self)

        # ---- action buttons ----
        actions_group = QGroupBox("Actions")
        ag = QHBoxLayout(actions_group)
        self._init_btn = QPushButton("Initialize project")
        self._init_btn.setToolTip("Initialize a new project (creates settings.yaml, prompts/,\n"
                                  "input/, output/). Skips projects that are already initialized.")
        self._index_btn = QPushButton("Run indexing")
        self._index_btn.setToolTip("graphrag index --root <project>")
        self._tune_btn = QPushButton("Prompt-tune")
        self._tune_btn.setToolTip("graphrag prompt-tune — adapt prompts to your corpus")
        self._reset_btn = QPushButton("Clear / Reset…")
        self._reset_btn.setToolTip("Delete output/, cache/, logs/ before re-indexing")
        self._cancel_btn = QPushButton("Cancel")
        self._cancel_btn.setEnabled(False)
        ag.addWidget(self._init_btn)
        ag.addWidget(self._index_btn)
        ag.addWidget(self._tune_btn)
        ag.addWidget(self._reset_btn)
        ag.addStretch(1)
        ag.addWidget(self._cancel_btn)
        root.addWidget(actions_group)

        # ---- prompt-tune options ----
        tune_group = QGroupBox("Prompt-tune options (used only when 'Prompt-tune' is clicked)")
        tg = QFormLayout(tune_group)
        self._domain_edit = QLineEdit()
        self._domain_edit.setPlaceholderText("e.g. machine-learning research papers")
        self._language_edit = QLineEdit()
        self._language_edit.setPlaceholderText("e.g. English")
        self._tune_limit = QSpinBox()
        self._tune_limit.setRange(1, 200)
        self._tune_limit.setValue(15)
        self._tune_chunk_size = QSpinBox()
        self._tune_chunk_size.setRange(0, 20000)
        self._tune_chunk_size.setSingleStep(100)
        self._tune_chunk_size.setValue(0)
        self._tune_chunk_size.setSpecialValueText("(use settings.yaml)")
        self._tune_chunk_size.setToolTip(
            "Override chunk size for sampling. Should match chunking.size in settings.yaml. "
            "Leave at 0 to let graphrag use the default."
        )
        self._tune_selection = QComboBox()
        self._tune_selection.addItems(["random", "top", "auto", "all"])
        self._tune_selection.setToolTip(
            "How chunks are sampled from the corpus: random (default), top (first N), "
            "auto (k-means clustering — best quality, more expensive), all."
        )
        self._tune_discover = QCheckBox("Discover entity types from text")
        self._tune_discover.setChecked(True)
        self._tune_discover.setToolTip(
            "Let the tuner infer entity types from your corpus instead of using the defaults "
            "(organization, person, geo, event). Recommended for non-default domains."
        )
        tg.addRow("Domain:", self._domain_edit)
        tg.addRow("Language:", self._language_edit)
        tg.addRow("Chunk limit:", self._tune_limit)
        tg.addRow("Chunk size:", self._tune_chunk_size)
        tg.addRow("Selection method:", self._tune_selection)
        tg.addRow("", self._tune_discover)
        root.addWidget(tune_group)

        # ---- progress + log ----
        self._progress = QProgressBar()
        self._progress.setRange(0, 100)
        self._progress.setValue(0)
        root.addWidget(self._progress)

        self._log = QPlainTextEdit()
        self._log.setReadOnly(True)
        self._log.setMaximumBlockCount(20000)
        font = QFont("monospace")
        font.setStyleHint(QFont.Monospace)
        self._log.setFont(font)
        self._log.setPlaceholderText("Indexing output will appear here…")
        root.addWidget(self._log, 1)

        self._init_btn.clicked.connect(self._on_init)
        self._index_btn.clicked.connect(self._on_index)
        self._tune_btn.clicked.connect(self._on_tune)
        self._reset_btn.clicked.connect(self._on_reset)
        self._cancel_btn.clicked.connect(self._on_cancel)

        self._update_buttons(running=False)

    # ---- public ----
    def set_project(self, project: GraphRAGProject | None) -> None:
        self._project = project

    # ---- handlers ----
    def _on_init(self) -> None:
        if not self._require_project():
            return
        if self._project.is_initialized():
            self._project.ensure_dirs()
            self._append_log("[gui] Project already initialized — ensured folders, skipped re-init.")
            QMessageBox.information(
                self,
                "Already initialized",
                "This project already has settings.yaml and prompts, so it was left untouched.\n"
                "The input/ output/ cache/ logs/ folders have been ensured.",
            )
            return
        self._log.clear()
        self._progress.setValue(0)
        self._indexer.init_project(self._project)

    def _on_index(self) -> None:
        if not self._require_project():
            return
        if not self._project.settings_path.exists():
            QMessageBox.warning(self, "Indexing", "settings.yaml is missing. Run Initialize first.")
            return
        self._log.clear()
        self._progress.setValue(0)
        self._indexer.index(self._project)

    def _on_tune(self) -> None:
        if not self._require_project():
            return
        self._log.clear()
        self._progress.setValue(0)
        self._indexer.prompt_tune(
            self._project,
            domain=self._domain_edit.text().strip(),
            language=self._language_edit.text().strip(),
            limit=self._tune_limit.value(),
            chunk_size=self._tune_chunk_size.value(),
            selection_method=self._tune_selection.currentText(),
            discover_entity_types=self._tune_discover.isChecked(),
        )

    def _on_reset(self) -> None:
        if not self._require_project():
            return
        dlg = ResetDialog(self)
        if dlg.exec() != QDialog.Accepted:
            return
        if not any([dlg.cb_output.isChecked(), dlg.cb_cache.isChecked(), dlg.cb_logs.isChecked()]):
            return
        confirm = QMessageBox.question(
            self,
            "Confirm reset",
            "This will permanently delete the selected folders. Continue?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if confirm != QMessageBox.Yes:
            return
        removed = self._project.reset(
            output=dlg.cb_output.isChecked(),
            cache=dlg.cb_cache.isChecked(),
            logs=dlg.cb_logs.isChecked(),
        )
        if removed:
            self._append_log("[gui] Cleared: " + ", ".join(removed))
        else:
            self._append_log("[gui] Nothing to clear (folders were already empty).")
        self.reset_done.emit()

    def _on_cancel(self) -> None:
        self._indexer.cancel()
        self._append_log("[gui] cancel requested")

    # ---- indexer slots ----
    def _on_started(self) -> None:
        self._update_buttons(running=True)
        self._append_log("[gui] process started")

    def _on_progress(self, pct: int) -> None:
        self._progress.setValue(pct)

    def _on_finished(self, code: int) -> None:
        self._update_buttons(running=False)
        self._append_log(f"[gui] process finished with exit code {code}")

    def _on_failed_to_start(self, msg: str) -> None:
        self._update_buttons(running=False)
        QMessageBox.critical(self, "Process failed", msg)

    # ---- helpers ----
    def _require_project(self) -> bool:
        if not self._project:
            QMessageBox.warning(self, "No project", "Open or create a project first.")
            return False
        return True

    def _update_buttons(self, *, running: bool) -> None:
        for b in (self._init_btn, self._index_btn, self._tune_btn, self._reset_btn):
            b.setEnabled(not running)
        self._cancel_btn.setEnabled(running)

    def _append_log(self, line: str) -> None:
        self._log.appendPlainText(line)
        # auto-scroll to bottom
        self._log.moveCursor(QTextCursor.End)
