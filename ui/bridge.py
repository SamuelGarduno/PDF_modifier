"""Puente reactivo (QObject Bridge) entre el motor asíncrono Python y la interfaz QtQuick/QML."""

from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys
from typing import Any
from urllib.parse import quote

from PySide6.QtCore import (
    Property,
    QObject,
    QUrl,
    Signal,
    Slot,
)
from PySide6.QtGui import QDesktopServices

from core.exceptions import (
    InvalidPasswordError,
    PDFCorruptedError,
    PDFEncryptedError,
    PDFStudioError,
)
from core.history import OperationHistoryStore
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
from core.range_parser import validate_page_ranges_realtime
from core.workers import AsyncTaskManager, PDFOperationWorker
from ui.image_provider import PDFPageImageProvider

TOOLS_CATALOG: list[dict[str, str]] = [
    {
        "id": "merge",
        "title": "Unir PDF",
        "subtitle": "Combina varios pliegos en un cuaderno",
        "badge": "M",
        "workspaceMode": "dropzone",
    },
    {
        "id": "split",
        "title": "Dividir y Extraer",
        "subtitle": "Separa páginas por rangos exactos",
        "badge": "S",
        "workspaceMode": "dropzone",
    },
    {
        "id": "organize",
        "title": "Organizar Páginas",
        "subtitle": "Reordena, rota, duplica o descarta hojas",
        "badge": "O",
        "workspaceMode": "organizer",
    },
    {
        "id": "compress",
        "title": "Comprimir PDF",
        "subtitle": "Aligera el peso manteniendo nitidez",
        "badge": "C",
        "workspaceMode": "dropzone",
    },
    {
        "id": "protect",
        "title": "Proteger con Clave",
        "subtitle": "Sella tu documento con cifrado AES-256",
        "badge": "P",
        "workspaceMode": "dropzone",
    },
    {
        "id": "unlock",
        "title": "Desbloquear PDF",
        "subtitle": "Abre sellos y retira contraseñas",
        "badge": "U",
        "workspaceMode": "dropzone",
    },
    {
        "id": "pdf_to_images",
        "title": "PDF a Imágenes",
        "subtitle": "Revela cada página en láminas PNG o JPG",
        "badge": "I",
        "workspaceMode": "dropzone",
    },
    {
        "id": "images_to_pdf",
        "title": "Imágenes a PDF",
        "subtitle": "Encuaderna tus postales en un PDF",
        "badge": "A",
        "workspaceMode": "dropzone",
    },
    {
        "id": "watermark",
        "title": "Marca de Agua",
        "subtitle": "Estampa filigranas en cuadrícula 3x3",
        "badge": "W",
        "workspaceMode": "dropzone",
    },
    {
        "id": "sign",
        "title": "Visor y Firma",
        "subtitle": "Trazo libre, lacre 'Aprobado' o firma PNG",
        "badge": "F",
        "workspaceMode": "viewer",
    },
]


def _format_bytes(size_bytes: int) -> str:
    if size_bytes < 1024:
        return f"{size_bytes} B"
    kb = size_bytes / 1024.0
    if kb < 1024:
        if kb >= 100 or abs(kb - round(kb)) < 0.05:
            return f"{int(round(kb))} KB"
        return f"{kb:.1f}".replace(".", ",") + " KB"
    mb = kb / 1024.0
    return f"{mb:.1f}".replace(".", ",") + " MB"


class StudioBridge(QObject):
    """Controlador principal expuesto como 'studioBridge' al contexto QML."""

    activeToolChanged = Signal()
    searchQueryChanged = Signal()
    filesChanged = Signal()
    pagesChanged = Signal()
    configChanged = Signal()
    progressChanged = Signal()
    viewerChanged = Signal()
    historyChanged = Signal()

    passwordRequired = Signal(str, str)  # file_path, file_name
    operationCompleted = Signal(str, str, str)  # message, first_file_path, folder_path
    errorOccurred = Signal(str)

    def __init__(
        self,
        image_provider: PDFPageImageProvider | None = None,
        history_store: OperationHistoryStore | None = None,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self.task_manager = AsyncTaskManager(self)
        self.image_provider = (
            image_provider
            if image_provider is not None
            else PDFPageImageProvider(cache=self.task_manager.thumbnail_cache)
        )
        self.history_store = (
            history_store if history_store is not None else OperationHistoryStore()
        )

        self._active_tool: str = ToolType.MERGE.value
        self._search_query: str = ""
        self._queued_files: list[QueuedFile] = []
        self._passwords: dict[Path, str] = {}

        # Estado del Organizador de Páginas
        self._organizer_pages: list[dict[str, Any]] = []

        # Estado del Visor y Capa de Firma
        self._viewer_page_index: int = 0
        self._viewer_zoom: float = 1.0
        self._viewer_draw_mode: bool = True
        self._signature_stamp: str = "APROBADO"
        self._signature_image_path: str = ""
        self._freehand_strokes: list[list[tuple[float, float]]] = []

        # Estado de los Paneles de Configuración Inferior
        self._range_expr: str = "1-2"
        self._range_valid: bool = True
        self._range_feedback: str = "Ingresa un rango como '1-5, 8, 11-13'"
        self._split_separate: bool = False
        self._compression_level: str = CompressionLevel.RECOMMENDED.value
        self._password_input: str = ""
        self._image_format: str = ImageFormat.PNG.value
        self._watermark_text: str = "CONFIDENCIAL"
        self._watermark_opacity: float = 0.35
        self._watermark_angle: float = 45.0
        self._watermark_position: str = WatermarkPosition.CENTER.value
        self._output_directory: str = ""

        # Estado de Ejecución y Footer
        self._is_busy: bool = False
        self._progress_percent: int = 0
        self._status_message: str = "Listo para trabajar en tu escritorio de papelería."
        self._last_output_file: str = ""
        self._last_output_folder: str = ""

    # --- Propiedades de Navegación y Buscador (Ctrl + K) ---

    def _update_ready_status_message(self) -> None:
        """Actualiza el mensaje de estado del pie de página según los archivos en cola."""
        if self._is_busy:
            return
        if not self._queued_files:
            self._status_message = "Listo para trabajar en tu escritorio de papelería."
        else:
            total_files = len(self._queued_files)
            total_pages = sum(f.page_count for f in self._queued_files)
            pliegos_word = "pliego" if total_files == 1 else "pliegos"
            paginas_word = "página" if total_pages == 1 else "páginas"
            self._status_message = (
                f"Listo para encuadernar {total_files} {pliegos_word} ({total_pages} {paginas_word})."
            )
        self.progressChanged.emit()

    @Property(str, notify=activeToolChanged)
    def activeTool(self) -> str:
        return self._active_tool

    @Slot(str)
    def setActiveTool(self, tool_id: str) -> None:
        valid_ids = {item["id"] for item in TOOLS_CATALOG}
        if tool_id in valid_ids and tool_id != self._active_tool:
            self._active_tool = tool_id
            if not self._is_busy:
                self._progress_percent = 0
                self._last_output_file = ""
                self._last_output_folder = ""
                self._update_ready_status_message()
            self.activeToolChanged.emit()
            self._revalidate_range()
            if (
                tool_id in {ToolType.ORGANIZE.value, ToolType.SIGN.value}
                and self._queued_files
                and not self._organizer_pages
            ):
                self._rebuild_pages_from_primary_file()

    @Property(str, notify=activeToolChanged)
    def activeToolTitle(self) -> str:
        for item in TOOLS_CATALOG:
            if item["id"] == self._active_tool:
                return item["title"]
        return "Estudio PDF"

    @Property(str, notify=activeToolChanged)
    def activeToolSubtitle(self) -> str:
        for item in TOOLS_CATALOG:
            if item["id"] == self._active_tool:
                return item["subtitle"]
        return ""

    @Property(str, notify=activeToolChanged)
    def workspaceMode(self) -> str:
        for item in TOOLS_CATALOG:
            if item["id"] == self._active_tool:
                return item["workspaceMode"]
        return "dropzone"

    @Property(str, notify=searchQueryChanged)
    def searchQuery(self) -> str:
        return self._search_query

    @Slot(str)
    def setSearchQuery(self, query: str) -> None:
        if query != self._search_query:
            self._search_query = query
            self.searchQueryChanged.emit()

    @Property("QVariantList", notify=searchQueryChanged)
    def filteredTools(self) -> list[dict[str, str]]:
        q = self._search_query.strip().lower()
        if not q:
            return list(TOOLS_CATALOG)
        return [
            item
            for item in TOOLS_CATALOG
            if q in item["title"].lower()
            or q in item["subtitle"].lower()
            or q in item["id"].lower()
        ]

    # --- Propiedades y Slots de la Cola de Archivos (Dropzone) ---

    @Property("QVariantList", notify=filesChanged)
    def queuedFiles(self) -> list[dict[str, Any]]:
        result: list[dict[str, Any]] = []
        for idx, qf in enumerate(self._queued_files):
            result.append(
                {
                    "index": idx,
                    "name": qf.file_path.name,
                    "path": str(qf.file_path),
                    "sizeFormatted": _format_bytes(qf.original_size_bytes),
                    "sizeBytes": qf.original_size_bytes,
                    "pageCount": qf.page_count,
                    "isEncrypted": qf.is_encrypted,
                    "status": qf.status,
                }
            )
        return result

    @Property(int, notify=filesChanged)
    def fileCount(self) -> int:
        return len(self._queued_files)

    @Property(int, notify=filesChanged)
    def totalQueuedBytes(self) -> int:
        return sum(f.original_size_bytes for f in self._queued_files)

    @Property(int, notify=filesChanged)
    def totalQueuedPages(self) -> int:
        return sum(f.page_count for f in self._queued_files)

    @Slot("QVariantList")
    def addFileUrls(self, urls_or_paths: list[Any]) -> None:
        """Agrega archivos desde Drag & Drop o FileDialog (acepta QUrl o rutas str)."""
        added_any = False
        for raw in urls_or_paths:
            if isinstance(raw, QUrl):
                local_path = Path(raw.toLocalFile())
            else:
                text = str(raw)
                if text.startswith("file:///"):
                    local_path = Path(QUrl(text).toLocalFile())
                else:
                    local_path = Path(text)

            if not local_path.exists() or not local_path.is_file():
                self.errorOccurred.emit(f"El archivo no existe: {local_path.name}")
                continue

            ext = local_path.suffix.lower()
            if self._active_tool == ToolType.IMAGES_TO_PDF.value or ext in {
                ".png",
                ".jpg",
                ".jpeg",
            }:
                if ext in {".png", ".jpg", ".jpeg"}:
                    size_b = local_path.stat().st_size
                    if size_b == 0:
                        self.errorOccurred.emit(
                            f"La imagen '{local_path.name}' está vacía (0 bytes)."
                        )
                        continue
                    self._queued_files.append(
                        QueuedFile(
                            file_path=local_path,
                            original_size_bytes=size_b,
                            page_count=1,
                            is_encrypted=False,
                            status="Imagen lista",
                        )
                    )
                    added_any = True
                    continue

            try:
                saved_pwd = self._passwords.get(local_path.resolve())
                info = inspect_pdf_file(local_path, password=saved_pwd)
                self._queued_files.append(info)
                added_any = True

                if (
                    info.is_encrypted
                    and not saved_pwd
                    and self._active_tool != ToolType.UNLOCK.value
                ):
                    self.passwordRequired.emit(str(local_path), local_path.name)
            except (PDFCorruptedError, InvalidPasswordError) as exc:
                self.errorOccurred.emit(str(exc))

        if added_any:
            if not self._output_directory and self._queued_files:
                self._output_directory = str(self._queued_files[0].file_path.parent)
                self.configChanged.emit()
            self._rebuild_pages_from_primary_file()
            self._revalidate_range()
            self._update_ready_status_message()
            self.filesChanged.emit()

    @Slot(str)
    def addSingleFilePath(self, path_str: str) -> None:
        self.addFileUrls([path_str])

    @Slot(str, str)
    def supplyFilePassword(self, file_path_str: str, password: str) -> bool:
        """Desbloquea en memoria un PDF protegido cargado en la cola."""
        path = Path(file_path_str)
        try:
            info = inspect_pdf_file(path, password=password)
        except (InvalidPasswordError, PDFCorruptedError) as exc:
            self.errorOccurred.emit(str(exc))
            return False

        self._passwords[path.resolve()] = password
        self.image_provider.register_password(path, password)

        for idx, existing in enumerate(self._queued_files):
            if existing.file_path.resolve() == path.resolve():
                self._queued_files[idx] = info

        self._rebuild_pages_from_primary_file()
        self._revalidate_range()
        self._update_ready_status_message()
        self.filesChanged.emit()
        return True

    @Slot(int)
    def removeFileAt(self, index: int) -> None:
        if 0 <= index < len(self._queued_files):
            self._queued_files.pop(index)
            self._rebuild_pages_from_primary_file()
            self._revalidate_range()
            self._update_ready_status_message()
            self.filesChanged.emit()

    @Slot(int, int)
    def moveFile(self, from_index: int, to_index: int) -> None:
        if (
            0 <= from_index < len(self._queued_files)
            and 0 <= to_index < len(self._queued_files)
            and from_index != to_index
        ):
            item = self._queued_files.pop(from_index)
            self._queued_files.insert(to_index, item)
            if from_index == 0 or to_index == 0:
                self._rebuild_pages_from_primary_file()
            self._update_ready_status_message()
            self.filesChanged.emit()

    @Slot(int)
    def moveFileUp(self, index: int) -> None:
        if index > 0:
            self.moveFile(index, index - 1)

    @Slot(int)
    def moveFileDown(self, index: int) -> None:
        if 0 <= index < len(self._queued_files) - 1:
            self.moveFile(index, index + 1)

    @Slot()
    def clearFiles(self) -> None:
        self._queued_files.clear()
        self._organizer_pages.clear()
        self._freehand_strokes.clear()
        self._update_ready_status_message()
        self.filesChanged.emit()
        self.pagesChanged.emit()
        self.viewerChanged.emit()

    # --- Organizador de Páginas (Page Organizer) ---

    def _reindex_organizer_pages(self) -> None:
        """Actualiza displayPageNumber de forma correlativa (1..N) tras mover, duplicar o eliminar."""
        for idx, page_dict in enumerate(self._organizer_pages):
            page_dict["displayPageNumber"] = idx + 1

    def _rebuild_pages_from_primary_file(self) -> None:
        self._organizer_pages.clear()
        self._viewer_page_index = 0
        if not self._queued_files:
            self.pagesChanged.emit()
            self.viewerChanged.emit()
            return

        primary = self._queued_files[0]
        if primary.page_count < 1 or primary.file_path.suffix.lower() != ".pdf":
            self.pagesChanged.emit()
            self.viewerChanged.emit()
            return

        encoded_path = quote(str(primary.file_path.resolve()))
        for idx in range(primary.page_count):
            self._organizer_pages.append(
                {
                    "sourcePageIndex": idx,
                    "displayPageNumber": idx + 1,
                    "rotation": 0,
                    "selected": False,
                    "thumbnailUrl": f"image://pdfpage/{idx}?path={encoded_path}&dpi=96",
                }
            )
        self.pagesChanged.emit()
        self.viewerChanged.emit()

    @Property("QVariantList", notify=pagesChanged)
    def organizerPages(self) -> list[dict[str, Any]]:
        return list(self._organizer_pages)

    @Property(int, notify=pagesChanged)
    def organizerPageCount(self) -> int:
        return len(self._organizer_pages)

    @Slot(int)
    def rotatePageAt(self, item_index: int) -> None:
        """Rota 90 grados en sentido horario la tarjeta de página indicada."""
        if 0 <= item_index < len(self._organizer_pages):
            current = int(self._organizer_pages[item_index]["rotation"])
            self._organizer_pages[item_index]["rotation"] = (current + 90) % 360
            self.pagesChanged.emit()

    @Slot(int)
    def duplicatePageAt(self, item_index: int) -> None:
        """Duplica la tarjeta de página indicada inmediatamente después de la original y reindexa."""
        if 0 <= item_index < len(self._organizer_pages):
            copy_item = dict(self._organizer_pages[item_index])
            copy_item["selected"] = False
            self._organizer_pages.insert(item_index + 1, copy_item)
            self._reindex_organizer_pages()
            self.pagesChanged.emit()

    @Slot(int)
    def deletePageAt(self, item_index: int) -> None:
        """Elimina una página del organizador siempre que quede al menos 1 página y reindexa."""
        if len(self._organizer_pages) <= 1:
            self.errorOccurred.emit(
                "El documento debe conservar al menos una página."
            )
            return
        if 0 <= item_index < len(self._organizer_pages):
            self._organizer_pages.pop(item_index)
            self._reindex_organizer_pages()
            self.pagesChanged.emit()

    @Slot(int, int)
    def moveOrganizerPage(self, from_index: int, to_index: int) -> None:
        """Reordena páginas mediante Drag & Drop en el Page Organizer y reindexa."""
        if (
            0 <= from_index < len(self._organizer_pages)
            and 0 <= to_index < len(self._organizer_pages)
            and from_index != to_index
        ):
            page_item = self._organizer_pages.pop(from_index)
            self._organizer_pages.insert(to_index, page_item)
            self._reindex_organizer_pages()
            self.pagesChanged.emit()

    @Slot(int, int)
    def move_page(self, from_index: int, to_index: int) -> None:
        """Alias snake_case para reordenar páginas desde Drag & Drop."""
        self.moveOrganizerPage(from_index, to_index)

    @Slot(int, bool, bool)
    def selectOrganizerPage(
        self, item_index: int, ctrl_pressed: bool, shift_pressed: bool
    ) -> None:
        """Gestiona selección simple o múltiple con Ctrl/Shift + clic."""
        if not (0 <= item_index < len(self._organizer_pages)):
            return

        if shift_pressed:
            selected_indices = [
                i for i, p in enumerate(self._organizer_pages) if p["selected"]
            ]
            anchor = selected_indices[0] if selected_indices else 0
            low, high = min(anchor, item_index), max(anchor, item_index)
            for idx in range(low, high + 1):
                self._organizer_pages[idx]["selected"] = True
        elif ctrl_pressed:
            self._organizer_pages[item_index]["selected"] = not bool(
                self._organizer_pages[item_index]["selected"]
            )
        else:
            for idx, page in enumerate(self._organizer_pages):
                page["selected"] = idx == item_index

        self.pagesChanged.emit()

    @Slot()
    def rotateSelectedPages(self) -> None:
        changed = False
        for page in self._organizer_pages:
            if page["selected"]:
                page["rotation"] = (int(page["rotation"]) + 90) % 360
                changed = True
        if changed:
            self.pagesChanged.emit()

    @Slot()
    def deleteSelectedPages(self) -> None:
        remaining = [p for p in self._organizer_pages if not p["selected"]]
        if not remaining:
            self.errorOccurred.emit(
                "No puedes eliminar todas las páginas del documento."
            )
            return
        if len(remaining) != len(self._organizer_pages):
            self._organizer_pages = remaining
            self._reindex_organizer_pages()
            self.pagesChanged.emit()

    # --- Visor PDF y Capa de Firma/Sellos ---

    @Property(bool, notify=viewerChanged)
    def viewerDrawMode(self) -> bool:
        return self._viewer_draw_mode

    @Slot(bool)
    def setViewerDrawMode(self, enabled: bool) -> None:
        if enabled != self._viewer_draw_mode:
            self._viewer_draw_mode = enabled
            self.viewerChanged.emit()

    @Property(int, notify=viewerChanged)
    def viewerPageIndex(self) -> int:
        return self._viewer_page_index

    @Slot(int)
    def setViewerPageIndex(self, index: int) -> None:
        max_p = self.primaryDocumentPageCount
        if 0 <= index < max(1, max_p) and index != self._viewer_page_index:
            self._viewer_page_index = index
            self.viewerChanged.emit()

    @Property(int, notify=filesChanged)
    def primaryDocumentPageCount(self) -> int:
        if not self._queued_files:
            return 0
        return self._queued_files[0].page_count

    @Property(float, notify=viewerChanged)
    def viewerZoom(self) -> float:
        return self._viewer_zoom

    @Slot(float)
    def setViewerZoom(self, zoom: float) -> None:
        clamped = round(max(0.5, min(3.0, zoom)), 2)
        if clamped != self._viewer_zoom:
            self._viewer_zoom = clamped
            self.viewerChanged.emit()

    @Property(str, notify=viewerChanged)
    def currentViewerPageUrl(self) -> str:
        if not self._queued_files:
            return ""
        primary = self._queued_files[0]
        if primary.file_path.suffix.lower() != ".pdf" or primary.page_count < 1:
            return ""
        encoded = quote(str(primary.file_path.resolve()))
        return f"image://pdfpage/{self._viewer_page_index}?path={encoded}&dpi=150"

    @Property(str, notify=viewerChanged)
    def signatureStamp(self) -> str:
        return self._signature_stamp

    @Slot(str)
    def setSignatureStamp(self, label: str) -> None:
        cleaned = "" if label.strip().upper() in {"", "SIN SELLO", "NINGUNO"} else label.strip()
        if cleaned != self._signature_stamp:
            self._signature_stamp = cleaned
            self.viewerChanged.emit()

    @Slot()
    def clearSignatureStamp(self) -> None:
        """Desactiva y oculta cualquier sello predefinido dejando solo la firma."""
        self.setSignatureStamp("")

    @Property(str, notify=viewerChanged)
    def signatureImagePath(self) -> str:
        return self._signature_image_path

    @Slot(str)
    def setSignatureImagePath(self, path_or_url: str) -> None:
        if path_or_url.startswith("file:///"):
            clean = QUrl(path_or_url).toLocalFile()
        else:
            clean = path_or_url
        if clean != self._signature_image_path:
            self._signature_image_path = clean
            self.viewerChanged.emit()

    @Slot("QVariantList")
    def addFreehandStroke(self, normalized_points: list[Any]) -> None:
        """Registra un trazo libre de firma (lista de puntos {x, y} normalizados 0..1)."""
        stroke: list[tuple[float, float]] = []
        for pt in normalized_points:
            if isinstance(pt, dict) and "x" in pt and "y" in pt:
                stroke.append((float(pt["x"]), float(pt["y"])))
            elif isinstance(pt, (list, tuple)) and len(pt) >= 2:
                stroke.append((float(pt[0]), float(pt[1])))
        if len(stroke) >= 2:
            self._freehand_strokes.append(stroke)
            self.viewerChanged.emit()

    @Slot()
    def clearFreehandStrokes(self) -> None:
        self._freehand_strokes.clear()
        self.viewerChanged.emit()

    @Property(int, notify=viewerChanged)
    def freehandStrokeCount(self) -> int:
        return len(self._freehand_strokes)

    # --- Propiedades de Paneles de Configuración Inferior ---

    @Property(str, notify=configChanged)
    def rangeExpr(self) -> str:
        return self._range_expr

    @Slot(str)
    def setRangeExpr(self, expr: str) -> None:
        if expr != self._range_expr:
            self._range_expr = expr
            self._revalidate_range()
            self.configChanged.emit()

    @Property(bool, notify=configChanged)
    def isRangeValid(self) -> bool:
        return self._range_valid

    @Property(str, notify=configChanged)
    def rangeFeedback(self) -> str:
        return self._range_feedback

    def _revalidate_range(self) -> None:
        max_pages = self.primaryDocumentPageCount or 20
        ok, msg, _ = validate_page_ranges_realtime(self._range_expr, max_pages)
        self._range_valid = ok
        self._range_feedback = msg

    @Property(bool, notify=configChanged)
    def splitSeparateFiles(self) -> bool:
        return self._split_separate

    @Slot(bool)
    def setSplitSeparateFiles(self, value: bool) -> None:
        if value != self._split_separate:
            self._split_separate = value
            self.configChanged.emit()

    @Property(str, notify=configChanged)
    def compressionLevel(self) -> str:
        return self._compression_level

    @Slot(str)
    def setCompressionLevel(self, level: str) -> None:
        if level in {
            CompressionLevel.EXTREME.value,
            CompressionLevel.RECOMMENDED.value,
            CompressionLevel.LOW_LOSS.value,
        } and level != self._compression_level:
            self._compression_level = level
            self.configChanged.emit()

    @Property(str, notify=configChanged)
    def estimatedCompressionSummary(self) -> str:
        base_bytes = self.totalQueuedBytes or (1024 * 1024)
        lvl = CompressionLevel(self._compression_level)
        est_final, pct = PDFEngine.estimate_compression_savings(base_bytes, lvl)
        return f"Reducción estimada ~{pct:.0f}% (de {_format_bytes(base_bytes)} a ~{_format_bytes(est_final)})"

    @Property(str, notify=configChanged)
    def passwordInput(self) -> str:
        return self._password_input

    @Slot(str)
    def setPasswordInput(self, pwd: str) -> None:
        if pwd != self._password_input:
            self._password_input = pwd
            self.configChanged.emit()

    @Property(str, notify=configChanged)
    def imageFormat(self) -> str:
        return self._image_format

    @Slot(str)
    def setImageFormat(self, fmt: str) -> None:
        fmt_clean = fmt.lower()
        if fmt_clean in {"png", "jpg"} and fmt_clean != self._image_format:
            self._image_format = fmt_clean
            self.configChanged.emit()

    @Property(str, notify=configChanged)
    def watermarkText(self) -> str:
        return self._watermark_text

    @Slot(str)
    def setWatermarkText(self, text: str) -> None:
        if text != self._watermark_text:
            self._watermark_text = text
            self.configChanged.emit()

    @Property(float, notify=configChanged)
    def watermarkOpacity(self) -> float:
        return self._watermark_opacity

    @Slot(float)
    def setWatermarkOpacity(self, opacity: float) -> None:
        clamped = round(max(0.05, min(1.0, opacity)), 2)
        if clamped != self._watermark_opacity:
            self._watermark_opacity = clamped
            self.configChanged.emit()

    @Property(float, notify=configChanged)
    def watermarkAngle(self) -> float:
        return self._watermark_angle

    @Slot(float)
    def setWatermarkAngle(self, angle: float) -> None:
        if angle != self._watermark_angle:
            self._watermark_angle = angle
            self.configChanged.emit()

    @Property(str, notify=configChanged)
    def watermarkPosition(self) -> str:
        return self._watermark_position

    @Slot(str)
    def setWatermarkPosition(self, pos: str) -> None:
        valid_positions = {p.value for p in WatermarkPosition}
        if pos in valid_positions and pos != self._watermark_position:
            self._watermark_position = pos
            self.configChanged.emit()

    @Property(str, notify=configChanged)
    def outputDirectory(self) -> str:
        return self._output_directory

    @Slot(str)
    def setOutputDirectory(self, path_or_url: str) -> None:
        if path_or_url.startswith("file:///"):
            clean = QUrl(path_or_url).toLocalFile()
        else:
            clean = path_or_url
        if clean != self._output_directory:
            self._output_directory = clean
            self.configChanged.emit()

    # --- Historial Persistente (JSON) ---

    @Property("QVariantList", notify=historyChanged)
    def recentHistory(self) -> list[dict[str, Any]]:
        entries = self.history_store.load_entries()
        return [
            {
                "timestamp": e.timestamp_iso,
                "tool": e.tool,
                "message": e.message,
                "savedPercentage": e.saved_percentage,
                "firstFile": e.output_files[0] if e.output_files else "",
            }
            for e in entries
        ]

    # --- Progreso, Ejecución Asíncrona y Acciones de Resultado ---

    @Property(bool, notify=progressChanged)
    def isBusy(self) -> bool:
        return self._is_busy

    @Property(int, notify=progressChanged)
    def progressPercent(self) -> int:
        return self._progress_percent

    @Property(str, notify=progressChanged)
    def statusMessage(self) -> str:
        return self._status_message

    @Property(str, notify=progressChanged)
    def lastOutputFile(self) -> str:
        return self._last_output_file

    @Property(str, notify=progressChanged)
    def lastOutputFolder(self) -> str:
        return self._last_output_folder

    @Slot()
    def executeActiveOperation(self) -> None:
        """Construye y lanza el PDFOperationWorker correspondiente a la herramienta activa."""
        if self._is_busy:
            return
        if not self._queued_files:
            self.errorOccurred.emit(
                "Agrega al menos un archivo en la mesa de trabajo antes de procesar."
            )
            return

        primary_file = self._queued_files[0].file_path
        primary_pwd = self._passwords.get(primary_file.resolve()) or self._password_input or None
        out_dir = (
            Path(self._output_directory)
            if self._output_directory
            else primary_file.parent
        )
        out_dir.mkdir(parents=True, exist_ok=True)

        tool = ToolType(self._active_tool)
        try:
            worker = self._build_worker_for_tool(
                tool, primary_file, primary_pwd, out_dir
            )
        except PDFStudioError as exc:
            self.errorOccurred.emit(str(exc))
            return

        self._is_busy = True
        self._progress_percent = 5
        self._status_message = "Iniciando tarea en segundo plano..."
        self.progressChanged.emit()

        worker.signals.progress.connect(self._on_worker_progress)
        worker.signals.finished.connect(self._on_worker_finished)
        worker.signals.cancelled.connect(self._on_worker_cancelled)
        worker.signals.error.connect(self._on_worker_error)
        self.task_manager.start_operation(worker)

    def _build_worker_for_tool(
        self,
        tool: ToolType,
        primary_file: Path,
        primary_pwd: str | None,
        out_dir: Path,
    ) -> PDFOperationWorker:
        if tool == ToolType.MERGE:
            paths = [qf.file_path for qf in self._queued_files]
            dest = ensure_safe_output_path(
                primary_file, out_dir / f"{primary_file.stem}_unido.pdf", "_unido"
            )
            return PDFOperationWorker(
                PDFEngine.merge_pdfs, paths, dest, passwords=dict(self._passwords)
            )

        if tool == ToolType.SPLIT:
            dest = ensure_safe_output_path(
                primary_file,
                out_dir / f"{primary_file.stem}_extraido.pdf",
                "_extraido",
            )
            return PDFOperationWorker(
                PDFEngine.split_pdf_by_range,
                primary_file,
                dest,
                self._range_expr,
                password=primary_pwd,
                split_into_separate_files=self._split_separate,
            )

        if tool == ToolType.ORGANIZE:
            instructions = [
                PageItemInstruction(
                    source_page_index=int(p["sourcePageIndex"]),
                    rotation_degrees=int(p["rotation"]),
                )
                for p in self._organizer_pages
            ]
            dest = ensure_safe_output_path(
                primary_file,
                out_dir / f"{primary_file.stem}_organizado.pdf",
                "_organizado",
            )
            return PDFOperationWorker(
                PDFEngine.organize_pdf,
                primary_file,
                dest,
                instructions,
                password=primary_pwd,
            )

        if tool == ToolType.COMPRESS:
            dest = ensure_safe_output_path(
                primary_file,
                out_dir / f"{primary_file.stem}_comprimido.pdf",
                "_comprimido",
            )
            return PDFOperationWorker(
                PDFEngine.compress_pdf,
                primary_file,
                dest,
                level=CompressionLevel(self._compression_level),
                password=primary_pwd,
            )

        if tool == ToolType.PROTECT:
            dest = ensure_safe_output_path(
                primary_file,
                out_dir / f"{primary_file.stem}_protegido.pdf",
                "_protegido",
            )
            return PDFOperationWorker(
                PDFEngine.protect_pdf,
                primary_file,
                dest,
                new_password=self._password_input,
                current_password=self._passwords.get(primary_file.resolve()),
            )

        if tool == ToolType.UNLOCK:
            dest = ensure_safe_output_path(
                primary_file,
                out_dir / f"{primary_file.stem}_desbloqueado.pdf",
                "_desbloqueado",
            )
            unlock_pwd = self._password_input or primary_pwd or ""
            return PDFOperationWorker(
                PDFEngine.unlock_pdf,
                primary_file,
                dest,
                password=unlock_pwd,
            )

        if tool == ToolType.PDF_TO_IMAGES:
            export_subdir = out_dir / f"{primary_file.stem}_imagenes"
            return PDFOperationWorker(
                PDFEngine.pdf_to_images,
                primary_file,
                export_subdir,
                image_format=ImageFormat(self._image_format),
                password=primary_pwd,
            )

        if tool == ToolType.IMAGES_TO_PDF:
            img_paths = [qf.file_path for qf in self._queued_files]
            dest = ensure_safe_output_path(
                primary_file,
                out_dir / f"{primary_file.stem}_album.pdf",
                "_album",
            )
            return PDFOperationWorker(
                PDFEngine.images_to_pdf,
                img_paths,
                dest,
            )

        if tool == ToolType.WATERMARK:
            dest = ensure_safe_output_path(
                primary_file,
                out_dir / f"{primary_file.stem}_marca_agua.pdf",
                "_marca_agua",
            )
            wm_cfg = WatermarkConfig(
                text=self._watermark_text,
                opacity=self._watermark_opacity,
                angle=self._watermark_angle,
                position=WatermarkPosition(self._watermark_position),
            )
            return PDFOperationWorker(
                PDFEngine.apply_watermark,
                primary_file,
                dest,
                wm_cfg,
                password=primary_pwd,
            )

        # ToolType.SIGN
        dest = ensure_safe_output_path(
            primary_file,
            out_dir / f"{primary_file.stem}_firmado.pdf",
            "_firmado",
        )
        img_p = Path(self._signature_image_path) if self._signature_image_path else None
        overlay = SignatureOverlay(
            page_index=self._viewer_page_index,
            stamp_label=self._signature_stamp if self._signature_stamp else None,
            image_path=img_p,
            freehand_strokes=list(self._freehand_strokes),
        )
        return PDFOperationWorker(
            PDFEngine.apply_signature_or_stamp,
            primary_file,
            dest,
            overlay,
            password=primary_pwd,
        )

    @Slot()
    def cancelActiveOperation(self) -> None:
        self.task_manager.cancel_active_operation()

    def _on_worker_progress(self, percent: int, message: str) -> None:
        self._progress_percent = percent
        self._status_message = message
        self.progressChanged.emit()

    def _on_worker_finished(self, result: OperationResult) -> None:
        self._is_busy = False
        self._progress_percent = 100
        self._status_message = result.message

        first_out = str(result.output_files[0]) if result.output_files else ""
        folder_out = (
            str(result.output_files[0].parent) if result.output_files else ""
        )
        self._last_output_file = first_out
        self._last_output_folder = folder_out

        self.history_store.record_operation(result)
        self.progressChanged.emit()
        self.historyChanged.emit()
        self.operationCompleted.emit(result.message, first_out, folder_out)

    def _on_worker_cancelled(self, message: str) -> None:
        self._is_busy = False
        self._progress_percent = 0
        self._status_message = message
        self.progressChanged.emit()

    def _on_worker_error(self, error_msg: str) -> None:
        self._is_busy = False
        self._progress_percent = 0
        self._status_message = f"Error: {error_msg}"
        self.progressChanged.emit()
        self.errorOccurred.emit(error_msg)

    @Slot(str)
    def openFileInSystem(self, file_path_str: str) -> None:
        target = file_path_str or self._last_output_file
        if target and Path(target).exists():
            QDesktopServices.openUrl(QUrl.fromLocalFile(target))

    @Slot(str)
    def showFileInFolder(self, file_or_folder_str: str) -> None:
        target = Path(file_or_folder_str or self._last_output_file or self._last_output_folder)
        if not target.exists():
            return
        if sys.platform.startswith("win") and target.is_file():
            subprocess.Popen(["explorer", "/select,", str(target.resolve())])
        else:
            folder = target if target.is_dir() else target.parent
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(folder.resolve())))

