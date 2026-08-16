"""Projects tab — settings.yaml editor + .env editor + path overview."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSplitter,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from ..project import GraphRAGProject


class ProjectsTab(QWidget):
    settings_saved = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._project: GraphRAGProject | None = None

        root_layout = QVBoxLayout(self)

        # Path overview group
        self._paths_group = QGroupBox("Project paths")
        paths_form = QFormLayout(self._paths_group)
        self._root_label = QLabel("(no project)")
        self._settings_label = QLabel("-")
        self._input_label = QLabel("-")
        self._output_label = QLabel("-")
        self._prompts_label = QLabel("-")
        self._status_label = QLabel("-")
        for lbl in (
            self._root_label,
            self._settings_label,
            self._input_label,
            self._output_label,
            self._prompts_label,
            self._status_label,
        ):
            lbl.setTextInteractionFlags(lbl.textInteractionFlags() | Qt.TextSelectableByMouse)
        paths_form.addRow("Root:", self._root_label)
        paths_form.addRow("settings.yaml:", self._settings_label)
        paths_form.addRow("input/:", self._input_label)
        paths_form.addRow("output/:", self._output_label)
        paths_form.addRow("prompts/:", self._prompts_label)
        paths_form.addRow("Status:", self._status_label)
        root_layout.addWidget(self._paths_group)

        # Editors
        editor_tabs = QTabWidget()
        # --- settings.yaml editor ---
        settings_widget = QWidget()
        sv = QVBoxLayout(settings_widget)
        self._settings_editor = QPlainTextEdit()
        self._settings_editor.setFont(QFont("monospace"))
        self._settings_editor.setPlaceholderText("settings.yaml will be loaded here.")
        sv.addWidget(self._settings_editor)
        s_btns = QHBoxLayout()
        self._reload_settings_btn = QPushButton("Reload")
        self._save_settings_btn = QPushButton("Save settings.yaml")
        s_btns.addStretch(1)
        s_btns.addWidget(self._reload_settings_btn)
        s_btns.addWidget(self._save_settings_btn)
        sv.addLayout(s_btns)
        editor_tabs.addTab(settings_widget, "settings.yaml")

        # --- .env editor ---
        env_widget = QWidget()
        ev = QVBoxLayout(env_widget)
        self._env_editor = QPlainTextEdit()
        self._env_editor.setFont(QFont("monospace"))
        self._env_editor.setPlaceholderText("Lines like  OPENAI_API_KEY=sk-...")
        ev.addWidget(self._env_editor)
        e_btns = QHBoxLayout()
        self._reload_env_btn = QPushButton("Reload")
        self._save_env_btn = QPushButton("Save .env")
        e_btns.addStretch(1)
        e_btns.addWidget(self._reload_env_btn)
        e_btns.addWidget(self._save_env_btn)
        ev.addLayout(e_btns)
        editor_tabs.addTab(env_widget, ".env")

        root_layout.addWidget(editor_tabs, 1)

        # ---- helper-app launcher row ----
        helper_row = QHBoxLayout()
        helper_row.addStretch(1)
        helper_row.addWidget(QLabel("Need to ingest a PDF?"))
        self._pdf_helper_btn = QPushButton("Open PDF → TXT helper")
        self._pdf_helper_btn.setToolTip(
            "Launch the standalone helper that converts PDFs to .txt files,\n"
            "defaulting to write into this project's input/ folder."
        )
        helper_row.addWidget(self._pdf_helper_btn)
        root_layout.addLayout(helper_row)
        self._pdf_helper_btn.clicked.connect(self._on_open_pdf_helper)

        self._helper_window = None  # keep a reference so it isn't garbage-collected

        self._reload_settings_btn.clicked.connect(self._reload_settings)
        self._save_settings_btn.clicked.connect(self._save_settings)
        self._reload_env_btn.clicked.connect(self._reload_env)
        self._save_env_btn.clicked.connect(self._save_env)

    # ---- public ----
    def set_project(self, project: GraphRAGProject | None) -> None:
        self._project = project
        if project is None:
            self._root_label.setText("(no project)")
            self._settings_label.setText("-")
            self._input_label.setText("-")
            self._output_label.setText("-")
            self._prompts_label.setText("-")
            self._status_label.setText("-")
            self._settings_editor.clear()
            self._env_editor.clear()
            return
        self._root_label.setText(str(project.root))
        self._settings_label.setText(str(project.settings_path))
        self._input_label.setText(str(project.input_dir))
        self._output_label.setText(str(project.output_dir))
        self._prompts_label.setText(str(project.prompts_dir))
        bits = []
        bits.append("initialized" if project.is_initialized() else "not initialized")
        bits.append("indexed" if project.is_indexed() else "not indexed")
        self._status_label.setText(" · ".join(bits))
        self._reload_settings()
        self._reload_env()

    # ---- handlers ----
    def _reload_settings(self) -> None:
        if not self._project or not self._project.settings_path.exists():
            self._settings_editor.setPlainText("")
            return
        self._settings_editor.setPlainText(self._project.settings_path.read_text())

    def _save_settings(self) -> None:
        if not self._project:
            return
        try:
            self._project.settings_path.write_text(self._settings_editor.toPlainText())
        except OSError as exc:
            QMessageBox.critical(self, "Save failed", str(exc))
            return
        QMessageBox.information(self, "Saved", "settings.yaml updated.")
        self.settings_saved.emit()

    def _reload_env(self) -> None:
        if not self._project or not self._project.env_path.exists():
            self._env_editor.setPlainText("")
            return
        self._env_editor.setPlainText(self._project.env_path.read_text())

    def _on_open_pdf_helper(self) -> None:
        from ..pdf_to_text import PdfToTextWindow
        if self._helper_window is None or not self._helper_window.isVisible():
            self._helper_window = PdfToTextWindow()
            # Pre-fill the output folder with this project's input dir.
            if self._project:
                self._helper_window._out_edit.setText(str(self._project.input_dir))
        self._helper_window.show()
        self._helper_window.raise_()
        self._helper_window.activateWindow()

    def _save_env(self) -> None:
        if not self._project:
            return
        try:
            self._project.env_path.write_text(self._env_editor.toPlainText())
        except OSError as exc:
            QMessageBox.critical(self, "Save failed", str(exc))
            return
        QMessageBox.information(self, "Saved", ".env updated.")
