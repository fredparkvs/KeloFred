"""Configuration loading (env vars + optional YAML)."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

try:
    import yaml
except ImportError:  # yaml optional; env-only still works
    yaml = None

DEFAULT_CREDS = Path.home() / ".config" / "keloray" / "creds.json"


@dataclass
class Config:
    app_id: str = ""
    region: str = "cn"
    username: str = ""
    password: str = ""
    creds_path: str = str(DEFAULT_CREDS)
    min_interval: float = 0.25
    rules: list[dict] = field(default_factory=list)

    @classmethod
    def load(cls, path: str | Path | None = None) -> "Config":
        data: dict[str, Any] = {}
        path = path or os.environ.get("KELORAY_CONFIG")
        if path and Path(path).exists():
            if not yaml:
                raise RuntimeError("pyyaml required to read a config file")
            data = yaml.safe_load(Path(path).read_text()) or {}
        # env overrides
        env = {
            "app_id": os.environ.get("KELORAY_APP_ID"),
            "region": os.environ.get("KELORAY_REGION"),
            "username": os.environ.get("KELORAY_USERNAME"),
            "password": os.environ.get("KELORAY_PASSWORD"),
        }
        for k, v in env.items():
            if v:
                data[k] = v
        known = {f for f in cls.__dataclass_fields__}
        return cls(**{k: v for k, v in data.items() if k in known})
