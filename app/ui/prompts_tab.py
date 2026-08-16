"""Prompts tab — edit the .txt prompts under prompts/."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from ..project import GraphRAGProject


class PromptsTab(QWidget):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._project: GraphRAGProject | None = None
        self._current_path: Path | None = None
        self._dirty: bool = False

        root = QHBoxLayout(self)
        splitter = QSplitter()
        root.addWidget(splitter)

        # ---- left: file list ----
        left = QWidget()
        ll = QVBoxLayout(left)
        ll.addWidget(QLabel("Prompts"))
        self._list = QListWidget()
        ll.addWidget(self._list, 1)
        self._reload_btn = QPushButton("Reload list")
        ll.addWidget(self._reload_btn)
        splitter.addWidget(left)

        # ---- right: editor ----
        right = QWidget()
        rl = QVBoxLayout(right)
        self._path_label = QLabel("(no file)")
        rl.addWidget(self._path_label)
        self._editor = QPlainTextEdit()
        font = QFont("monospace")
        self._editor.setFont(font)
        self._editor.setPlaceholderText("Select a prompt on the left to edit it.")
        rl.addWidget(self._editor, 1)
        btns = QHBoxLayout()
        self._save_btn = QPushButton("Save")
        btns.addStretch(1)
        btns.addWidget(self._save_btn)
        rl.addLayout(btns)
        splitter.addWidget(right)
        splitter.setSizes([260, 700])

        self._list.currentItemChanged.connect(self._on_select)
        self._reload_btn.clicked.connect(self._populate)
        self._save_btn.clicked.connect(self._save)
        self._editor.textChanged.connect(self._mark_dirty)

    # ---- public ----
    def set_project(self, project: GraphRAGProject | None) -> None:
        self._project = project
        self._editor.clear()
        self._path_label.setText("(no file)")
        self._populate()

    # ---- internals ----
    def _populate(self) -> None:
        self._list.clear()
        if not self._project or not self._project.prompts_dir.exists():
            return
        for p in sorted(self._project.prompts_dir.iterdir()):
            if p.is_file() and p.suffix in {".txt", ".md"}:
                item = QListWidgetItem(p.name)
                item.setData(Qt.UserRole, str(p))
                self._list.addItem(item)

    def _on_select(self, current, _previous) -> None:
        if self._dirty and self._current_path:
            choice = QMessageBox.question(
                self,
                "Unsaved changes",
                f"Discard unsaved changes to {self._current_path.name}?",
                QMessageBox.Yes | QMessageBox.No,
            )
            if choice != QMessageBox.Yes:
                # Re-select the previous item without retriggering
                self._list.blockSignals(True)
                items = self._list.findItems(self._current_path.name, Qt.MatchExactly)
                if items:
                    self._list.setCurrentItem(items[0])
                self._list.blockSignals(False)
                return
        if not current:
            self._current_path = None
            self._editor.clear()
            self._path_label.setText("(no file)")
            return
        path = Path(current.data(Qt.UserRole))
        self._current_path = path
        self._path_label.setText(str(path))
        try:
            text = path.read_text()
        except OSError as exc:
            QMessageBox.critical(self, "Open failed", str(exc))
            return
        self._editor.blockSignals(True)
        self._editor.setPlainText(text)
        self._editor.blockSignals(False)
        self._dirty = False

    def _save(self) -> None:
        if not self._current_path:
            return
        try:
            self._current_path.write_text(self._editor.toPlainText())
        except OSError as exc:
            QMessageBox.critical(self, "Save failed", str(exc))
            return
        self._dirty = False
        QMessageBox.information(self, "Saved", f"Saved {self._current_path.name}")

    def _mark_dirty(self) -> None:
        self._dirty = True
