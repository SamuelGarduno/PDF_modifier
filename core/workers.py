"""Workers asíncronos (QRunnable / QThreadPool) para ejecutar operaciones PDF y miniaturas sin bloquear la UI."""

from __future__ import annotations

from collections import OrderedDict
from collections.abc import Callable
from pathlib import Path
import threading
from typing import Any

from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal, Slot

from core.exceptions import PDFStudioError, TaskCancelledError
from core.models import OperationResult
from core.pdf_engine import DEFAULT_THUMBNAIL_DPI, PDFEngine

MAX_CACHED_THUMBNAILS = 80


class WorkerSignals(QObject):
    """Señales emitidas por un PDFOperationWorker hacia el hilo principal de Qt."""

    started = Signal()
    progress = Signal(int, str)
    finished = Signal(object)  # OperationResult
    cancelled = Signal(str)
    error = Signal(str)


class PDFOperationWorker(QRunnable):
    """Ejecuta una operación del PDFEngine en un hilo del QThreadPool con soporte de cancelación."""

    def __init__(
        self,
        task_fn: Callable[..., OperationResult],
        *args: Any,
        **kwargs: Any,
    ) -> None:
        super().__init__()
        self.setAutoDelete(True)
        self.signals = WorkerSignals()
        self._task_fn = task_fn
        self._args = args
        self._kwargs = kwargs
        self._cancel_event = threading.Event()

    def cancel(self) -> None:
        """Solicita la cancelación limpia de la tarea en curso."""
        self._cancel_event.set()

    def is_cancelled(self) -> bool:
        """Indica si se ha solicitado cancelar el worker."""
        return self._cancel_event.is_set()

    @Slot()
    def run(self) -> None:
        """Punto de entrada en el hilo secundario."""
        self.signals.started.emit()
        try:
            self._kwargs["on_progress"] = self._emit_progress
            self._kwargs["is_cancelled"] = self.is_cancelled
            result = self._task_fn(*self._args, **self._kwargs)
            if self.is_cancelled():
                self.signals.cancelled.emit("Operación cancelada por el usuario.")
                return
            self.signals.finished.emit(result)
        except TaskCancelledError as exc:
            self.signals.cancelled.emit(str(exc))
        except PDFStudioError as exc:
            self.signals.error.emit(str(exc))
        except Exception as exc:
            self.signals.error.emit(f"Error inesperado al procesar el PDF: {exc}")

    def _emit_progress(self, percent: int, message: str) -> None:
        if not self.is_cancelled():
            self.signals.progress.emit(percent, message)


class ThumbnailSignals(QObject):
    """Señales emitidas al terminar de renderizar una miniatura."""

    ready = Signal(str, int, bytes)  # file_path_str, page_index, png_bytes
    failed = Signal(str, int, str)  # file_path_str, page_index, error_msg


class ThumbnailRenderWorker(QRunnable):
    """Worker ligero para renderizar una página PDF a PNG con DPI controlado."""

    def __init__(
        self,
        file_path: Path,
        page_index: int,
        dpi: int = DEFAULT_THUMBNAIL_DPI,
        password: str | None = None,
        cache: ThumbnailLRUCache | None = None,
    ) -> None:
        super().__init__()
        self.setAutoDelete(True)
        self.signals = ThumbnailSignals()
        self.file_path = Path(file_path)
        self.page_index = page_index
        self.dpi = dpi
        self.password = password
        self._cache = cache

    @Slot()
    def run(self) -> None:
        key = (str(self.file_path.resolve()), self.page_index, self.dpi)
        if self._cache is not None:
            cached = self._cache.get(key)
            if cached is not None:
                self.signals.ready.emit(str(self.file_path), self.page_index, cached)
                return

        try:
            png_bytes = PDFEngine.render_page_png_bytes(
                self.file_path,
                self.page_index,
                dpi=self.dpi,
                password=self.password,
            )
            if self._cache is not None:
                self._cache.put(key, png_bytes)
            self.signals.ready.emit(str(self.file_path), self.page_index, png_bytes)
        except Exception as exc:
            self.signals.failed.emit(str(self.file_path), self.page_index, str(exc))


class ThumbnailLRUCache:
    """Caché LRU thread-safe acotada para mantener el uso de RAM bajo control (<300 MB en >200 páginas)."""

    def __init__(self, max_entries: int = MAX_CACHED_THUMBNAILS) -> None:
        self.max_entries = max(8, max_entries)
        self._store: OrderedDict[tuple[str, int, int], bytes] = OrderedDict()
        self._lock = threading.Lock()

    def get(self, key: tuple[str, int, int]) -> bytes | None:
        with self._lock:
            if key not in self._store:
                return None
            self._store.move_to_end(key)
            return self._store[key]

    def put(self, key: tuple[str, int, int], data: bytes) -> None:
        with self._lock:
            if key in self._store:
                self._store.move_to_end(key)
            self._store[key] = data
            while len(self._store) > self.max_entries:
                self._store.popitem(last=False)

    def clear(self) -> None:
        with self._lock:
            self._store.clear()

    def remove_for_file(self, resolved_file_path: str) -> None:
        with self._lock:
            keys_to_remove = [
                k for k in self._store if k[0] == resolved_file_path
            ]
            for k in keys_to_remove:
                self._store.pop(k, None)

    def __len__(self) -> int:
        with self._lock:
            return len(self._store)


class AsyncTaskManager(QObject):
    """Coordinador de workers sobre QThreadPool global o dedicado."""

    def __init__(
        self, parent: QObject | None = None, max_threads: int = 4
    ) -> None:
        super().__init__(parent)
        self.pool = QThreadPool(self)
        self.pool.setMaxThreadCount(max_threads)
        self.thumbnail_cache = ThumbnailLRUCache()
        self._active_worker: PDFOperationWorker | None = None

    def start_operation(self, worker: PDFOperationWorker) -> None:
        """Inicia un worker de operación principal en segundo plano."""
        self._active_worker = worker
        self.pool.start(worker)

    def cancel_active_operation(self) -> bool:
        """Cancela la operación activa si existe."""
        if self._active_worker is not None:
            self._active_worker.cancel()
            return True
        return False

    def request_thumbnail(
        self,
        file_path: Path,
        page_index: int,
        dpi: int = DEFAULT_THUMBNAIL_DPI,
        password: str | None = None,
    ) -> ThumbnailRenderWorker:
        """Encola la generación asíncrona de una miniatura con caché LRU."""
        worker = ThumbnailRenderWorker(
            file_path=file_path,
            page_index=page_index,
            dpi=dpi,
            password=password,
            cache=self.thumbnail_cache,
        )
        self.pool.start(worker)
        return worker

