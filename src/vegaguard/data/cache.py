"""Reproducible on-disk cache for raw Alpaca responses and normalized records."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


class LocalMarketDataCache:
    """Keep network responses separate from portable normalized replay inputs."""

    def __init__(self, root: str | Path = "data") -> None:
        self.root = Path(root)
        self.raw_dir = self.root / "raw"
        self.normalized_dir = self.root / "normalized"
        self.manifest_path = self.root / "cache_manifest.json"

    def write_raw(
        self,
        name: str,
        payload: Any,
        *,
        endpoint: str,
        symbols: list[str],
        start: str | None,
        end: str | None,
        feed: str | None,
        data_kind: str,
        request_id: str | None = None,
        source: str = "Alpaca Market Data API",
    ) -> Path:
        return self._write(
            self.raw_dir / f"{name}.json",
            payload,
            endpoint=endpoint,
            symbols=symbols,
            start=start,
            end=end,
            feed=feed,
            data_kind=data_kind,
            request_id=request_id,
            source=source,
            normalized=False,
        )

    def write_normalized(
        self,
        name: str,
        records: Any,
        *,
        endpoint: str,
        symbols: list[str],
        start: str | None,
        end: str | None,
        feed: str | None,
        data_kind: str,
        request_id: str | None = None,
        source: str = "Alpaca Market Data API",
    ) -> Path:
        return self._write(
            self.normalized_dir / f"{name}.json",
            records,
            endpoint=endpoint,
            symbols=symbols,
            start=start,
            end=end,
            feed=feed,
            data_kind=data_kind,
            request_id=request_id,
            source=source,
            normalized=True,
        )

    def _write(self, path: Path, payload: Any, **manifest: Any) -> Path:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        entries = self._manifest_entries()
        entries.append(
            {
                "path": str(path.relative_to(self.root)),
                "request_timestamp": datetime.now(UTC).isoformat(),
                "data_version": "alpaca-rest-v1",
                **manifest,
            }
        )
        self.root.mkdir(parents=True, exist_ok=True)
        self.manifest_path.write_text(
            json.dumps({"entries": entries}, indent=2) + "\n", encoding="utf-8"
        )
        return path

    def _manifest_entries(self) -> list[dict[str, Any]]:
        if not self.manifest_path.exists():
            return []
        try:
            return list(
                json.loads(self.manifest_path.read_text(encoding="utf-8")).get("entries", [])
            )
        except (OSError, json.JSONDecodeError):
            return []
