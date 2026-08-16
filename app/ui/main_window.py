"""Main window — toolbar (project picker + provider chip) and tab container."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QAction
from PySide6.QtWidgets import (
    QComboBox,
    QFileDialog,
    QLabel,
    QMainWindow,
    QMessageBox,
    QStatusBar,
    QTabWidget,
    QToolBar,
)

from ..project import GraphRAGProject, load_recent_projects, save_recent_projects
from ..providers import ProviderStore, read_settings_summary
from .data_tab import DataTab
from .graph_tab import GraphTab
from .index_tab import IndexTab
from .projects_tab import ProjectsTab
from .prompts_tab import PromptsTab
from .providers_tab import ProvidersTab
from .query_tab import QueryTab


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("GraphRAG GUI")
        self.resize(1280, 860)

        self._providers = ProviderStore.load()
        self._recents: list[Path] = load_recent_projects()
        self._project: GraphRAGProject | None = None

        # ---- toolbar ----
        tb = QToolBar("Project")
        tb.setMovable(False)
        self.addToolBar(tb)

        tb.addWidget(QLabel(" Project: "))
        self._project_combo = QComboBox()
        self._project_combo.setMinimumWidth(420)
        tb.addWidget(self._project_combo)

        open_action = QAction("Open…", self)
        open_action.triggered.connect(self._on_open_project)
        tb.addAction(open_action)

        new_action = QAction("New empty…", self)
        new_action.triggered.connect(self._on_new_project)
        tb.addAction(new_action)

        tb.addSeparator()
        tb.addWidget(QLabel(" Active provider: "))
        self._provider_chip = QLabel("(none)")
        self._provider_chip.setStyleSheet("padding: 2px 8px; border: 1px solid #888; border-radius: 8px;")
        tb.addWidget(self._provider_chip)

        # ---- tabs ----
        self._tabs = QTabWidget()
        self.setCentralWidget(self._tabs)

        self._projects_tab = ProjectsTab()
        self._providers_tab = ProvidersTab(self._providers)
        self._index_tab = IndexTab()
        self._query_tab = QueryTab()
        self._data_tab = DataTab()
        self._graph_tab = GraphTab()
        self._prompts_tab = PromptsTab()

        self._tabs.addTab(self._projects_tab, "Project")
        self._tabs.addTab(self._providers_tab, "Providers")
        self._tabs.addTab(self._index_tab, "Index")
        self._tabs.addTab(self._query_tab, "Query")
        self._tabs.addTab(self._data_tab, "Data")
        self._tabs.addTab(self._graph_tab, "Graph")
        self._tabs.addTab(self._prompts_tab, "Prompts")

        # ---- status bar ----
        self.setStatusBar(QStatusBar())
        self._update_settings_status()

        # ---- wiring ----
        self._project_combo.currentIndexChanged.connect(self._on_project_changed)
        self._projects_tab.settings_saved.connect(self._update_settings_status)
        self._providers_tab.profile_applied.connect(self._on_profile_applied)
        self._providers_tab.profiles_changed.connect(self._refresh_provider_chip)
        self._index_tab.reset_done.connect(self._on_reset_done)

        self._refresh_project_combo()
        self._refresh_provider_chip()

    # ---- project management ----
    def _refresh_project_combo(self) -> None:
        self._project_combo.blockSignals(True)
        self._project_combo.clear()
        for p in self._recents:
            self._project_combo.addItem(str(p), str(p))
        self._project_combo.blockSignals(False)
        if self._recents:
            self._project_combo.setCurrentIndex(0)
            self._activate_project(self._recents[0])
        else:
            self._activate_project(None)

    def _on_project_changed(self, idx: int) -> None:
        if idx < 0 or idx >= len(self._recents):
            return
        self._activate_project(self._recents[idx])

    def _on_reset_done(self) -> None:
        if self._project:
            self._activate_project(self._project.root)

    def _activate_project(self, root: Path | None) -> None:
        project = GraphRAGProject(root) if root else None
        self._project = project
        self._projects_tab.set_project(project)
        self._providers_tab.set_project(project)
        self._index_tab.set_project(project)
        self._query_tab.set_project(project)
        self._data_tab.set_project(project)
        self._graph_tab.set_project(project)
        self._prompts_tab.set_project(project)
        self._update_settings_status()

    def _on_open_project(self) -> None:
        path = QFileDialog.getExistingDirectory(self, "Open GraphRAG project root")
        if not path:
            return
        self._add_and_select(Path(path))

    def _on_new_project(self) -> None:
        path = QFileDialog.getExistingDirectory(
            self,
            "Pick a folder for the new project (will be created if needed)",
        )
        if not path:
            return
        Path(path).mkdir(parents=True, exist_ok=True)
        self._add_and_select(Path(path))
        QMessageBox.information(
            self,
            "Initialize project",
            "Folder added. Switch to the Index tab and click 'Initialize project' to create settings.yaml.",
        )

    def _add_and_select(self, root: Path) -> None:
        # newest first
        self._recents = [root] + [p for p in self._recents if str(p.resolve()) != str(root.resolve())]
        save_recent_projects(self._recents)
        self._refresh_project_combo()

    # ---- providers ----
    def _refresh_provider_chip(self) -> None:
        active = self._providers.active or "(none)"
        self._provider_chip.setText(active)

    def _on_profile_applied(self, name: str) -> None:
        self._providers.active = name
        self._providers.save()
        self._refresh_provider_chip()
        self._update_settings_status()
        # Reload settings.yaml view in the Project tab.
        self._projects_tab.set_project(self._project)

    # ---- status bar ----
    def _update_settings_status(self) -> None:
        if self._project and self._project.settings_path.exists():
            msg = read_settings_summary(self._project.settings_path)
            self.statusBar().showMessage(msg)
        else:
            self.statusBar().showMessage("No project loaded.")
