"""Puente reactivo (QObject Bridge) entre el motor asíncrono Python y la interfaz QtQuick/QML."""

from __future__ import annotations

import os
from pathlib import Path
import shutil
import subprocess
import sys
from typing import Any
from urllib.parse import quote

from PySide6.QtCore import (
    Property,
    QObject,
    QSettings,
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
    TaskCancelledError,
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

SUPPORTED_PDF_EXTENSIONS: frozenset[str] = frozenset({".pdf"})
SUPPORTED_IMAGE_EXTENSIONS: frozenset[str] = frozenset(
    {".png", ".jpg", ".jpeg", ".webp"}
)
SUPPORTED_EXTENSIONS: frozenset[str] = (
    SUPPORTED_PDF_EXTENSIONS | SUPPORTED_IMAGE_EXTENSIONS
)

TOOLS_WITH_OPTIONS: frozenset[str] = frozenset(
    {"organize", "split", "compress", "pdf_to_images", "watermark", "sign"}
)

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
        "id": "pdf_to_images",
        "title": "PDF a Imágenes",
        "subtitle": "Revela cada página en láminas PNG o JPG",
        "badge": "I",
        "workspaceMode": "dropzone",
    },
    {
        "id": "images_to_pdf",
        "title": "Imágenes a PDF",
        "subtitle": "Encuadernar postales en un PDF",
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

TOOLS_BY_ID: dict[str, dict[str, str]] = {item["id"]: item for item in TOOLS_CATALOG}



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

        self._active_tool: str = ToolType.ORGANIZE.value
        self._is_tool_selected: bool = False
        self._search_query: str = ""
        self._queued_files: list[QueuedFile] = []
        self._passwords: dict[Path, str] = {}
        self._last_notice_message: str = ""
        self._last_notice_is_error: bool = False
        self._has_processing_error: bool = False

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
        self._settings = QSettings("AtelierCoquette", "CoquettePDFStudio")
        self._output_directory: str = ""
        self._output_directory_valid: bool = True
        self._output_directory_error: str = ""

        # Estado de Ejecución y Footer
        self._is_busy: bool = False
        self._progress_percent: int = 0
        self._status_message: str = "Listo para trabajar en tu escritorio de papelería."
        self._last_output_file: str = ""
        self._last_output_folder: str = ""

    # --- Propiedades de Navegación Contextual ("Suelta primero, elige después") ---

    def _emit_error(self, message: str) -> None:
        """Registra y emite un mensaje de error o advertencia amigable hacia la UI."""
        self._last_notice_message = message
        self._last_notice_is_error = True
        self.progressChanged.emit()
        self.errorOccurred.emit(message)

    def _emit_notice(self, message: str, is_error: bool = False) -> None:
        """Emite un aviso breve o error amigable hacia el banner flotante."""
        self._last_notice_message = message
        self._last_notice_is_error = is_error
        self.progressChanged.emit()
        self.errorOccurred.emit(message)

    @Property(str, notify=progressChanged)
    def lastNoticeMessage(self) -> str:
        return self._last_notice_message

    @Property(bool, notify=progressChanged)
    def lastNoticeIsError(self) -> bool:
        return self._last_notice_is_error

    @Property(bool, notify=progressChanged)
    def hasProcessingError(self) -> bool:
        return self._has_processing_error

    @Slot()
    def clearNoticeMessage(self) -> None:
        if self._last_notice_message:
            self._last_notice_message = ""
            self._last_notice_is_error = False
            self.progressChanged.emit()

    def _valid_queued_files(self) -> list[QueuedFile]:
        """Devuelve los archivos en cola excluyendo los marcados como ilegibles/dañados."""
        return [qf for qf in self._queued_files if qf.status != "No se pudo leer"]

    def _update_ready_status_message(self) -> None:
        """Actualiza el mensaje de estado del pie de página según los archivos en cola."""
        if self._is_busy:
            return
        self._has_processing_error = False
        valid_files = self._valid_queued_files()
        if not self._queued_files:
            self._status_message = "Listo para trabajar en tu escritorio de papelería."
        elif not valid_files:
            self._status_message = "Los archivos en cola no se pudieron leer."
        else:
            total_files = len(valid_files)
            total_pages = sum(f.page_count for f in valid_files)
            pliegos_word = "pliego" if total_files == 1 else "pliegos"
            paginas_word = "página" if total_pages == 1 else "páginas"
            self._status_message = (
                f"Listo para encuadernar {total_files} {pliegos_word} ({total_pages} {paginas_word})."
            )
        self.progressChanged.emit()

    def _compute_input_context_state(self) -> str:
        """Evalúa instantáneamente en O(N) la cantidad y extensión de los archivos válidos en cola."""
        valid_files = self._valid_queued_files()
        if not valid_files:
            return "empty" if not self._queued_files else "single_pdf"
        pdf_count = 0
        img_count = 0
        for qf in valid_files:
            ext = qf.file_path.suffix.lower()
            if ext in SUPPORTED_PDF_EXTENSIONS:
                pdf_count += 1
            elif ext in SUPPORTED_IMAGE_EXTENSIONS:
                img_count += 1
        if pdf_count == 1 and img_count == 0:
            return "single_pdf"
        if pdf_count >= 2 and img_count == 0:
            return "multi_pdf"
        if img_count >= 1 and pdf_count == 0:
            return "images_only"
        if pdf_count >= 1 and img_count >= 1:
            return "mixed"
        return "empty"

    @Property(str, notify=filesChanged)
    def inputContextState(self) -> str:
        """Estado contextual actual: 'empty', 'single_pdf', 'multi_pdf', 'images_only' o 'mixed'."""
        return self._compute_input_context_state()

    @Property(int, notify=filesChanged)
    def pdfCount(self) -> int:
        return sum(
            1
            for qf in self._valid_queued_files()
            if qf.file_path.suffix.lower() in SUPPORTED_PDF_EXTENSIONS
        )

    @Property(int, notify=filesChanged)
    def imageCount(self) -> int:
        return sum(
            1
            for qf in self._valid_queued_files()
            if qf.file_path.suffix.lower() in SUPPORTED_IMAGE_EXTENSIONS
        )

    @Property(bool, notify=filesChanged)
    def hasLockedFiles(self) -> bool:
        return any(
            qf.is_encrypted and qf.file_path.resolve() not in self._passwords
            for qf in self._valid_queued_files()
        )

    @Property(bool, notify=filesChanged)
    def hasCorruptedFiles(self) -> bool:
        return any(qf.status == "No se pudo leer" for qf in self._queued_files)

    @Property(str, notify=filesChanged)
    def workbenchSubtitle(self) -> str:
        """Subtítulo corto y directo para la barra de título en la Mesa de Trabajo."""
        if not self._queued_files:
            return "Suelta primero tus archivos, elige después tu herramienta"
        state = self._compute_input_context_state()
        if state == "single_pdf":
            if self.hasLockedFiles:
                return "1 pliego sellado en la mesa"
            return "1 pliego en la mesa"
        if state == "multi_pdf":
            return f"{self.pdfCount} pliegos listos"
        if state == "images_only":
            n = self.imageCount
            return f"{n} {'postal lista' if n == 1 else 'postales listas'}"
        if state == "mixed":
            p_word = "pliego" if self.pdfCount == 1 else "pliegos"
            i_word = "postal" if self.imageCount == 1 else "postales"
            return f"{self.pdfCount} {p_word} · {self.imageCount} {i_word}"
        return "Mesa de Trabajo Floral"

    @Property(str, notify=filesChanged)
    def queueSummaryRightText(self) -> str:
        """Resumen compacto a la derecha de 'Tus pliegos' ('2 pliegos · 10 páginas · 8,3 MB')."""
        if not self._queued_files:
            return ""
        state = self._compute_input_context_state()
        size_str = _format_bytes(self.totalQueuedBytes)
        if state == "images_only":
            n = self.imageCount
            word = "postal" if n == 1 else "postales"
            return f"{n} {word} · {size_str}"
        n = len(self._queued_files)
        p = self.totalQueuedPages
        f_word = "pliego" if n == 1 else "pliegos"
        p_word = "página" if p == 1 else "páginas"
        return f"{n} {f_word} · {p} {p_word} · {size_str}"

    @Property(str, notify=filesChanged)
    def contextSummaryTitle(self) -> str:
        return self.workbenchSubtitle

    @Property("QVariantList", notify=filesChanged)
    def suggestedTools(self) -> list[dict[str, Any]]:
        """Devuelve dinámicamente las tarjetas de herramientas compatibles con la entrada actual."""
        state = self._compute_input_context_state()
        if state == "empty" and not self._queued_files:
            return []

        def _make_card(
            tool_id: str,
            is_primary: bool = False,
            override_title: str | None = None,
            override_subtitle: str | None = None,
        ) -> dict[str, Any]:
            base = dict(TOOLS_BY_ID[tool_id])
            if override_title:
                base["title"] = override_title
            if override_subtitle:
                base["subtitle"] = override_subtitle
            base["isPrimary"] = is_primary
            base["opensScreen"] = tool_id in {"organize", "split", "sign"}
            base["hasOptions"] = tool_id in TOOLS_WITH_OPTIONS
            return base

        if state == "single_pdf":
            # Caso 1: Un (1) archivo PDF
            return [
                _make_card("organize", is_primary=True),
                _make_card("split", is_primary=False),
                _make_card("compress", is_primary=False),
                _make_card("pdf_to_images", is_primary=False),
                _make_card("watermark", is_primary=False),
                _make_card("sign", is_primary=False),
            ]

        if state == "multi_pdf":
            # Caso 2: Múltiples (2 o más) archivos PDF
            return [
                _make_card("merge", is_primary=True),
                _make_card(
                    "compress",
                    is_primary=False,
                    override_subtitle="Aligera el peso de los PDFs en lote",
                ),
                _make_card(
                    "pdf_to_images",
                    is_primary=False,
                    override_subtitle="Exporta las páginas a láminas PNG o JPG",
                ),
                _make_card(
                    "watermark",
                    is_primary=False,
                    override_subtitle="Estampa filigrana en todos los pliegos",
                ),
            ]

        if state == "images_only":
            # Caso 3: Una o más imágenes (.png, .jpg, .jpeg, .webp)
            return [
                _make_card(
                    "images_to_pdf",
                    is_primary=True,
                    override_subtitle="Encuadernar postales en un PDF",
                ),
            ]

        # Caso 4: Mezcla de PDFs e imágenes
        return [
            _make_card(
                "merge",
                is_primary=True,
                override_title="Unir Todo en un PDF",
                override_subtitle="Convierte e integra PDFs y postales en un solo cuaderno",
            ),
        ]

    @Property("QVariantMap", notify=activeToolChanged)
    def primarySuggestedTool(self) -> dict[str, Any]:
        """Devuelve la herramienta actualmente destacada en la tarjeta grande de Zona 2."""
        suggestions = self.suggestedTools
        if not suggestions:
            return {
                "id": "organize",
                "title": "Organizar Páginas",
                "subtitle": "Reordena, rota, duplica o descarta hojas",
                "isPrimary": True,
                "opensScreen": True,
                "hasOptions": True,
            }
        for item in suggestions:
            if item["id"] == self._active_tool:
                selected_copy = dict(item)
                selected_copy["isPrimary"] = True
                return selected_copy
        first_copy = dict(suggestions[0])
        first_copy["isPrimary"] = True
        return first_copy

    @Property("QVariantList", notify=activeToolChanged)
    def secondarySuggestedTools(self) -> list[dict[str, Any]]:
        """Devuelve los chips secundarios ('También puedes:') excluyendo la herramienta destacada actual."""
        suggestions = self.suggestedTools
        if len(suggestions) <= 1:
            return []
        primary_id = self.primarySuggestedTool.get("id", suggestions[0]["id"])
        return [dict(item, isPrimary=False) for item in suggestions if item["id"] != primary_id]

    @Slot(str)
    def chooseWorkbenchTool(self, tool_id: str) -> None:
        """Elige una herramienta dentro de la Mesa de Trabajo sin abandonar la vista principal."""
        valid_ids = {item["id"] for item in TOOLS_CATALOG}
        if tool_id not in valid_ids:
            return
        if self._active_tool != tool_id or self._is_tool_selected:
            self._active_tool = tool_id
            self._is_tool_selected = False
            self._has_processing_error = False
            self.activeToolChanged.emit()
            self.filesChanged.emit()
            self.progressChanged.emit()

    def _sync_contextual_tool_after_queue_change(self) -> None:
        """Sincroniza la herramienta activa y el modo de vista tras cambios en la cola de archivos."""
        if not self._queued_files:
            # Si se eliminan todos los archivos, regresa automáticamente a Mesa de Trabajo Vacía
            if self._is_tool_selected:
                self._is_tool_selected = False
            self.activeToolChanged.emit()
            return

        suggestions = self.suggestedTools
        valid_suggested_ids = [item["id"] for item in suggestions]
        primary_id = suggestions[0]["id"] if suggestions else ToolType.ORGANIZE.value

        if not self._is_tool_selected:
            # Mientras está en la mesa de trabajo eligiendo herramienta, preseleccionar la principal sugerida
            if self._active_tool != primary_id:
                self._active_tool = primary_id
            self.activeToolChanged.emit()
        else:
            # Si ya había entrado a una herramienta pero la cola cambió a un estado incompatible, ajustar
            if valid_suggested_ids and self._active_tool not in valid_suggested_ids:
                self._active_tool = primary_id
            self.activeToolChanged.emit()

    @Property(bool, notify=activeToolChanged)
    def isToolSelected(self) -> bool:
        return self._is_tool_selected

    @Property(str, notify=activeToolChanged)
    def activeTool(self) -> str:
        return self._active_tool

    @Slot(str)
    def selectTool(self, tool_id: str) -> None:
        """Selecciona una herramienta sugerida y transiciona a su vista de configuración."""
        valid_ids = {item["id"] for item in TOOLS_CATALOG}
        if tool_id not in valid_ids:
            return
        changed = (tool_id != self._active_tool) or (not self._is_tool_selected)
        self._active_tool = tool_id
        self._is_tool_selected = True
        self._has_processing_error = False
        if not self._is_busy:
            self._progress_percent = 0
            self._last_output_file = ""
            self._last_output_folder = ""
            self._update_ready_status_message()
        if changed:
            self.activeToolChanged.emit()
        self._revalidate_range()
        if (
            tool_id in {ToolType.ORGANIZE.value, ToolType.SIGN.value}
            and self._queued_files
            and not self._organizer_pages
        ):
            self._rebuild_pages_from_primary_file()

    @Slot()
    def returnToWorkbench(self) -> None:
        """Vuelve a la mesa de trabajo contextual ('Cambiar archivos / Elegir otra herramienta')."""
        if self._is_tool_selected:
            self._is_tool_selected = False
            self._has_processing_error = False
            suggestions = self.suggestedTools
            if suggestions:
                self._active_tool = suggestions[0]["id"]
            if not self._is_busy:
                self._progress_percent = 0
                self._update_ready_status_message()
            self.activeToolChanged.emit()

    @Slot(str)
    def setActiveTool(self, tool_id: str) -> None:
        """Establece y activa la herramienta indicada (compatible con llamadas directas)."""
        self.selectTool(tool_id)

    @Property(str, notify=activeToolChanged)
    def primaryCtaText(self) -> str:
        """Texto dinámico y específico para el botón principal de la Barra de Acción."""
        if self._is_busy:
            return "Cancelar"
        valid_files = self._valid_queued_files()
        if not valid_files:
            return "Selecciona archivos"
        if self.hasLockedFiles:
            return "Abrir sello"

        tool = self._active_tool
        n_valid = len(valid_files)
        n_pdfs = max(1, self.pdfCount)
        n_imgs = max(1, self.imageCount)

        if not self._is_tool_selected:
            if tool == "organize":
                return "Abrir organizador →"
            if tool == "split":
                return "Elegir páginas →"
            if tool == "sign":
                return "Abrir visor →"
            if tool == "watermark":
                return "Configurar filigrana →"
            if tool == "compress":
                return "Configurar compresión →"
            if tool == "pdf_to_images":
                return "Configurar láminas →"

        if tool == "organize":
            return "Guardar pliego organizado"
        if tool == "split":
            return "Extraer páginas"
        if tool == "sign":
            return "Firmar y guardar"
        if tool == "merge":
            word = "pliego" if n_valid == 1 else "pliegos"
            return f"Unir {n_valid} {word}"
        if tool == "compress":
            word = "pliego" if n_pdfs == 1 else "pliegos"
            return f"Comprimir {n_pdfs} {word}"
        if tool == "images_to_pdf":
            word = "postal" if n_imgs == 1 else "postales"
            return f"Encuadernar {n_imgs} {word}"
        if tool == "pdf_to_images":
            return "Revelar páginas"
        if tool == "watermark":
            return "Estampar filigrana"
        if tool == "protect":
            return "Sellar con clave"
        if tool == "unlock":
            return "Abrir sello"
        return f"Procesar {self.activeToolTitle}"

    @Slot()
    def triggerPrimaryAction(self) -> None:
        """Ejecuta la acción principal de la barra inferior (desbloquear, abrir pantalla o procesar)."""
        if self._is_busy:
            self.cancelActiveOperation()
            return
        valid_files = self._valid_queued_files()
        if not valid_files:
            self._emit_error("Agrega al menos un archivo válido antes de continuar.")
            return
        if self.hasLockedFiles:
            for qf in valid_files:
                if qf.is_encrypted and qf.file_path.resolve() not in self._passwords:
                    self.passwordRequired.emit(str(qf.file_path), qf.file_path.name)
                    return
        if not self._is_tool_selected and self._active_tool in TOOLS_WITH_OPTIONS:
            self.selectTool(self._active_tool)
            return
        self.executeActiveOperation()

    @Property(str, notify=activeToolChanged)
    def activeToolTitle(self) -> str:
        if (
            self._active_tool == ToolType.MERGE.value
            and self._compute_input_context_state() == "mixed"
        ):
            return "Unir Todo en un PDF"
        for item in TOOLS_CATALOG:
            if item["id"] == self._active_tool:
                return item["title"]
        return "Mesa de Trabajo"

    @Property(str, notify=activeToolChanged)
    def activeToolSubtitle(self) -> str:
        if (
            self._active_tool == ToolType.MERGE.value
            and self._compute_input_context_state() == "mixed"
        ):
            return "Convierte e integra PDFs y postales en un solo cuaderno"
        for item in TOOLS_CATALOG:
            if item["id"] == self._active_tool:
                return item["subtitle"]
        return "Suelta tus pliegos PDF o postales y elige tu herramienta"

    @Property(str, notify=activeToolChanged)
    def workspaceMode(self) -> str:
        if not self._is_tool_selected or not self._queued_files:
            return "dropzone"
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
            ext = qf.file_path.suffix.lower()
            is_img = ext in SUPPORTED_IMAGE_EXTENSIONS
            is_corrupted = qf.status == "No se pudo leer"
            is_locked = bool(qf.is_encrypted and qf.file_path.resolve() not in self._passwords)
            if is_corrupted:
                thumb_url = ""
            elif is_img:
                thumb_url = QUrl.fromLocalFile(str(qf.file_path.resolve())).toString()
            else:
                encoded = quote(str(qf.file_path.resolve()))
                thumb_url = f"image://pdfpage/0?path={encoded}&dpi=72&locked={1 if is_locked else 0}"

            result.append(
                {
                    "index": idx,
                    "name": qf.file_path.name,
                    "path": str(qf.file_path),
                    "sizeFormatted": _format_bytes(qf.original_size_bytes),
                    "sizeBytes": qf.original_size_bytes,
                    "pageCount": qf.page_count,
                    "isEncrypted": qf.is_encrypted,
                    "isLocked": is_locked,
                    "isCorrupted": is_corrupted,
                    "isImage": is_img,
                    "status": qf.status,
                    "thumbnailUrl": thumb_url,
                }
            )
        return result

    @Property(int, notify=filesChanged)
    def fileCount(self) -> int:
        return len(self._queued_files)

    @Property(int, notify=filesChanged)
    def validFileCount(self) -> int:
        return len(self._valid_queued_files())

    @Property(int, notify=filesChanged)
    def totalQueuedBytes(self) -> int:
        return sum(f.original_size_bytes for f in self._valid_queued_files())

    @Property(int, notify=filesChanged)
    def totalQueuedPages(self) -> int:
        return sum(f.page_count for f in self._valid_queued_files())

    @Slot(int)
    def requestUnlockAt(self, index: int) -> None:
        """Abre el diálogo de contraseña para el archivo en la posición indicada."""
        if 0 <= index < len(self._queued_files):
            qf = self._queued_files[index]
            self.passwordRequired.emit(str(qf.file_path), qf.file_path.name)

    @Slot("QVariantList")
    def addFileUrls(self, urls_or_paths: list[Any]) -> None:
        """Agrega archivos desde Drag & Drop o FileDialog validando formato, duplicados e integridad."""
        added_any = False
        unsupported_names: list[str] = []
        duplicate_names: list[str] = []
        existing_resolved = {qf.file_path.resolve() for qf in self._queued_files}

        for raw in urls_or_paths:
            if isinstance(raw, QUrl):
                local_path = Path(raw.toLocalFile())
            else:
                text = str(raw)
                if text.startswith("file:"):
                    local_path = Path(QUrl(text).toLocalFile())
                else:
                    local_path = Path(text)

            if not local_path.exists() or not local_path.is_file():
                self._emit_error(f"El archivo no existe: {local_path.name}")
                continue

            ext = local_path.suffix.lower()
            if ext not in SUPPORTED_EXTENSIONS:
                unsupported_names.append(local_path.name)
                continue

            resolved_path = local_path.resolve()
            if resolved_path in existing_resolved:
                duplicate_names.append(local_path.name)
                continue

            size_b = local_path.stat().st_size
            if size_b == 0:
                self._emit_error(
                    f"El archivo '{local_path.name}' está vacío (0 bytes)."
                )
                continue

            if ext in SUPPORTED_IMAGE_EXTENSIONS:
                self._queued_files.append(
                    QueuedFile(
                        file_path=local_path,
                        original_size_bytes=size_b,
                        page_count=1,
                        is_encrypted=False,
                        status="Imagen lista",
                    )
                )
                existing_resolved.add(resolved_path)
                added_any = True
                continue

            try:
                saved_pwd = self._passwords.get(resolved_path)
                info = inspect_pdf_file(local_path, password=saved_pwd)
                self._queued_files.append(info)
                existing_resolved.add(resolved_path)
                added_any = True

                if info.is_encrypted and not saved_pwd:
                    self.passwordRequired.emit(str(local_path), local_path.name)
            except PDFCorruptedError:
                self._queued_files.append(
                    QueuedFile(
                        file_path=local_path,
                        original_size_bytes=size_b,
                        page_count=0,
                        is_encrypted=False,
                        status="No se pudo leer",
                    )
                )
                existing_resolved.add(resolved_path)
                added_any = True
                self._emit_error(
                    f"No se pudo leer '{local_path.name}'. Puedes quitarlo de la cola; se excluirá del proceso."
                )
            except InvalidPasswordError as exc:
                self._emit_error(str(exc))

        if duplicate_names:
            dup_label = duplicate_names[0] if len(duplicate_names) == 1 else f"{len(duplicate_names)} archivos"
            self._emit_notice(f"Ya está en la mesa: '{dup_label}'", is_error=False)

        if unsupported_names:
            joined = ", ".join(f"'{n}'" for n in unsupported_names[:3])
            if len(unsupported_names) > 3:
                joined += f" y {len(unsupported_names) - 3} más"
            self._emit_error(
                f"Formato no compatible ignorado ({joined}). Solo se admiten pliegos PDF e imágenes PNG, JPG o WEBP."
            )

        if added_any:
            if not self._output_directory and self._queued_files:
                remembered = str(self._settings.value("lastOutputDirectory", "") or "")
                if remembered and Path(remembered).is_dir():
                    self._output_directory = remembered
                else:
                    self._output_directory = str(self._queued_files[0].file_path.parent)
                self._revalidate_output_directory()
                self.configChanged.emit()
            self._rebuild_pages_from_primary_file()
            self._revalidate_range()
            self._sync_contextual_tool_after_queue_change()
            self._update_ready_status_message()
            self.filesChanged.emit()
            self.activeToolChanged.emit()

    @Slot(str)
    def addSingleFilePath(self, path_str: str) -> None:
        self.addFileUrls([path_str])

    @Slot()
    def keepOnlyPdfs(self) -> None:
        """Filtra la cola actual conservando únicamente los archivos PDF."""
        filtered = [
            qf
            for qf in self._queued_files
            if qf.file_path.suffix.lower() in SUPPORTED_PDF_EXTENSIONS
        ]
        if len(filtered) != len(self._queued_files):
            self._queued_files = filtered
            self._rebuild_pages_from_primary_file()
            self._revalidate_range()
            self._sync_contextual_tool_after_queue_change()
            self._update_ready_status_message()
            self.filesChanged.emit()
            self.activeToolChanged.emit()

    @Slot()
    def keepOnlyImages(self) -> None:
        """Filtra la cola actual conservando únicamente los archivos de imagen."""
        filtered = [
            qf
            for qf in self._queued_files
            if qf.file_path.suffix.lower() in SUPPORTED_IMAGE_EXTENSIONS
        ]
        if len(filtered) != len(self._queued_files):
            self._queued_files = filtered
            self._rebuild_pages_from_primary_file()
            self._revalidate_range()
            self._sync_contextual_tool_after_queue_change()
            self._update_ready_status_message()
            self.filesChanged.emit()
            self.activeToolChanged.emit()

    @Slot(str, str)
    def supplyFilePassword(self, file_path_str: str, password: str) -> bool:
        """Desbloquea en memoria un PDF protegido cargado en la cola."""
        path = Path(file_path_str)
        try:
            info = inspect_pdf_file(path, password=password)
        except (InvalidPasswordError, PDFCorruptedError) as exc:
            self._emit_error(str(exc))
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
        self.activeToolChanged.emit()
        return True

    @Slot(int)
    def removeFileAt(self, index: int) -> None:
        if 0 <= index < len(self._queued_files):
            removed = self._queued_files.pop(index)
            self.image_provider.invalidate_file(removed.file_path)
            self._rebuild_pages_from_primary_file()
            self._revalidate_range()
            self._sync_contextual_tool_after_queue_change()
            self._update_ready_status_message()
            self.filesChanged.emit()
            self.activeToolChanged.emit()

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
        self.task_manager.thumbnail_cache.clear()
        self._is_tool_selected = False
        self._has_processing_error = False
        self._sync_contextual_tool_after_queue_change()
        self._update_ready_status_message()
        self.filesChanged.emit()
        self.pagesChanged.emit()
        self.viewerChanged.emit()
        self.activeToolChanged.emit()

    # --- Organizador de Páginas (Page Organizer) ---

    def _reindex_organizer_pages(self) -> None:
        """Actualiza displayPageNumber de forma correlativa (1..N) tras mover, duplicar o eliminar."""
        for idx, page_dict in enumerate(self._organizer_pages):
            page_dict["displayPageNumber"] = idx + 1

    def _rebuild_pages_from_primary_file(self) -> None:
        self._organizer_pages.clear()
        self._viewer_page_index = 0
        valid_files = self._valid_queued_files()
        if not valid_files:
            self.pagesChanged.emit()
            self.viewerChanged.emit()
            return

        primary = valid_files[0]
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
            self._emit_error(
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
            self._emit_error(
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

    def _revalidate_output_directory(self) -> None:
        """Valida que la carpeta de destino exista o pueda crearse, tenga permisos de escritura y espacio."""
        if not self._output_directory:
            self._output_directory_valid = True
            self._output_directory_error = ""
            return
        try:
            target = Path(self._output_directory)
            if target.exists() and not target.is_dir():
                self._output_directory_valid = False
                self._output_directory_error = "La ruta seleccionada no es una carpeta válida."
                return
            probe_dir = target if target.exists() else target.parent
            if not probe_dir.exists():
                self._output_directory_valid = False
                self._output_directory_error = "La carpeta de destino no existe o no está disponible."
                return
            if not os.access(probe_dir, os.W_OK):
                self._output_directory_valid = False
                self._output_directory_error = "Sin permisos de escritura en la carpeta elegida."
                return
            usage = shutil.disk_usage(probe_dir)
            min_required = max(1024 * 1024, self.totalQueuedBytes)
            if usage.free < min_required:
                self._output_directory_valid = False
                self._output_directory_error = "Espacio insuficiente en disco para guardar."
                return
            self._output_directory_valid = True
            self._output_directory_error = ""
        except OSError:
            self._output_directory_valid = False
            self._output_directory_error = "No se puede acceder a la carpeta de guardado seleccionada."

    @Property(str, notify=configChanged)
    def outputDirectory(self) -> str:
        return self._output_directory

    @Property(bool, notify=configChanged)
    def isOutputDirectoryValid(self) -> bool:
        return self._output_directory_valid

    @Property(str, notify=configChanged)
    def outputDirectoryError(self) -> str:
        return self._output_directory_error

    @Slot(str)
    def setOutputDirectory(self, path_or_url: str) -> None:
        if path_or_url.startswith("file:"):
            clean = QUrl(path_or_url).toLocalFile()
        else:
            clean = path_or_url
        if clean != self._output_directory:
            self._output_directory = clean
            self._revalidate_output_directory()
            if self._output_directory_valid and clean:
                self._settings.setValue("lastOutputDirectory", clean)
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
    def retryLastOperation(self) -> None:
        """Reintenta la operación activa tras un error sin perder la cola."""
        self.executeActiveOperation()

    @Slot()
    def executeActiveOperation(self) -> None:
        """Construye y lanza el PDFOperationWorker correspondiente a la herramienta activa."""
        if self._is_busy:
            return
        valid_files = self._valid_queued_files()
        if not valid_files:
            self._emit_error(
                "Agrega al menos un archivo válido en la mesa de trabajo antes de procesar."
            )
            return

        self._revalidate_output_directory()
        if not self._output_directory_valid:
            self._has_processing_error = True
            self._status_message = self._output_directory_error
            self._emit_error(self._output_directory_error)
            return

        primary_file = valid_files[0].file_path
        primary_pwd = self._passwords.get(primary_file.resolve()) or self._password_input or None
        out_dir = (
            Path(self._output_directory)
            if self._output_directory
            else primary_file.parent
        )
        try:
            out_dir.mkdir(parents=True, exist_ok=True)
        except OSError:
            err_text = "No se pudo crear ni escribir en la carpeta de destino. Elige otra ubicación."
            self._output_directory_valid = False
            self._output_directory_error = err_text
            self._has_processing_error = True
            self._status_message = err_text
            self.configChanged.emit()
            self._emit_error(err_text)
            return

        tool = ToolType(self._active_tool)
        try:
            worker = self._build_worker_for_tool(
                tool, primary_file, primary_pwd, out_dir
            )
        except PDFStudioError as exc:
            self._has_processing_error = True
            self._status_message = str(exc)
            self._emit_error(str(exc))
            return

        self._has_processing_error = False
        self._is_busy = True
        self._progress_percent = 5
        self._status_message = "Iniciando tarea en segundo plano..."
        self.progressChanged.emit()
        self.activeToolChanged.emit()

        worker.signals.progress.connect(self._on_worker_progress)
        worker.signals.finished.connect(self._on_worker_finished)
        worker.signals.cancelled.connect(self._on_worker_cancelled)
        worker.signals.error.connect(self._on_worker_error)
        self.task_manager.start_operation(worker)

    @staticmethod
    def _merge_mixed_files_task(
        input_files: list[Path],
        output_path: Path,
        passwords: dict[Path, str] | None = None,
        on_progress: Any = None,
        is_cancelled: Any = None,
    ) -> OperationResult:
        """Une e integra archivos PDF e imágenes (.png/.jpg/.jpeg/.webp) en un único PDF."""
        import pymupdf as fitz

        passwords = passwords or {}
        total_original_bytes = 0
        total_files = len(input_files)
        merged_doc = fitz.open()
        try:
            for idx, item_path in enumerate(input_files):
                if is_cancelled is not None and is_cancelled():
                    raise TaskCancelledError("Operación cancelada por el usuario.")
                path = Path(item_path)
                total_original_bytes += path.stat().st_size
                ext = path.suffix.lower()

                if ext in SUPPORTED_PDF_EXTENSIONS:
                    pwd = passwords.get(path) or passwords.get(path.resolve())
                    src_doc = fitz.open(path)
                    try:
                        if src_doc.needs_pass and pwd:
                            src_doc.authenticate(pwd)
                        merged_doc.insert_pdf(src_doc)
                    finally:
                        src_doc.close()
                else:
                    img_doc = fitz.open(path)
                    try:
                        pdf_bytes = img_doc.convert_to_pdf()
                        img_pdf = fitz.open("pdf", pdf_bytes)
                        try:
                            merged_doc.insert_pdf(img_pdf)
                        finally:
                            img_pdf.close()
                    finally:
                        img_doc.close()

                if on_progress is not None:
                    pct = int(((idx + 1) / total_files) * 88)
                    on_progress(pct, f"Integrando '{path.name}' ({idx + 1}/{total_files})...")

            safe_dest = ensure_safe_output_path(
                Path(input_files[0]), output_path, default_suffix="_integrado"
            )
            merged_doc.save(str(safe_dest), deflate=True)
            if on_progress is not None:
                on_progress(100, "Documentos e imágenes integrados en un PDF.")
            final_bytes = safe_dest.stat().st_size
            return OperationResult(
                tool=ToolType.MERGE,
                output_files=[safe_dest],
                original_size_bytes=total_original_bytes,
                final_size_bytes=final_bytes,
                saved_percentage=0.0,
                message=f"Se integraron {total_files} archivos (PDF e imágenes) en '{safe_dest.name}'.",
            )
        finally:
            merged_doc.close()

    @staticmethod
    def _batch_pdf_task(
        pdf_files: list[Path],
        out_dir: Path,
        passwords: dict[Path, str],
        tool: ToolType,
        compression_level: CompressionLevel,
        image_format: ImageFormat,
        watermark_config: WatermarkConfig,
        on_progress: Any = None,
        is_cancelled: Any = None,
    ) -> OperationResult:
        """Ejecuta compresión, exportación a imágenes o marca de agua sobre un lote de PDFs."""
        all_outputs: list[Path] = []
        total_orig = 0
        total_final = 0
        total = len(pdf_files)

        for idx, pdf_path in enumerate(pdf_files):
            if is_cancelled is not None and is_cancelled():
                raise TaskCancelledError("Operación cancelada por el usuario.")
            pwd = passwords.get(pdf_path) or passwords.get(pdf_path.resolve())

            def _sub_progress(p: int, msg: str, i: int = idx) -> None:
                if on_progress is not None:
                    overall = int(((i + (p / 100.0)) / total) * 100)
                    on_progress(overall, f"[{i + 1}/{total}] {msg}")

            if tool == ToolType.COMPRESS:
                dest = ensure_safe_output_path(
                    pdf_path,
                    out_dir / f"{pdf_path.stem}_comprimido.pdf",
                    "_comprimido",
                )
                res = PDFEngine.compress_pdf(
                    pdf_path,
                    dest,
                    level=compression_level,
                    password=pwd,
                    on_progress=_sub_progress,
                    is_cancelled=is_cancelled,
                )
            elif tool == ToolType.PDF_TO_IMAGES:
                subdir = out_dir / f"{pdf_path.stem}_imagenes"
                res = PDFEngine.pdf_to_images(
                    pdf_path,
                    subdir,
                    image_format=image_format,
                    password=pwd,
                    on_progress=_sub_progress,
                    is_cancelled=is_cancelled,
                )
            else:
                dest = ensure_safe_output_path(
                    pdf_path,
                    out_dir / f"{pdf_path.stem}_marca_agua.pdf",
                    "_marca_agua",
                )
                res = PDFEngine.apply_watermark(
                    pdf_path,
                    dest,
                    watermark_config,
                    password=pwd,
                    on_progress=_sub_progress,
                    is_cancelled=is_cancelled,
                )

            all_outputs.extend(res.output_files)
            total_orig += res.original_size_bytes
            total_final += res.final_size_bytes

        saved_pct = (
            max(0.0, ((total_orig - total_final) / total_orig) * 100.0)
            if total_orig > 0 and tool == ToolType.COMPRESS
            else 0.0
        )
        return OperationResult(
            tool=tool,
            output_files=all_outputs,
            original_size_bytes=total_orig,
            final_size_bytes=total_final,
            saved_percentage=round(saved_pct, 2),
            message=f"Lote procesado con éxito ({total} pliegos PDF, {len(all_outputs)} archivo(s) generados).",
        )

    def _build_worker_for_tool(
        self,
        tool: ToolType,
        primary_file: Path,
        primary_pwd: str | None,
        out_dir: Path,
    ) -> PDFOperationWorker:
        valid_files = self._valid_queued_files()
        pdf_paths = [
            qf.file_path
            for qf in valid_files
            if qf.file_path.suffix.lower() in SUPPORTED_PDF_EXTENSIONS
        ]
        img_paths = [
            qf.file_path
            for qf in valid_files
            if qf.file_path.suffix.lower() in SUPPORTED_IMAGE_EXTENSIONS
        ]

        if tool == ToolType.MERGE:
            all_paths = [qf.file_path for qf in valid_files]
            if img_paths and pdf_paths:
                dest = ensure_safe_output_path(
                    primary_file,
                    out_dir / f"{primary_file.stem}_integrado.pdf",
                    "_integrado",
                )
                return PDFOperationWorker(
                    self._merge_mixed_files_task,
                    all_paths,
                    dest,
                    passwords=dict(self._passwords),
                )
            dest = ensure_safe_output_path(
                primary_file, out_dir / f"{primary_file.stem}_unido.pdf", "_unido"
            )
            return PDFOperationWorker(
                PDFEngine.merge_pdfs,
                pdf_paths or all_paths,
                dest,
                passwords=dict(self._passwords),
            )

        if tool == ToolType.SPLIT:
            target_pdf = pdf_paths[0] if pdf_paths else primary_file
            dest = ensure_safe_output_path(
                target_pdf,
                out_dir / f"{target_pdf.stem}_extraido.pdf",
                "_extraido",
            )
            return PDFOperationWorker(
                PDFEngine.split_pdf_by_range,
                target_pdf,
                dest,
                self._range_expr,
                password=primary_pwd,
                split_into_separate_files=self._split_separate,
            )

        if tool == ToolType.ORGANIZE:
            target_pdf = pdf_paths[0] if pdf_paths else primary_file
            instructions = [
                PageItemInstruction(
                    source_page_index=int(p["sourcePageIndex"]),
                    rotation_degrees=int(p["rotation"]),
                )
                for p in self._organizer_pages
            ]
            dest = ensure_safe_output_path(
                target_pdf,
                out_dir / f"{target_pdf.stem}_organizado.pdf",
                "_organizado",
            )
            return PDFOperationWorker(
                PDFEngine.organize_pdf,
                target_pdf,
                dest,
                instructions,
                password=primary_pwd,
            )

        if tool in {ToolType.COMPRESS, ToolType.PDF_TO_IMAGES, ToolType.WATERMARK} and len(pdf_paths) > 1:
            wm_cfg = WatermarkConfig(
                text=self._watermark_text,
                opacity=self._watermark_opacity,
                angle=self._watermark_angle,
                position=WatermarkPosition(self._watermark_position),
            )
            return PDFOperationWorker(
                self._batch_pdf_task,
                pdf_paths,
                out_dir,
                dict(self._passwords),
                tool,
                CompressionLevel(self._compression_level),
                ImageFormat(self._image_format),
                wm_cfg,
            )

        if tool == ToolType.COMPRESS:
            target_pdf = pdf_paths[0] if pdf_paths else primary_file
            dest = ensure_safe_output_path(
                target_pdf,
                out_dir / f"{target_pdf.stem}_comprimido.pdf",
                "_comprimido",
            )
            return PDFOperationWorker(
                PDFEngine.compress_pdf,
                target_pdf,
                dest,
                level=CompressionLevel(self._compression_level),
                password=primary_pwd,
            )

        if tool == ToolType.PDF_TO_IMAGES:
            target_pdf = pdf_paths[0] if pdf_paths else primary_file
            export_subdir = out_dir / f"{target_pdf.stem}_imagenes"
            return PDFOperationWorker(
                PDFEngine.pdf_to_images,
                target_pdf,
                export_subdir,
                image_format=ImageFormat(self._image_format),
                password=primary_pwd,
            )

        if tool == ToolType.IMAGES_TO_PDF:
            target_imgs = img_paths or [qf.file_path for qf in valid_files]
            dest = ensure_safe_output_path(
                target_imgs[0],
                out_dir / f"{target_imgs[0].stem}_album.pdf",
                "_album",
            )
            return PDFOperationWorker(
                PDFEngine.images_to_pdf,
                target_imgs,
                dest,
            )

        if tool == ToolType.WATERMARK:
            target_pdf = pdf_paths[0] if pdf_paths else primary_file
            dest = ensure_safe_output_path(
                target_pdf,
                out_dir / f"{target_pdf.stem}_marca_agua.pdf",
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
                target_pdf,
                dest,
                wm_cfg,
                password=primary_pwd,
            )

        # ToolType.SIGN
        target_pdf = pdf_paths[0] if pdf_paths else primary_file
        dest = ensure_safe_output_path(
            target_pdf,
            out_dir / f"{target_pdf.stem}_firmado.pdf",
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
            target_pdf,
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
        self._has_processing_error = False
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
        self.activeToolChanged.emit()
        self.historyChanged.emit()
        self.operationCompleted.emit(result.message, first_out, folder_out)

    def _on_worker_cancelled(self, message: str) -> None:
        self._is_busy = False
        self._has_processing_error = False
        self._progress_percent = 0
        self._status_message = message
        self.progressChanged.emit()
        self.activeToolChanged.emit()

    def _on_worker_error(self, error_msg: str) -> None:
        self._is_busy = False
        self._has_processing_error = True
        self._progress_percent = 0
        self._status_message = f"No se pudo completar: {error_msg}"
        self.activeToolChanged.emit()
        self._emit_error(error_msg)

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

