"""Cross-run deduplication via a JSON seen-store.

The store maps an article id -> {first_seen, path, source_id}. Articles whose
id is already present are skipped on subsequent runs, so the pipeline is
idempotent: running it twice does not duplicate files.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path


class SeenStore:
    def __init__(self, path: Path):
        self.path = Path(path)
        self._data: dict[str, dict] = {}
        self._load()

    def _load(self) -> None:
        if self.path.exists():
            try:
                self._data = json.loads(self.path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                self._data = {}

    def __contains__(self, article_id: str) -> bool:
        return article_id in self._data

    def __len__(self) -> int:
        return len(self._data)

    def record(self, article_id: str, rel_path: str, source_id: str) -> None:
        if article_id not in self._data:
            self._data[article_id] = {
                "first_seen": datetime.now(timezone.utc).isoformat(),
                "path": rel_path,
                "source_id": source_id,
            }

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(self.path.suffix + ".tmp")
        tmp.write_text(json.dumps(self._data, indent=2, sort_keys=True), encoding="utf-8")
        tmp.replace(self.path)
