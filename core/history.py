"""Persistencia local en JSON para las últimas 10 operaciones realizadas."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import json
from pathlib import Path

from core.models import OperationResult

MAX_HISTORY_ENTRIES = 10


@dataclass(slots=True)
class HistoryEntry:
    """Entrada serializable del historial de operaciones."""

    timestamp_iso: str
    tool: str
    output_files: list[str]
    original_size_bytes: int
    final_size_bytes: int
    saved_percentage: float
    message: str


class OperationHistoryStore:
    """Gestiona la lectura y escritura del historial JSON local (máximo 10 entradas)."""

    def __init__(self, storage_path: Path | None = None) -> None:
        if storage_path is None:
            storage_path = Path.home() / ".coquette_pdf_studio" / "history.json"
        self.storage_path = storage_path

    def load_entries(self) -> list[HistoryEntry]:
        """Carga las entradas almacenadas en disco."""
        if not self.storage_path.exists():
            return []
        try:
            raw_text = self.storage_path.read_text(encoding="utf-8")
            data = json.loads(raw_text)
            if not isinstance(data, list):
                return []
            entries: list[HistoryEntry] = []
            for item in data[:MAX_HISTORY_ENTRIES]:
                if isinstance(item, dict):
                    entries.append(
                        HistoryEntry(
                            timestamp_iso=str(item.get("timestamp_iso", "")),
                            tool=str(item.get("tool", "")),
                            output_files=[str(p) for p in item.get("output_files", [])],
                            original_size_bytes=int(item.get("original_size_bytes", 0)),
                            final_size_bytes=int(item.get("final_size_bytes", 0)),
                            saved_percentage=float(item.get("saved_percentage", 0.0)),
                            message=str(item.get("message", "")),
                        )
                    )
            return entries
        except (OSError, ValueError, TypeError):
            return []

    def record_operation(self, result: OperationResult) -> list[HistoryEntry]:
        """Registra una nueva operación al principio de la lista y trunca a 10 elementos."""
        entries = self.load_entries()
        new_entry = HistoryEntry(
            timestamp_iso=datetime.now(timezone.utc).isoformat(timespec="seconds"),
            tool=str(result.tool),
            output_files=[str(p) for p in result.output_files],
            original_size_bytes=result.original_size_bytes,
            final_size_bytes=result.final_size_bytes,
            saved_percentage=round(result.saved_percentage, 2),
            message=result.message,
        )
        updated = [new_entry, *entries][:MAX_HISTORY_ENTRIES]
        self._save_entries(updated)
        return updated

    def clear(self) -> None:
        """Limpia el historial persistido."""
        self._save_entries([])

    def _save_entries(self, entries: list[HistoryEntry]) -> None:
        self.storage_path.parent.mkdir(parents=True, exist_ok=True)
        payload = [asdict(entry) for entry in entries[:MAX_HISTORY_ENTRIES]]
        self.storage_path.write_text(
            json.dumps(payload, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

