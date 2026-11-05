"""Paquete central de lógica y procesamiento asíncrono de PDFs."""

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
from core.pdf_engine import PDFEngine, ensure_safe_output_path, inspect_pdf_file
from core.range_parser import parse_page_ranges, validate_page_ranges_realtime
from core.workers import (
    AsyncTaskManager,
    PDFOperationWorker,
    ThumbnailLRUCache,
    ThumbnailRenderWorker,
)

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

