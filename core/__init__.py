"""Paquete central de lógica y procesamiento asíncrono de PDFs."""

from __future__ import annotations

from typing import Any

from core.exceptions import (
    InvalidPageRangeError,
    InvalidPasswordError,
    PDFCorruptedError,
    PDFEncryptedError,
    PDFStudioError,
    TaskCancelledError,
)
from core.history import HistoryEntry, OperationHistoryStore
from core.models import (
    CompressionLevel,
    ImageFormat,
    OperationResult,
    PageItemInstruction,
    QueuedFile,
    SignatureOverlay,
    ToolType,
    WatermarkConfig,
    WatermarkPosition,
)
from core.range_parser import parse_page_ranges, validate_page_ranges_realtime
from core.workers import (
    AsyncTaskManager,
    PDFOperationWorker,
    ThumbnailLRUCache,
    ThumbnailRenderWorker,
)

_LAZY_PDF_ENGINE_EXPORTS = frozenset(
    {"PDFEngine", "ensure_safe_output_path", "inspect_pdf_file"}
)


def __getattr__(name: str) -> Any:
    """Diferencia el import de core.pdf_engine hasta que algún llamador solicite sus símbolos."""
    if name in _LAZY_PDF_ENGINE_EXPORTS:
        import core.pdf_engine as pdf_engine_mod

        value = getattr(pdf_engine_mod, name)
        globals()[name] = value
        return value
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

__all__ = [
    "AsyncTaskManager",
    "CompressionLevel",
    "HistoryEntry",
    "ImageFormat",
    "InvalidPageRangeError",
    "InvalidPasswordError",
    "OperationHistoryStore",
    "OperationResult",
    "PDFCorruptedError",
    "PDFEncryptedError",
    "PDFEngine",
    "PDFOperationWorker",
    "PDFStudioError",
    "PageItemInstruction",
    "QueuedFile",
    "SignatureOverlay",
    "TaskCancelledError",
    "ThumbnailLRUCache",
    "ThumbnailRenderWorker",
    "ToolType",
    "WatermarkConfig",
    "WatermarkPosition",
    "ensure_safe_output_path",
    "inspect_pdf_file",
    "parse_page_ranges",
    "validate_page_ranges_realtime",
]

