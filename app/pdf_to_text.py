"""Standalone PDF → .txt helper for GraphRAG ingest.

Drops cleaned text files into a project's `input/` directory.
Run with: ./pdf2txt.sh  (or  .venv/bin/python -m app.pdf_to_text)
"""
from __future__ import annotations

import os
import re
import sys
import traceback
from dataclasses import dataclass
from io import StringIO
from pathlib import Path

from PySide6.QtCore import QObject, QThread, Qt, Signal
from PySide6.QtGui import QFont, QTextCursor
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QSpinBox,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from .project import load_recent_projects


# ---------------- extraction ----------------

@dataclass
class ConvertOptions:
    page_first: int = 1            # 1-based, inclusive
    page_last: int = 0             # 0 = until end
    collapse_blank_lines: bool = True
    strip_hyphen_breaks: bool = True
    strip_page_numbers: bool = True
    strip_running_headers: bool = True
    drop_after_references: bool = False
    collapse_inner_whitespace: bool = True   # "word   word" → "word word"
    rewrap_paragraphs: bool = False          # join soft line wraps inside paragraphs


_PAGE_NUMBER_LINE = re.compile(r"^\s*(?:page\s*)?\d+\s*(?:of\s*\d+)?\s*$", re.IGNORECASE)
_REFERENCES_HEADING = re.compile(
    r"^\s*(references|bibliography|works cited)\s*$", re.IGNORECASE
)


def _extract_pdf_text(path: Path, opts: ConvertOptions) -> str:
    """Extract text from a PDF with pdfminer.six, respecting page range."""
    from pdfminer.high_level import extract_text_to_fp
    from pdfminer.layout import LAParams

    page_numbers: list[int] | None
    if opts.page_first <= 1 and opts.page_last == 0:
        page_numbers = None
    else:
        first = max(opts.page_first - 1, 0)
        if opts.page_last == 0:
            # pdfminer doesn't allow open-ended ranges via page_numbers; let it run all
            # then we'll trim before.
            page_numbers = None
        else:
            last = max(opts.page_last - 1, first)
            page_numbers = list(range(first, last + 1))

    buf = StringIO()
    with path.open("rb") as f:
        extract_text_to_fp(
            f,
            buf,
            page_numbers=page_numbers,
            laparams=LAParams(),
            output_type="text",
        )
    text = buf.getvalue()
    if page_numbers is None and opts.page_first > 1:
        # crude page split on form feed
        pages = text.split("\f")
        start = opts.page_first - 1
        text = "\f".join(pages[start:])
    return text


def _detect_repeated_headers_footers(text: str, min_repeats: int = 3) -> set[str]:
    """Lines that appear at the top or bottom of >=N pages are treated as headers/footers."""
    pages = text.split("\f")
    if len(pages) < min_repeats:
        return set()
    candidates: dict[str, int] = {}
    for page in pages:
        lines = [ln.strip() for ln in page.splitlines() if ln.strip()]
        if not lines:
            continue
        for line in (lines[:1] + lines[-1:]):
            if 3 <= len(line) <= 100:  # ignore very short or very long lines
                candidates[line] = candidates.get(line, 0) + 1
    return {line for line, count in candidates.items() if count >= min_repeats}


def _clean(text: str, opts: ConvertOptions) -> str:
    drop_lines = _detect_repeated_headers_footers(text) if opts.strip_running_headers else set()

    cleaned_lines: list[str] = []
    in_references = False
    for raw in text.splitlines():
        line = raw.rstrip()
        if "\f" in line:
            # keep page boundaries collapsible
            line = line.replace("\f", "")
        if opts.drop_after_references and _REFERENCES_HEADING.match(line):
            in_references = True
            continue
        if in_references:
            continue
        stripped = line.strip()
        if opts.strip_page_numbers and stripped and _PAGE_NUMBER_LINE.match(stripped):
            continue
        if stripped in drop_lines:
            continue
        cleaned_lines.append(line)

    out = "\n".join(cleaned_lines)

    if opts.strip_hyphen_breaks:
        # "infor-\nmation" -> "information"
        out = re.sub(r"-\n(?=\w)", "", out)

    if opts.collapse_inner_whitespace:
        # Replace runs of 2+ spaces/tabs *inside* a line with a single space.
        # Preserve newlines and any leading indentation.
        def _collapse(line: str) -> str:
            lead_len = len(line) - len(line.lstrip(" \t"))
            head, body = line[:lead_len], line[lead_len:]
            return head + re.sub(r"[ \t]{2,}", " ", body)
        out = "\n".join(_collapse(ln) for ln in out.splitlines())

    if opts.collapse_blank_lines:
        out = re.sub(r"\n{3,}", "\n\n", out)

    # Trim trailing spaces on each line
    out = "\n".join(ln.rstrip() for ln in out.splitlines()).strip() + "\n"

    if opts.rewrap_paragraphs:
        out = _rewrap_paragraphs(out)
    return out


def _rewrap_paragraphs(text: str) -> str:
    """Join soft line wraps within paragraphs, treating blank lines as paragraph breaks."""
    paragraphs = re.split(r"\n\s*\n", text)
    rewrapped: list[str] = []
    for para in paragraphs:
        lines = [ln.strip() for ln in para.splitlines() if ln.strip()]
        if not lines:
            continue
        # Heuristic: if any line in this group starts with a bullet/number marker,
        # leave it as-is (might be a list).
        if any(re.match(r"^(?:[-*•]|\d+[.)])\s", ln) for ln in lines):
            rewrapped.append("\n".join(lines))
        else:
            rewrapped.append(" ".join(lines))
    return "\n\n".join(rewrapped) + "\n"


def convert_pdf_to_text(pdf_path: Path, out_dir: Path, opts: ConvertOptions) -> Path:
    """Convert a single PDF to a .txt file. Returns the output path."""
    raw = _extract_pdf_text(pdf_path, opts)
    cleaned = _clean(raw, opts)
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / (pdf_path.stem + ".txt")
    out_path.write_text(cleaned)
    return out_path


# ---------------- worker thread ----------------

class _ConvertWorker(QThread):
    file_started = Signal(str)
    file_done = Signal(str, str, int)  # source, output_path, byte_size
    file_failed = Signal(str, str)
    all_done = Signal()

    def __init__(
        self,
        sources: list[Path],
        out_dir: Path,
        opts: ConvertOptions,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self.sources = sources
        self.out_dir = out_dir
        self.opts = opts
        self._cancel = False

    def request_cancel(self) -> None:
        self._cancel = True

    def run(self) -> None:
        for src in self.sources:
            if self._cancel:
                break
            self.file_started.emit(str(src))
            try:
                out = convert_pdf_to_text(src, self.out_dir, self.opts)
                self.file_done.emit(str(src), str(out), out.stat().st_size)
            except Exception as exc:  # noqa: BLE001
                self.file_failed.emit(str(src), f"{exc}\n{traceback.format_exc()}")
        self.all_done.emit()


# ---------------- UI ----------------

class PdfToTextWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("GraphRAG · PDF → TXT helper")
        self.resize(960, 720)

        self._worker: _ConvertWorker | None = None

        central = QWidget()
        root = QVBoxLayout(central)
        self.setCentralWidget(central)

        # ---- output folder ----
        out_group = QGroupBox("Output folder")
        og = QHBoxLayout(out_group)
        self._out_edit = QLineEdit()
        self._out_edit.setPlaceholderText("Where to write the .txt files (default: <recent project>/input)")
        og.addWidget(self._out_edit, 1)
        self._pick_out_btn = QPushButton("Browse…")
        og.addWidget(self._pick_out_btn)
        root.addWidget(out_group)

        # ---- options ----
        opts_group = QGroupBox("Cleanup options")
        ol = QFormLayout(opts_group)
        self._all_pages = QCheckBox("Convert all pages")
        self._all_pages.setChecked(True)
        self._page_first = QSpinBox()
        self._page_first.setRange(1, 99999)
        self._page_first.setValue(1)
        self._page_last = QSpinBox()
        self._page_last.setRange(1, 99999)
        self._page_last.setValue(1)

        page_row = QHBoxLayout()
        page_row.addWidget(self._all_pages)
        page_row.addSpacing(16)
        page_row.addWidget(QLabel("First:"))
        page_row.addWidget(self._page_first)
        page_row.addSpacing(12)
        page_row.addWidget(QLabel("Last:"))
        page_row.addWidget(self._page_last)
        page_row.addStretch(1)
        page_holder = QWidget()
        page_holder.setLayout(page_row)
        ol.addRow("Page range:", page_holder)

        def _sync_page_widgets() -> None:
            enabled = not self._all_pages.isChecked()
            self._page_first.setEnabled(enabled)
            self._page_last.setEnabled(enabled)
        self._all_pages.toggled.connect(lambda _=None: _sync_page_widgets())
        _sync_page_widgets()

        self._opt_collapse = QCheckBox("Collapse runs of blank lines")
        self._opt_collapse.setChecked(True)
        self._opt_hyphen = QCheckBox("Join hyphen-broken words at end of line")
        self._opt_hyphen.setChecked(True)
        self._opt_pagenums = QCheckBox("Drop standalone page-number lines")
        self._opt_pagenums.setChecked(True)
        self._opt_running = QCheckBox("Drop repeated headers / footers")
        self._opt_running.setChecked(True)
        self._opt_refs = QCheckBox("Drop everything after a 'References' heading")
        self._opt_refs.setChecked(False)
        self._opt_inner_ws = QCheckBox("Collapse multi-space runs inside lines  (recommended)")
        self._opt_inner_ws.setChecked(True)
        self._opt_rewrap = QCheckBox("Rewrap paragraphs (join soft line wraps within paragraphs)")
        self._opt_rewrap.setChecked(False)
        for cb in (
            self._opt_collapse,
            self._opt_hyphen,
            self._opt_pagenums,
            self._opt_running,
            self._opt_inner_ws,
            self._opt_rewrap,
            self._opt_refs,
        ):
            ol.addRow("", cb)
        root.addWidget(opts_group)

        # ---- file list + actions ----
        files_group = QGroupBox("PDFs to convert")
        fg = QVBoxLayout(files_group)
        self._files_list = QListWidget()
        fg.addWidget(self._files_list, 1)
        btn_row = QHBoxLayout()
        self._add_btn = QPushButton("Add PDFs…")
        self._remove_btn = QPushButton("Remove selected")
        self._clear_btn = QPushButton("Clear list")
        btn_row.addWidget(self._add_btn)
        btn_row.addWidget(self._remove_btn)
        btn_row.addWidget(self._clear_btn)
        btn_row.addStretch(1)
        self._convert_btn = QPushButton("Convert →  TXT")
        self._convert_btn.setDefault(True)
        self._cancel_btn = QPushButton("Cancel")
        self._cancel_btn.setEnabled(False)
        btn_row.addWidget(self._convert_btn)
        btn_row.addWidget(self._cancel_btn)
        fg.addLayout(btn_row)
        root.addWidget(files_group, 1)

        # ---- progress + log + preview ----
        self._progress = QProgressBar()
        self._progress.setRange(0, 100)
        root.addWidget(self._progress)

        splitter = QSplitter(Qt.Horizontal)
        self._log = QPlainTextEdit()
        self._log.setReadOnly(True)
        self._log.setMaximumBlockCount(10000)
        f = QFont("monospace")
        self._log.setFont(f)
        self._log.setPlaceholderText("Conversion log…")
        splitter.addWidget(self._log)
        preview_box = QWidget()
        pv = QVBoxLayout(preview_box)
        pv.setContentsMargins(0, 0, 0, 0)
        self._preview_header = QLabel("Preview (last converted file):")
        pv.addWidget(self._preview_header)
        self._preview = QPlainTextEdit()
        self._preview.setReadOnly(True)
        self._preview.setFont(f)
        self._preview.setPlaceholderText("After conversion, a sample of the .txt file will appear here.")
        pv.addWidget(self._preview, 1)
        splitter.addWidget(preview_box)
        splitter.setSizes([400, 500])
        root.addWidget(splitter, 1)

        # ---- wiring ----
        self._pick_out_btn.clicked.connect(self._on_pick_out)
        self._add_btn.clicked.connect(self._on_add)
        self._remove_btn.clicked.connect(self._on_remove)
        self._clear_btn.clicked.connect(self._files_list.clear)
        self._convert_btn.clicked.connect(self._on_convert)
        self._cancel_btn.clicked.connect(self._on_cancel)

        # Default output: first recent project's input dir
        recents = load_recent_projects()
        if recents:
            self._out_edit.setText(str(recents[0] / "input"))

    # ---- handlers ----
    def _on_pick_out(self) -> None:
        path = QFileDialog.getExistingDirectory(self, "Pick output folder")
        if path:
            self._out_edit.setText(path)

    def _on_add(self) -> None:
        paths, _ = QFileDialog.getOpenFileNames(
            self,
            "Pick PDF files",
            str(Path.home()),
            "PDF (*.pdf);;All files (*)",
        )
        for p in paths:
            if not p:
                continue
            for i in range(self._files_list.count()):
                if self._files_list.item(i).text() == p:
                    break
            else:
                item = QListWidgetItem(p)
                self._files_list.addItem(item)

    def _on_remove(self) -> None:
        for item in self._files_list.selectedItems():
            self._files_list.takeItem(self._files_list.row(item))

    def _build_opts(self) -> ConvertOptions:
        if self._all_pages.isChecked():
            page_first, page_last = 1, 0
        else:
            page_first = self._page_first.value()
            page_last = self._page_last.value()
            if page_last < page_first:
                page_last = page_first
        return ConvertOptions(
            page_first=page_first,
            page_last=page_last,
            collapse_blank_lines=self._opt_collapse.isChecked(),
            strip_hyphen_breaks=self._opt_hyphen.isChecked(),
            strip_page_numbers=self._opt_pagenums.isChecked(),
            strip_running_headers=self._opt_running.isChecked(),
            drop_after_references=self._opt_refs.isChecked(),
            collapse_inner_whitespace=self._opt_inner_ws.isChecked(),
            rewrap_paragraphs=self._opt_rewrap.isChecked(),
        )

    def _collect_sources(self) -> list[Path]:
        out: list[Path] = []
        for i in range(self._files_list.count()):
            p = Path(self._files_list.item(i).text())
            if p.exists():
                out.append(p)
            else:
                self._append_log(f"[skip] missing: {p}")
        return out

    def _on_convert(self) -> None:
        sources = self._collect_sources()
        if not sources:
            QMessageBox.information(self, "Nothing to do", "Add at least one PDF.")
            return
        out_dir = Path(self._out_edit.text().strip() or "").expanduser()
        if not str(out_dir):
            QMessageBox.warning(self, "Output", "Pick an output folder first.")
            return
        try:
            out_dir.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            QMessageBox.critical(self, "Output", f"Cannot create {out_dir}:\n{exc}")
            return

        self._log.clear()
        self._preview.clear()
        self._progress.setRange(0, len(sources))
        self._progress.setValue(0)
        self._set_busy(True)

        worker = _ConvertWorker(sources, out_dir, self._build_opts())
        self._done_count = 0
        worker.file_started.connect(self._on_file_started)
        worker.file_done.connect(self._on_file_done)
        worker.file_failed.connect(self._on_file_failed)
        worker.all_done.connect(self._on_all_done)
        worker.finished.connect(self._on_thread_finished)
        self._worker = worker
        worker.start()

    def _on_cancel(self) -> None:
        if self._worker:
            self._worker.request_cancel()
            self._append_log("[gui] cancel requested")

    # ---- worker slots ----
    def _on_file_started(self, src: str) -> None:
        self._append_log(f"→ {src}")

    def _on_file_done(self, src: str, out_path: str, size: int) -> None:
        self._done_count += 1
        self._progress.setValue(self._done_count)
        self._append_log(f"  ✓ {Path(out_path).name}  ({size:,} bytes)")
        try:
            data = Path(out_path).read_text(errors="replace")
        except OSError:
            data = ""
        PREVIEW_LIMIT = 6000
        truncated = len(data) > PREVIEW_LIMIT
        body = data[:PREVIEW_LIMIT]
        if truncated:
            body += f"\n\n… [preview truncated — full file is {len(data):,} chars on disk]"
        self._preview.setPlainText(body)
        self._preview_header.setText(
            f"Preview of {Path(out_path).name}  —  "
            f"{len(data):,} chars on disk"
            + ("  (showing first 6,000)" if truncated else "")
        )

    def _on_file_failed(self, src: str, msg: str) -> None:
        self._done_count += 1
        self._progress.setValue(self._done_count)
        self._append_log(f"  ✗ {Path(src).name}: {msg.splitlines()[0]}")

    def _on_all_done(self) -> None:
        self._append_log("[gui] done")
        self._set_busy(False)

    def _on_thread_finished(self) -> None:
        self._worker = None

    # ---- helpers ----
    def _append_log(self, line: str) -> None:
        self._log.appendPlainText(line)
        self._log.moveCursor(QTextCursor.End)

    def _set_busy(self, busy: bool) -> None:
        self._convert_btn.setEnabled(not busy)
        self._cancel_btn.setEnabled(busy)
        self._add_btn.setEnabled(not busy)
        self._remove_btn.setEnabled(not busy)
        self._clear_btn.setEnabled(not busy)


def main() -> int:
    os.environ.setdefault("QTWEBENGINE_CHROMIUM_FLAGS", "--no-sandbox")
    app = QApplication(sys.argv)
    app.setApplicationName("GraphRAG · PDF→TXT")
    w = PdfToTextWindow()
    w.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
