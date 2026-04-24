"""High-water-mark store. Three strategies map to the three operational
patterns demonstrated by the MVP: updated_at (periodic-global),
commit_sha (CI/CD-step), scan_id (on-demand).

Production backs the store with a Delta table (schema: key, subkey,
value, updated_at). Tests use a JSON file at the same interface."""

import json
from datetime import datetime, timezone
from pathlib import Path


class HwmStore:
    def __init__(self, path: Path):
        self.path = Path(path)
        if not self.path.exists():
            self.path.write_text("{}")

    def _load(self) -> dict:
        return json.loads(self.path.read_text() or "{}")

    def _save(self, data: dict) -> None:
        self.path.write_text(json.dumps(data))

    def get(self, key: str, subkey: str = "") -> str | None:
        data = self._load()
        return data.get(f"{key}::{subkey}")

    def set(self, key: str, value: str, subkey: str = "") -> None:
        data = self._load()
        data[f"{key}::{subkey}"] = value
        self._save(data)


class UpdatedAtHwm:
    _EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)

    def __init__(self, key: str, store: HwmStore):
        self.key = key
        self.store = store

    def read(self) -> datetime:
        raw = self.store.get(self.key)
        if raw is None:
            return self._EPOCH
        return datetime.fromisoformat(raw)

    def write(self, ts: datetime) -> None:
        if ts.tzinfo is None:
            raise ValueError("HWM timestamps must be timezone-aware")
        self.store.set(self.key, ts.isoformat())


class CommitShaHwm:
    def __init__(self, key: str, store: HwmStore):
        self.key = key
        self.store = store

    def read(self, repository_id: str) -> str | None:
        return self.store.get(self.key, subkey=repository_id)

    def write(self, repository_id: str, sha: str) -> None:
        self.store.set(self.key, sha, subkey=repository_id)


class ScanIdHwm:
    def __init__(self, key: str, store: HwmStore):
        self.key = key
        self.store = store

    def read(self) -> str | None:
        return self.store.get(self.key)

    def write(self, scan_id: str) -> None:
        self.store.set(self.key, scan_id)
