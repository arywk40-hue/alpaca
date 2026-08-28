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

    def record_fetch_status(
        self,
        status: str,
        *,
        symbols: list[str],
        start: str,
        end: str,
        include_options: bool,
        error: str | None = None,
        counts: dict[str, int] | None = None,
    ) -> None:
        """Record whether a historical-data fetch reached a terminal state."""
        if status not in {"started", "completed", "failed"}:
            raise ValueError("fetch status must be started, completed, or failed")
        manifest = self._manifest()
        fetches = manifest.setdefault("fetches", [])
        fetches.append(
            {
                "status": status,
                "timestamp": datetime.now(UTC).isoformat(),
                "symbols": symbols,
                "start": start,
                "end": end,
                "include_options": include_options,
                **({"error": error} if error else {}),
                **({"counts": counts} if counts is not None else {}),
            }
        )
        self.root.mkdir(parents=True, exist_ok=True)
        self.manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")

    def _write(self, path: Path, payload: Any, **manifest: Any) -> Path:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        manifest_payload = self._manifest()
        entries = list(manifest_payload.get("entries", []))
        entries.append(
            {
                "path": str(path.relative_to(self.root)),
                "request_timestamp": datetime.now(UTC).isoformat(),
                "data_version": "alpaca-rest-v1",
                **manifest,
            }
        )
        self.root.mkdir(parents=True, exist_ok=True)
        manifest_payload["entries"] = entries
        self.manifest_path.write_text(
            json.dumps(manifest_payload, indent=2) + "\n", encoding="utf-8"
        )
        return path

    def _manifest(self) -> dict[str, Any]:
        if not self.manifest_path.exists():
            return {"entries": [], "fetches": []}
        try:
            loaded = json.loads(self.manifest_path.read_text(encoding="utf-8"))
            return loaded if isinstance(loaded, dict) else {"entries": [], "fetches": []}
        except (OSError, json.JSONDecodeError):
            return {"entries": [], "fetches": []}


def latest_fetch_status(root: str | Path) -> dict[str, Any] | None:
    """Return the last historical-fetch lifecycle entry, if it is readable."""
    manifest_path = Path(root) / "cache_manifest.json"
    if not manifest_path.exists():
        return None
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    fetches = manifest.get("fetches", []) if isinstance(manifest, dict) else []
    if not isinstance(fetches, list) or not fetches:
        return None
    latest = fetches[-1]
    return latest if isinstance(latest, dict) else None
