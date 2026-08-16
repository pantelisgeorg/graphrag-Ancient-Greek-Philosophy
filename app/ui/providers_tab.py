"""Providers tab — manage saved profiles (OpenAI / Ollama / LM Studio / custom)
and apply one to the active project's settings.yaml."""
from __future__ import annotations

from dataclasses import replace

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QComboBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from ..project import GraphRAGProject
from ..providers import Profile, ProviderStore, apply_profile_to_settings


KIND_CHOICES: list[tuple[str, str]] = [
    ("openai", "OpenAI"),
    ("ollama", "Ollama"),
    ("lmstudio", "LM Studio"),
    ("custom", "Custom (OpenAI-compatible)"),
]


class ProvidersTab(QWidget):
    profiles_changed = Signal()
    profile_applied = Signal(str)  # profile name

    def __init__(self, store: ProviderStore, parent=None) -> None:
        super().__init__(parent)
        self._store = store
        self._project: GraphRAGProject | None = None
        self._suppress = False

        outer = QHBoxLayout(self)
        splitter = QSplitter()
        outer.addWidget(splitter)

        # ---- left: profile list + buttons ----
        left = QWidget()
        ll = QVBoxLayout(left)
        ll.addWidget(QLabel("Saved profiles"))
        self._list = QListWidget()
        ll.addWidget(self._list, 1)

        list_btns = QHBoxLayout()
        self._new_btn = QPushButton("New…")
        self._delete_btn = QPushButton("Delete")
        list_btns.addWidget(self._new_btn)
        list_btns.addWidget(self._delete_btn)
        ll.addLayout(list_btns)

        splitter.addWidget(left)

        # ---- right: editor form ----
        right = QWidget()
        rl = QVBoxLayout(right)

        form_group = QGroupBox("Profile")
        form = QFormLayout(form_group)

        self._name_edit = QLineEdit()
        self._kind_combo = QComboBox()
        for key, label in KIND_CHOICES:
            self._kind_combo.addItem(label, key)
        self._api_base_edit = QLineEdit()
        self._completion_edit = QLineEdit()
        self._embedding_edit = QLineEdit()
        self._embedding_base_edit = QLineEdit()
        self._embedding_base_edit.setPlaceholderText("(blank = same as API base)")
        self._api_key_edit = QLineEdit()
        self._api_key_edit.setEchoMode(QLineEdit.Password)
        self._api_key_edit.setPlaceholderText("literal value or leave blank")
        self._api_key_env_edit = QLineEdit()
        self._api_key_env_edit.setPlaceholderText("e.g. OPENAI_API_KEY (takes priority over literal)")

        form.addRow("Name:", self._name_edit)
        form.addRow("Kind:", self._kind_combo)
        form.addRow("API base:", self._api_base_edit)
        form.addRow("Completion model:", self._completion_edit)
        form.addRow("Embedding model:", self._embedding_edit)
        form.addRow("Embedding API base:", self._embedding_base_edit)
        form.addRow("API key (literal):", self._api_key_edit)
        form.addRow("API key (env name):", self._api_key_env_edit)
        rl.addWidget(form_group)

        action_row = QHBoxLayout()
        self._save_btn = QPushButton("Save changes")
        self._apply_btn = QPushButton("Apply to project")
        action_row.addStretch(1)
        action_row.addWidget(self._save_btn)
        action_row.addWidget(self._apply_btn)
        rl.addLayout(action_row)

        self._summary = QLabel("")
        self._summary.setWordWrap(True)
        rl.addWidget(self._summary)
        rl.addStretch(1)

        splitter.addWidget(right)
        splitter.setSizes([240, 600])

        self._populate_list()

        self._list.currentItemChanged.connect(self._on_select)
        self._new_btn.clicked.connect(self._on_new)
        self._delete_btn.clicked.connect(self._on_delete)
        self._save_btn.clicked.connect(self._on_save)
        self._apply_btn.clicked.connect(self._on_apply)

    # ---- public ----
    def set_project(self, project: GraphRAGProject | None) -> None:
        self._project = project
        self._summary.setText("")

    def active_profile(self) -> Profile | None:
        return self._store.get(self._store.active) if self._store.active else None

    # ---- list ----
    def _populate_list(self) -> None:
        self._suppress = True
        self._list.clear()
        for p in self._store.profiles:
            item = QListWidgetItem(p.name)
            item.setData(0x100, p.name)
            self._list.addItem(item)
            if p.name == self._store.active:
                self._list.setCurrentItem(item)
        if self._list.currentItem() is None and self._list.count():
            self._list.setCurrentRow(0)
        self._suppress = False
        self._load_current()

    def _load_current(self) -> None:
        item = self._list.currentItem()
        if not item:
            return
        p = self._store.get(item.text())
        if not p:
            return
        self._suppress = True
        self._name_edit.setText(p.name)
        idx = self._kind_combo.findData(p.kind)
        self._kind_combo.setCurrentIndex(idx if idx >= 0 else 0)
        self._api_base_edit.setText(p.api_base)
        self._completion_edit.setText(p.completion_model)
        self._embedding_edit.setText(p.embedding_model)
        self._embedding_base_edit.setText(p.embedding_api_base)
        self._api_key_edit.setText(p.api_key)
        self._api_key_env_edit.setText(p.api_key_env)
        self._suppress = False

    # ---- handlers ----
    def _on_select(self, current, _previous) -> None:
        if self._suppress or not current:
            return
        self._store.active = current.text()
        self._store.save()
        self._load_current()
        self.profiles_changed.emit()

    def _on_new(self) -> None:
        name, ok = QInputDialog.getText(self, "New profile", "Profile name:")
        if not ok or not name.strip():
            return
        name = name.strip()
        if self._store.get(name):
            QMessageBox.warning(self, "Duplicate", "A profile with that name already exists.")
            return
        new_profile = Profile(name=name, kind="custom", api_base="http://localhost:1234/v1")
        self._store.upsert(new_profile)
        self._store.active = name
        self._store.save()
        self._populate_list()
        self.profiles_changed.emit()

    def _on_delete(self) -> None:
        item = self._list.currentItem()
        if not item:
            return
        name = item.text()
        if QMessageBox.question(self, "Delete", f"Delete profile '{name}'?") != QMessageBox.Yes:
            return
        self._store.remove(name)
        self._store.save()
        self._populate_list()
        self.profiles_changed.emit()

    def _build_profile_from_form(self) -> Profile:
        return Profile(
            name=self._name_edit.text().strip(),
            kind=self._kind_combo.currentData(),
            api_base=self._api_base_edit.text().strip(),
            completion_model=self._completion_edit.text().strip(),
            embedding_model=self._embedding_edit.text().strip(),
            embedding_api_base=self._embedding_base_edit.text().strip(),
            api_key=self._api_key_edit.text().strip(),
            api_key_env=self._api_key_env_edit.text().strip(),
        )

    def _on_save(self) -> None:
        item = self._list.currentItem()
        if not item:
            return
        original_name = item.text()
        new = self._build_profile_from_form()
        if not new.name:
            QMessageBox.warning(self, "Save", "Name cannot be empty.")
            return
        if new.name != original_name and self._store.get(new.name):
            QMessageBox.warning(self, "Save", "A profile with the new name already exists.")
            return
        # Remove old, add new
        self._store.remove(original_name)
        self._store.upsert(new)
        if self._store.active == original_name:
            self._store.active = new.name
        self._store.save()
        self._populate_list()
        self.profiles_changed.emit()

    def _on_apply(self) -> None:
        if not self._project:
            QMessageBox.warning(self, "Apply", "No project selected.")
            return
        if not self._project.settings_path.exists():
            QMessageBox.warning(
                self,
                "Apply",
                "settings.yaml does not exist yet. Run 'Initialize' in the Index tab first.",
            )
            return
        profile = self._build_profile_from_form()
        if not profile.api_base or not profile.completion_model or not profile.embedding_model:
            QMessageBox.warning(
                self,
                "Apply",
                "API base, completion model, and embedding model must all be set.",
            )
            return
        try:
            summary = apply_profile_to_settings(profile, self._project.settings_path)
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(self, "Apply failed", str(exc))
            return
        self._summary.setText("✔ Applied to settings.yaml\n" + summary)
        self.profile_applied.emit(profile.name)
