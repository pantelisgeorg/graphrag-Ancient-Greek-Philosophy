"""Qt table model over a pandas DataFrame, with text filtering."""
from __future__ import annotations

from typing import Any

import pandas as pd
from PySide6.QtCore import QAbstractTableModel, QModelIndex, Qt


def _shorten(value: Any, limit: int = 200) -> str:
    if value is None:
        return ""
    if isinstance(value, (list, tuple)):
        s = f"[{len(value)}] " + ", ".join(str(x) for x in value[:6])
        if len(value) > 6:
            s += ", …"
        return s
    s = str(value)
    if len(s) > limit:
        return s[: limit - 1] + "…"
    return s


class ParquetTableModel(QAbstractTableModel):
    def __init__(self, df: pd.DataFrame | None = None, parent=None):
        super().__init__(parent)
        self._df_full: pd.DataFrame = df if df is not None else pd.DataFrame()
        self._df: pd.DataFrame = self._df_full
        self._filter: str = ""

    # ---- public API ----
    def set_dataframe(self, df: pd.DataFrame) -> None:
        self.beginResetModel()
        self._df_full = df.reset_index(drop=True)
        self._apply_filter()
        self.endResetModel()

    def dataframe(self) -> pd.DataFrame:
        return self._df

    def set_filter(self, text: str) -> None:
        self._filter = text.strip()
        self.beginResetModel()
        self._apply_filter()
        self.endResetModel()

    def cell(self, row: int, col: int) -> Any:
        if 0 <= row < len(self._df) and 0 <= col < len(self._df.columns):
            return self._df.iat[row, col]
        return None

    def column_name(self, col: int) -> str:
        if 0 <= col < len(self._df.columns):
            return str(self._df.columns[col])
        return ""

    # ---- Qt overrides ----
    def rowCount(self, parent=QModelIndex()) -> int:
        return 0 if parent.isValid() else len(self._df)

    def columnCount(self, parent=QModelIndex()) -> int:
        return 0 if parent.isValid() else len(self._df.columns)

    def headerData(self, section, orientation, role=Qt.DisplayRole):
        if role != Qt.DisplayRole:
            return None
        if orientation == Qt.Horizontal:
            try:
                return str(self._df.columns[section])
            except IndexError:
                return None
        return section + 1

    def data(self, index, role=Qt.DisplayRole):
        if not index.isValid():
            return None
        if role in (Qt.DisplayRole, Qt.ToolTipRole):
            try:
                value = self._df.iat[index.row(), index.column()]
            except IndexError:
                return None
            if role == Qt.ToolTipRole:
                return _shorten(value, 1000)
            return _shorten(value)
        return None

    # ---- internals ----
    def _apply_filter(self) -> None:
        if not self._filter or self._df_full.empty:
            self._df = self._df_full
            return
        pat = self._filter
        # Match against any column as string
        mask = pd.Series(False, index=self._df_full.index)
        for col in self._df_full.columns:
            try:
                mask = mask | self._df_full[col].astype(str).str.contains(pat, case=False, na=False, regex=False)
            except Exception:  # noqa: BLE001
                continue
        self._df = self._df_full[mask].reset_index(drop=True)
