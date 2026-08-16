"""Model provider profiles and settings.yaml patching."""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Literal

from ruamel.yaml import YAML

from .paths import providers_path

ProviderKind = Literal["openai", "ollama", "lmstudio", "custom"]


@dataclass
class Profile:
    name: str
    kind: ProviderKind = "openai"
    api_base: str = "https://api.openai.com/v1"
    completion_model: str = "gpt-4o-mini"
    embedding_model: str = "text-embedding-3-small"
    api_key: str = ""  # literal value written to settings.yaml ("NONE" for local)
    api_key_env: str = ""  # alternative: env-var reference like "OPENAI_API_KEY"
    embedding_api_base: str = ""  # optional override; falls back to api_base

    def effective_api_key_value(self) -> str:
        """Value to write into settings.yaml for api_key."""
        if self.api_key_env:
            return "${" + self.api_key_env + "}"
        return self.api_key or "NONE"


DEFAULT_PROFILES: list[Profile] = [
    Profile(
        name="OpenAI Cloud",
        kind="openai",
        api_base="https://api.openai.com/v1",
        completion_model="gpt-4o",
        embedding_model="text-embedding-3-small",
        api_key_env="OPENAI_API_KEY",
    ),
    Profile(
        name="Ollama local",
        kind="ollama",
        api_base="http://localhost:11434/v1",
        completion_model="llama-krikri-8b-instruct",
        embedding_model="nomic-embed-text-v2-moe",
        api_key="NONE",
    ),
    Profile(
        name="LM Studio",
        kind="lmstudio",
        api_base="http://localhost:1234/v1",
        completion_model="llama-krikri-8b-instruct",
        embedding_model="text-embedding-nomic-embed-text-v2-moe",
        embedding_api_base="http://localhost:1234/v1",
        api_key="NONE",
    ),
    Profile(
        name="Ollama @ Vast.ai (Gemma-4 31B)",
        kind="ollama",
        api_base="http://<VAST_IP>:<VAST_PORT>/v1",
        completion_model="gemma4:31b",
        embedding_model="nomic-embed-text-v2-moe",
        api_key="NONE",
    ),
    Profile(
        name="Ollama @ Vast.ai (Krikri-8B Q8)",
        kind="ollama",
        api_base="http://<VAST_IP>:<VAST_PORT>/v1",
        completion_model="ilsp/llama-krikri-8b-instruct:q8_0",
        embedding_model="nomic-embed-text-v2-moe",
        api_key="NONE",
    ),
]


@dataclass
class ProviderStore:
    profiles: list[Profile] = field(default_factory=list)
    active: str = ""

    @classmethod
    def load(cls) -> "ProviderStore":
        p = providers_path()
        if not p.exists():
            store = cls(profiles=list(DEFAULT_PROFILES), active=DEFAULT_PROFILES[0].name)
            store.save()
            return store
        try:
            raw = json.loads(p.read_text())
            profiles = [Profile(**d) for d in raw.get("profiles", [])]
            return cls(profiles=profiles, active=raw.get("active", ""))
        except Exception:
            store = cls(profiles=list(DEFAULT_PROFILES), active=DEFAULT_PROFILES[0].name)
            store.save()
            return store

    def save(self) -> None:
        providers_path().write_text(
            json.dumps(
                {"profiles": [asdict(p) for p in self.profiles], "active": self.active},
                indent=2,
            )
        )

    def get(self, name: str) -> Profile | None:
        return next((p for p in self.profiles if p.name == name), None)

    def upsert(self, profile: Profile) -> None:
        for i, p in enumerate(self.profiles):
            if p.name == profile.name:
                self.profiles[i] = profile
                return
        self.profiles.append(profile)

    def remove(self, name: str) -> None:
        self.profiles = [p for p in self.profiles if p.name != name]
        if self.active == name:
            self.active = self.profiles[0].name if self.profiles else ""


# ---------- settings.yaml patching ----------

_yaml = YAML()
_yaml.preserve_quotes = True
_yaml.width = 4096


def _load_yaml(path: Path):
    with path.open("r") as f:
        return _yaml.load(f)


def _dump_yaml(data, path: Path) -> None:
    with path.open("w") as f:
        _yaml.dump(data, f)


def apply_profile_to_settings(profile: Profile, settings_yaml: Path) -> str:
    """Patch <root>/settings.yaml with the given profile. Returns a short diff summary."""
    data = _load_yaml(settings_yaml)

    completion_block = data.setdefault("completion_models", {})
    embedding_block = data.setdefault("embedding_models", {})

    comp = completion_block.get("default_completion_model") or {}
    emb = embedding_block.get("default_embedding_model") or {}

    api_key_val = profile.effective_api_key_value()

    comp["model_provider"] = "openai"
    comp["model"] = profile.completion_model
    comp["auth_method"] = "api_key"
    comp["api_key"] = api_key_val
    comp["api_base"] = profile.api_base

    emb["model_provider"] = "openai"
    emb["model"] = profile.embedding_model
    emb["auth_method"] = "api_key"
    emb["api_key"] = api_key_val
    emb["api_base"] = profile.embedding_api_base or profile.api_base

    completion_block["default_completion_model"] = comp
    embedding_block["default_embedding_model"] = emb

    _dump_yaml(data, settings_yaml)
    return (
        f"completion: {profile.completion_model} @ {profile.api_base}\n"
        f"embedding:  {profile.embedding_model} @ {profile.embedding_api_base or profile.api_base}\n"
        f"api_key:    {api_key_val}"
    )


def read_settings_summary(settings_yaml: Path) -> str:
    """Return a one-line summary of the current models in a settings.yaml."""
    try:
        data = _load_yaml(settings_yaml)
        comp = (data.get("completion_models") or {}).get("default_completion_model") or {}
        emb = (data.get("embedding_models") or {}).get("default_embedding_model") or {}
        return (
            f"completion: {comp.get('model', '?')} @ {comp.get('api_base', '(default)')}  |  "
            f"embedding: {emb.get('model', '?')} @ {emb.get('api_base', '(default)')}"
        )
    except Exception as e:  # noqa: BLE001
        return f"(unable to read settings.yaml: {e})"
