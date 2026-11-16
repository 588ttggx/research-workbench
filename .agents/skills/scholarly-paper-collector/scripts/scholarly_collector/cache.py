from __future__ import annotations

import hashlib
import time
from pathlib import Path


class FileCache:
    def __init__(self, root: Path):
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)

    def path_for(self, namespace: str, key: str, suffix: str = ".json") -> Path:
        digest = hashlib.sha256(key.encode("utf-8")).hexdigest()
        directory = self.root / namespace
        directory.mkdir(parents=True, exist_ok=True)
        return directory / f"{digest}{suffix}"

    def read_text(self, namespace: str, key: str) -> str | None:
        path = self.path_for(namespace, key)
        if path.exists() and time.time() - path.stat().st_mtime < 86400:
            return path.read_text(encoding="utf-8")
        return None

    def write_text(self, namespace: str, key: str, value: str) -> None:
        self.path_for(namespace, key).write_text(value, encoding="utf-8")
