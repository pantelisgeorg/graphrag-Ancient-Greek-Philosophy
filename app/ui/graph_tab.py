"""Graph tab — inline pyvis preview + 'Open in Neo4j' button."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QUrl
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWidgets import (
    QApplication,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from ..graph_viz import build_cytoscape_html
from ..neo4j_loader import push_to_neo4j
from ..project import GraphRAGProject


class GraphTab(QWidget):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._project: GraphRAGProject | None = None

        root = QVBoxLayout(self)

        controls = QGroupBox("Visualization")
        cl = QHBoxLayout(controls)
        cl.addWidget(QLabel("Community level:"))
        self._level = QSpinBox()
        self._level.setRange(0, 5)
        self._level.setValue(0)
        self._level.setToolTip(
            "Which level of the Leiden community hierarchy to color the nodes by.\n"
            "0 = broadest (top-level groupings), higher = more granular sub-groups."
        )
        cl.addWidget(self._level)
        cl.addWidget(QLabel("Max nodes:"))
        self._max_nodes = QSpinBox()
        self._max_nodes.setRange(20, 5000)
        self._max_nodes.setValue(500)
        self._max_nodes.setToolTip(
            "Cap the number of nodes (highest-degree kept). Lower it if the view is sluggish."
        )
        cl.addWidget(self._max_nodes)
        self._rebuild_btn = QPushButton("Rebuild preview")
        cl.addWidget(self._rebuild_btn)
        cl.addStretch(1)
        self._neo4j_btn = QPushButton("Open in Neo4j")
        self._neo4j_btn.setToolTip(
            "Push entities + relationships into Neo4j and open Neo4j Browser.\n"
            "Requires NEO4J_URI / NEO4J_USER / NEO4J_PASSWORD in the project's .env "
            "and a running Neo4j DBMS (e.g. Neo4j Desktop)."
        )
        cl.addWidget(self._neo4j_btn)
        root.addWidget(controls)

        self._status = QLabel(
            "Open a project, then click 'Rebuild preview'. "
            "Inside the view: drag to pan, scroll to zoom, click a node for details."
        )
        self._status.setWordWrap(True)
        root.addWidget(self._status)

        self._view = QWebEngineView()
        root.addWidget(self._view, 1)

        self._rebuild_btn.clicked.connect(self._rebuild)
        self._neo4j_btn.clicked.connect(self._open_neo4j)

    # ---- public ----
    def set_project(self, project: GraphRAGProject | None) -> None:
        self._project = project
        if project and project.is_indexed() and project.graph_html_path.exists():
            self._load_html(project.graph_html_path)
            self._status.setText(f"Showing cached preview: {project.graph_html_path}")
        else:
            self._view.setHtml("")
            self._status.setText(
                "Open a project, then click 'Rebuild preview'. "
                "Inside the view: drag to pan, scroll to zoom, click a node for details."
            )

    # ---- actions ----
    def _rebuild(self) -> None:
        if not self._project:
            QMessageBox.warning(self, "No project", "Open a project first.")
            return
        if not self._project.is_indexed():
            QMessageBox.warning(self, "Not indexed", "No entities.parquet — run indexing first.")
            return
        try:
            path = build_cytoscape_html(
                self._project,
                level=self._level.value(),
                max_nodes=self._max_nodes.value(),
            )
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(self, "Build failed", str(exc))
            return
        self._load_html(path)
        self._status.setText(f"Rebuilt: {path}")

    def _open_neo4j(self) -> None:
        if not self._project:
            QMessageBox.warning(self, "No project", "Open a project first.")
            return
        if not self._project.is_indexed():
            QMessageBox.warning(self, "Not indexed", "No entities.parquet — run indexing first.")
            return
        self._neo4j_btn.setEnabled(False)
        self._status.setText("Pushing graph to Neo4j…")
        QApplication.processEvents()
        try:
            ok, msg = push_to_neo4j(self._project)
        finally:
            self._neo4j_btn.setEnabled(True)
        if ok:
            self._status.setText("✔ " + msg.splitlines()[0])
            QMessageBox.information(self, "Neo4j", msg)
        else:
            self._status.setText("Neo4j load failed — see dialog.")
            QMessageBox.warning(self, "Neo4j", msg)

    def _load_html(self, path: Path) -> None:
        self._view.load(QUrl.fromLocalFile(str(path)))
