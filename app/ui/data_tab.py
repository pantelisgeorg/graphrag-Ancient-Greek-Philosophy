"""Data tab — browse all parquet outputs with filter + cell inspector."""
from __future__ import annotations

from pathlib import Path

import pandas as pd
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFileDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSplitter,
    QTableView,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from ..parquet_model import ParquetTableModel
from ..project import GraphRAGProject


class _ParquetView(QWidget):
    def __init__(self, name: str, parent=None) -> None:
        super().__init__(parent)
        self._name = name
        self._model = ParquetTableModel()
        v = QVBoxLayout(self)

        top = QHBoxLayout()
        self._row_count = QLabel("0 rows")
        self._filter = QLineEdit()
        self._filter.setPlaceholderText("filter (case-insensitive, any column)…")
        self._refresh_btn = QPushButton("Reload")
        self._export_btn = QPushButton("Export CSV…")
        top.addWidget(self._row_count)
        top.addWidget(self._filter, 1)
        top.addWidget(self._refresh_btn)
        top.addWidget(self._export_btn)
        v.addLayout(top)

        splitter = QSplitter(Qt.Vertical)
        self._table = QTableView()
        self._table.setModel(self._model)
        self._table.setSortingEnabled(True)
        self._table.horizontalHeader().setSectionResizeMode(QHeaderView.Interactive)
        self._table.horizontalHeader().setStretchLastSection(True)
        self._table.setSelectionBehavior(QTableView.SelectRows)
        splitter.addWidget(self._table)

        self._cell_view = QPlainTextEdit()
        self._cell_view.setReadOnly(True)
        self._cell_view.setPlaceholderText("Select a cell to see its full value…")
        self._cell_view.setMaximumHeight(220)
        splitter.addWidget(self._cell_view)
        splitter.setSizes([500, 200])
        v.addWidget(splitter, 1)

        self._filter.textChanged.connect(self._model.set_filter)
        self._table.selectionModel().currentChanged.connect(self._on_select)
        self._export_btn.clicked.connect(self._on_export)
        self._refresh_btn.clicked.connect(self._reload)

        self._project: GraphRAGProject | None = None

    def set_project(self, project: GraphRAGProject | None) -> None:
        self._project = project
        self._reload()

    def _reload(self) -> None:
        if not self._project:
            self._model.set_dataframe(pd.DataFrame())
            self._row_count.setText("0 rows")
            return
        df = self._project.load_parquet(self._name)
        self._model.set_dataframe(df)
        self._row_count.setText(f"{len(df):,} rows × {len(df.columns)} cols  ({self._name}.parquet)")

    def _on_select(self, current, _previous) -> None:
        if not current.isValid():
            return
        value = self._model.cell(current.row(), current.column())
        col_name = self._model.column_name(current.column())
        if value is None:
            self._cell_view.setPlainText("")
            return
        self._cell_view.setPlainText(f"[{col_name}]\n\n{value}")

    def _on_export(self) -> None:
        if not self._project:
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "Export CSV", f"{self._name}.csv", "CSV (*.csv)"
        )
        if not path:
            return
        try:
            self._model.dataframe().to_csv(path, index=False)
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(self, "Export failed", str(exc))


class DataTab(QWidget):
    NAMES = (
        "entities",
        "relationships",
        "communities",
        "community_reports",
        "text_units",
        "documents",
    )

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        root = QVBoxLayout(self)
        self._tabs = QTabWidget()
        self._views: dict[str, _ParquetView] = {}
        for n in self.NAMES:
            v = _ParquetView(n)
            self._views[n] = v
            self._tabs.addTab(v, n)
        root.addWidget(self._tabs)

    def set_project(self, project: GraphRAGProject | None) -> None:
        for v in self._views.values():
            v.set_project(project)
