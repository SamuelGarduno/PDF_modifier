"""Puente reactivo (QObject Bridge) entre el motor asíncrono Python y la interfaz QtQuick/QML."""

from __future__ import annotations

import ctypes
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time
from typing import Any
from urllib.parse import quote

from PySide6.QtCore import (
    Property,
    QObject,
    QSettings,
    Qt,
    QUrl,
    Signal,
    Slot,
)
from PySide6.QtGui import QDesktopServices, QImage

from core.exceptions import (
    InvalidPasswordError,
    PDFCorruptedError,
    PDFEncryptedError,
    PDFStudioError,
    TaskCancelledError,
)
from core.filename_utils import (
    clean_windows_filename_stem,
    resolve_unique_output_path,
    sanitize_windows_filename,
)
from core.history import OperationHistoryStore
from core.models import (
    DECIMAL_MB_BYTES,
    STROKE_WIDTH_PT_MAP,
    TARGET_SIZE_MAX_MB,
    TARGET_SIZE_MIN_MB,
    TARGET_SIZE_PRESETS_MB,
    TARGET_SIZE_SAFETY_FACTOR,
    CompressionLevel,
    ImageFormat,
    OperationResult,
    PageItemInstruction,
    QueuedFile,
    SignatureOverlay,
    StrokeWidthPreset,
    TargetCompressionResult,
    ToolType,
    WatermarkConfig,
    WatermarkPosition,
)
from core.range_parser import format_page_ranges, validate_page_ranges_realtime
from core.word_converter import (
    SUPPORTED_WORD_EXTENSIONS,
    convert_word_batch,
    convert_word_to_pdf,
)
from core.workers import AsyncTaskManager, PDFOperationWorker
from ui.image_provider import PDFPageImageProvider


def _pdf_engine_module() -> Any:
    """Importa core.pdf_engine bajo demanda para evitar cargas pesadas en el arranque."""
    import core.pdf_engine as pdf_engine_mod

    return pdf_engine_mod

SUPPORTED_PDF_EXTENSIONS: frozenset[str] = frozenset({".pdf"})
SUPPORTED_IMAGE_EXTENSIONS: frozenset[str] = frozenset(
    {".png", ".jpg", ".jpeg", ".webp"}
)
SUPPORTED_EXTENSIONS: frozenset[str] = (
    SUPPORTED_PDF_EXTENSIONS | SUPPORTED_IMAGE_EXTENSIONS | SUPPORTED_WORD_EXTENSIONS
)
SHOW_FOLDER_DEBOUNCE_SECONDS: float = 0.8

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
        "workspaceMode": "split",
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
    {
        "id": "word_to_pdf",
        "title": "Word a PDF",
        "subtitle": "Convierte documentos .docx y .doc a PDF",
        "badge": "D",
        "workspaceMode": "dropzone",
    },
]

TOOLS_BY_ID: dict[str, dict[str, str]] = {item["id"]: item for item in TOOLS_CATALOG}

MAX_VIEWER_UNDO_STEPS = 50
DEFAULT_STAMP_RECT: tuple[float, float, float, float] = (0.60, 0.78, 0.92, 0.92)
DEFAULT_IMAGE_RECT: tuple[float, float, float, float] = (0.375, 0.42, 0.625, 0.56)
DEFAULT_IMAGE_ASPECT = 2.2



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
    difficultCompressionOccurred = Signal(str, str)  # summary, advisory
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
        self._organizer_initial_snapshot: list[dict[str, Any]] = []

        # Estado del Visor y Capa de Firma
        self._viewer_page_index: int = 0
        self._viewer_zoom: float = 1.0
        self._viewer_dpr: float = 1.0
        self._viewer_draw_mode: bool = True
        self._signature_stroke_width_key: str = StrokeWidthPreset.FINE.value
        self._signature_stamp: str = "APROBADO"
        self._signature_image_path: str = ""
        self._freehand_strokes: list[list[tuple[float, float]]] = []
        self._page_annotations: dict[int, dict[str, Any]] = {}
        self._viewer_undo_stack: list[dict[str, Any]] = []
        self._pending_undo_checkpoint: dict[str, Any] | None = None
        self._primary_doc_key: str = ""

        # Estado de los Paneles de Configuración Inferior
        self._range_expr: str = "1-2"
        self._range_valid: bool = True
        self._range_feedback: str = "Ingresa un rango como '1-5, 8, 11-13'"
        self._split_selected_indices: set[int] = set()
        self._split_separate: bool = False
        self._compression_level: str = CompressionLevel.RECOMMENDED.value
        self._is_target_size_mode: bool = False
        self._target_size_mb: float = 5.0
        self._target_size_text: str = "5"
        self._target_size_valid: bool = True
        self._target_size_feedback: str = (
            "Límite efectivo: 4.75 MB (95% de seguridad)"
        )
        self._compression_estimate_cache: dict[
            tuple[str, int, int], dict[str, dict[str, float | int | bool]]
        ] = {}
        self._target_anatomy_cache: dict[tuple[str, int, int], dict[str, Any]] = {}
        self._is_estimating_compression: bool = False
        self._estimate_generation_id: int = 0
        self._active_estimate_worker: PDFOperationWorker | None = None
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
        self._custom_output_name: str = ""
        self._output_name_user_edited: bool = False

        # Estado de Ejecución y Footer
        self._is_busy: bool = False
        self._progress_percent: int = 0
        self._status_message: str = "Listo para trabajar en tu escritorio de papelería."
        self._last_output_file: str = ""
        self._last_output_file_path: str = ""
        self._last_output_folder: str = ""
        self._last_show_folder_monotonic: float = 0.0
        self._last_compression_comparison: str = ""
        self._last_compression_quality_label: str = ""
        self._last_compression_preview_url: str = ""
        self._difficult_target_context: dict[str, Any] | None = None
        self._pending_target_request: dict[str, Any] | None = None
        self._pending_rescue_preview: bool = False

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
        word_count = 0
        for qf in valid_files:
            ext = qf.file_path.suffix.lower()
            if ext in SUPPORTED_PDF_EXTENSIONS:
                pdf_count += 1
            elif ext in SUPPORTED_IMAGE_EXTENSIONS:
                img_count += 1
            elif ext in SUPPORTED_WORD_EXTENSIONS:
                word_count += 1
        if word_count >= 1 and pdf_count == 0 and img_count == 0:
            return "word_only"
        if pdf_count == 1 and img_count == 0 and word_count == 0:
            return "single_pdf"
        if pdf_count >= 2 and img_count == 0 and word_count == 0:
            return "multi_pdf"
        if img_count >= 1 and pdf_count == 0 and word_count == 0:
            return "images_only"
        if (pdf_count >= 1 or img_count >= 1 or word_count >= 1):
            return "mixed"
        return "empty"

    @Property(str, notify=filesChanged)
    def inputContextState(self) -> str:
        """Estado contextual actual: 'empty', 'single_pdf', 'multi_pdf', 'images_only', 'word_only' o 'mixed'."""
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

    @Property(int, notify=filesChanged)
    def wordCount(self) -> int:
        return sum(
            1
            for qf in self._valid_queued_files()
            if qf.file_path.suffix.lower() in SUPPORTED_WORD_EXTENSIONS
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
        if state == "word_only":
            n = self.wordCount
            return f"{n} {'documento Word listo' if n == 1 else 'documentos Word listos'}"
        if state == "mixed":
            parts: list[str] = []
            if self.pdfCount:
                parts.append(f"{self.pdfCount} {'pliego' if self.pdfCount == 1 else 'pliegos'}")
            if self.wordCount:
                parts.append(f"{self.wordCount} Word")
            if self.imageCount:
                parts.append(f"{self.imageCount} {'postal' if self.imageCount == 1 else 'postales'}")
            return " · ".join(parts)
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
        if state == "word_only":
            n = self.wordCount
            word = "documento Word" if n == 1 else "documentos Word"
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

        if state == "word_only":
            # Caso 4: Uno o más documentos de Word (.docx, .doc)
            return [
                _make_card(
                    "word_to_pdf",
                    is_primary=True,
                    override_subtitle="Convierte documentos Word (.docx/.doc) a PDF usando Microsoft Word",
                ),
            ]

        # Caso 5: Mezcla de PDFs, Word e imágenes
        return [
            _make_card(
                "merge",
                is_primary=True,
                override_title="Unir Todo en un PDF",
                override_subtitle="Convierte e integra PDFs, Word y postales en un solo cuaderno",
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
            self.configChanged.emit()
            self.progressChanged.emit()
            self._schedule_compression_estimation()

    def _sync_contextual_tool_after_queue_change(self) -> None:
        """Sincroniza la herramienta activa y el modo de vista tras cambios en la cola de archivos."""
        if not self._queued_files:
            # Si se eliminan todos los archivos, regresa automáticamente a Mesa de Trabajo Vacía
            if self._is_tool_selected:
                self._is_tool_selected = False
            self.activeToolChanged.emit()
            self.configChanged.emit()
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
        self.configChanged.emit()

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
            self._last_compression_comparison = ""
            self._last_compression_quality_label = ""
            self._last_compression_preview_url = ""
            self._difficult_target_context = None
            self._update_ready_status_message()
        if changed:
            self.activeToolChanged.emit()
            self.configChanged.emit()
        self._revalidate_range()
        self._schedule_compression_estimation()
        if tool_id == ToolType.COMPRESS.value:
            pdf_engine = _pdf_engine_module().PDFEngine
            for qf in self._valid_queued_files():
                if qf.file_path.suffix.lower() in SUPPORTED_PDF_EXTENSIONS:
                    pwd = self._passwords.get(qf.file_path.resolve())
                    if pdf_engine.has_digital_signature(qf.file_path, password=pwd):
                        self._emit_notice(
                            f"Aviso: '{qf.file_path.name}' contiene una firma digital criptográfica que se invalidará al comprimirlo.",
                            is_error=False,
                        )
                        break
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
            self.configChanged.emit()

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
        if tool == "word_to_pdf":
            n_words = max(1, self.wordCount)
            word = "documento Word" if n_words == 1 else "documentos Word"
            return f"Convertir {n_words} {word}"
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
            return "Convierte e integra PDFs, Word y postales en un solo cuaderno"
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
            is_word = ext in SUPPORTED_WORD_EXTENSIONS
            is_corrupted = qf.status == "No se pudo leer"
            is_locked = bool(qf.is_encrypted and qf.file_path.resolve() not in self._passwords)
            if is_corrupted or is_word:
                thumb_url = ""
            elif is_img:
                thumb_url = QUrl.fromLocalFile(str(qf.file_path.resolve())).toString()
            else:
                encoded = quote(str(qf.file_path.resolve()))
                thumb_url = f"image://pdfpage/0?path={encoded}&dpi=60&locked={1 if is_locked else 0}"

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
                    "isWord": is_word,
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

            if ext in SUPPORTED_WORD_EXTENSIONS:
                self._queued_files.append(
                    QueuedFile(
                        file_path=local_path,
                        original_size_bytes=size_b,
                        page_count=0,
                        is_encrypted=False,
                        status="Documento Word",
                    )
                )
                existing_resolved.add(resolved_path)
                added_any = True
                continue

            try:
                saved_pwd = self._passwords.get(resolved_path)
                info = _pdf_engine_module().inspect_pdf_file(
                    local_path, password=saved_pwd
                )
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
                f"Formato no compatible ignorado ({joined}). Solo se admiten pliegos PDF, documentos Word (.docx/.doc) e imágenes PNG, JPG o WEBP."
            )

        if added_any:
            if not self._output_directory and self._queued_files:
                remembered = str(self._settings.value("lastOutputDirectory", "") or "")
                if remembered and Path(remembered).is_dir():
                    self._output_directory = remembered
                else:
                    self._output_directory = str(self._queued_files[0].file_path.parent)
                self._revalidate_output_directory()
            self._rebuild_pages_from_primary_file()
            self._revalidate_range()
            self._sync_contextual_tool_after_queue_change()
            self._update_ready_status_message()
            self._schedule_compression_estimation()
            self.filesChanged.emit()
            self.activeToolChanged.emit()
            self.configChanged.emit()

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
            self._schedule_compression_estimation()
            self.filesChanged.emit()
            self.activeToolChanged.emit()
            self.configChanged.emit()

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
            self._schedule_compression_estimation()
            self.filesChanged.emit()
            self.activeToolChanged.emit()
            self.configChanged.emit()

    @Slot()
    def keepOnlyWord(self) -> None:
        """Filtra la cola actual conservando únicamente los documentos Word (.docx/.doc)."""
        filtered = [
            qf
            for qf in self._queued_files
            if qf.file_path.suffix.lower() in SUPPORTED_WORD_EXTENSIONS
        ]
        if len(filtered) != len(self._queued_files):
            self._queued_files = filtered
            self._rebuild_pages_from_primary_file()
            self._revalidate_range()
            self._sync_contextual_tool_after_queue_change()
            self._update_ready_status_message()
            self._schedule_compression_estimation()
            self.filesChanged.emit()
            self.activeToolChanged.emit()
            self.configChanged.emit()

    @Slot(str, str)
    def supplyFilePassword(self, file_path_str: str, password: str) -> bool:
        """Desbloquea en memoria un PDF protegido cargado en la cola."""
        path = Path(file_path_str)
        try:
            info = _pdf_engine_module().inspect_pdf_file(path, password=password)
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
        self._schedule_compression_estimation()
        self.filesChanged.emit()
        self.activeToolChanged.emit()
        self.configChanged.emit()
        return True

    @Slot(int)
    def removeFileAt(self, index: int) -> None:
        if 0 <= index < len(self._queued_files):
            removed = self._queued_files.pop(index)
            self._difficult_target_context = None
            self.image_provider.invalidate_file(removed.file_path)
            self._rebuild_pages_from_primary_file()
            self._revalidate_range()
            self._sync_contextual_tool_after_queue_change()
            self._update_ready_status_message()
            self._schedule_compression_estimation()
            self.filesChanged.emit()
            self.activeToolChanged.emit()
            self.configChanged.emit()

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
            self.configChanged.emit()

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
        if self._active_estimate_worker is not None:
            self._active_estimate_worker.cancel()
            self._active_estimate_worker = None
        self._queued_files.clear()
        self._organizer_pages.clear()
        self._organizer_initial_snapshot.clear()
        self._freehand_strokes.clear()
        self._page_annotations.clear()
        self._viewer_undo_stack.clear()
        self._pending_undo_checkpoint = None
        self._primary_doc_key = ""
        self._signature_image_path = ""
        self._signature_stamp = "APROBADO"
        self._custom_output_name = ""
        self._output_name_user_edited = False
        self.task_manager.thumbnail_cache.clear()
        self.image_provider.cache.clear()
        self._is_tool_selected = False
        self._has_processing_error = False
        self._difficult_target_context = None
        self._last_compression_comparison = ""
        self._last_compression_quality_label = ""
        self._last_compression_preview_url = ""
        self._schedule_compression_estimation()
        self._sync_contextual_tool_after_queue_change()
        self._update_ready_status_message()
        self.filesChanged.emit()
        self.pagesChanged.emit()
        self.viewerChanged.emit()
        self.activeToolChanged.emit()
        self.configChanged.emit()

    # --- Organizador de Páginas (Page Organizer) ---

    def _reindex_organizer_pages(self) -> None:
        """Actualiza displayPageNumber de forma correlativa (1..N) tras mover, duplicar o eliminar."""
        for idx, page_dict in enumerate(self._organizer_pages):
            page_dict["displayPageNumber"] = idx + 1

    def _rebuild_pages_from_primary_file(self) -> None:
        self._organizer_pages.clear()
        self._organizer_initial_snapshot.clear()
        self._viewer_page_index = 0
        valid_files = self._valid_queued_files()
        if not valid_files:
            self._page_annotations.clear()
            self._viewer_undo_stack.clear()
            self._pending_undo_checkpoint = None
            self._primary_doc_key = ""
            self._custom_output_name = ""
            self._output_name_user_edited = False
            self._sync_current_page_viewer_state()
            self.pagesChanged.emit()
            self.viewerChanged.emit()
            self.configChanged.emit()
            return

        primary = valid_files[0]
        new_doc_key = str(primary.file_path.resolve())
        if new_doc_key != self._primary_doc_key:
            self._primary_doc_key = new_doc_key
            self._page_annotations.clear()
            self._viewer_undo_stack.clear()
            self._pending_undo_checkpoint = None
            self._custom_output_name = ""
            self._output_name_user_edited = False
        self._sync_current_page_viewer_state()

        if primary.page_count < 1 or primary.file_path.suffix.lower() != ".pdf":
            self.pagesChanged.emit()
            self.viewerChanged.emit()
            self.configChanged.emit()
            return

        encoded_path = quote(str(primary.file_path.resolve()))
        for idx in range(primary.page_count):
            self._organizer_pages.append(
                {
                    "sourcePageIndex": idx,
                    "displayPageNumber": idx + 1,
                    "rotation": 0,
                    "selected": False,
                    "thumbnailUrl": f"image://pdfpage/{idx}?path={encoded_path}&dpi=72",
                }
            )
        self._organizer_initial_snapshot = [dict(p) for p in self._organizer_pages]
        self.pagesChanged.emit()
        self.viewerChanged.emit()
        self.configChanged.emit()

    @Property(bool, notify=pagesChanged)
    def hasOrganizerChanges(self) -> bool:
        """Indica si el orden, rotación o cantidad de páginas difiere del estado inicial cargado."""
        if not self._organizer_initial_snapshot:
            return False
        current_state = [
            (int(p["sourcePageIndex"]), int(p["rotation"]))
            for p in self._organizer_pages
        ]
        initial_state = [
            (int(p["sourcePageIndex"]), int(p["rotation"]))
            for p in self._organizer_initial_snapshot
        ]
        return current_state != initial_state

    @Slot()
    def restoreOrganizerOriginal(self) -> None:
        """Revierte orden, rotaciones, duplicados y eliminaciones al estado inicial sin re-renderizar."""
        if not self._organizer_initial_snapshot or not self.hasOrganizerChanges:
            return
        self._organizer_pages = [
            dict(item, selected=False) for item in self._organizer_initial_snapshot
        ]
        self._reindex_organizer_pages()
        self.pagesChanged.emit()

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

        changed = False
        if shift_pressed:
            selected_indices = [
                i for i, p in enumerate(self._organizer_pages) if p["selected"]
            ]
            anchor = selected_indices[0] if selected_indices else 0
            low, high = min(anchor, item_index), max(anchor, item_index)
            for idx in range(low, high + 1):
                if not self._organizer_pages[idx]["selected"]:
                    self._organizer_pages[idx]["selected"] = True
                    changed = True
        elif ctrl_pressed:
            self._organizer_pages[item_index]["selected"] = not bool(
                self._organizer_pages[item_index]["selected"]
            )
            changed = True
        else:
            for idx, page in enumerate(self._organizer_pages):
                target_sel = idx == item_index
                if bool(page["selected"]) != target_sel:
                    page["selected"] = target_sel
                    changed = True

        if changed:
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

    @staticmethod
    def _default_page_annotation(page_index: int) -> dict[str, Any]:
        return {
            "strokes": [],
            "stamp": "APROBADO" if page_index == 0 else "",
            "stamp_rect": DEFAULT_STAMP_RECT,
            "image_path": "",
            "image_rect": DEFAULT_IMAGE_RECT,
            "image_aspect": DEFAULT_IMAGE_ASPECT,
        }

    @staticmethod
    def _clone_annotation(ann: dict[str, Any]) -> dict[str, Any]:
        return {
            "strokes": [
                {
                    "points": list(s["points"]),
                    "widthPt": float(s["widthPt"]),
                    "widthKey": str(s["widthKey"]),
                }
                for s in ann.get("strokes", [])
            ],
            "stamp": str(ann.get("stamp", "")),
            "stamp_rect": tuple(ann.get("stamp_rect", DEFAULT_STAMP_RECT)),
            "image_path": str(ann.get("image_path", "")),
            "image_rect": tuple(ann.get("image_rect", DEFAULT_IMAGE_RECT)),
            "image_aspect": float(ann.get("image_aspect", DEFAULT_IMAGE_ASPECT)),
        }

    @staticmethod
    def _annotations_equal(a: dict[str, Any], b: dict[str, Any]) -> bool:
        return (
            a.get("strokes") == b.get("strokes")
            and a.get("stamp") == b.get("stamp")
            and tuple(a.get("stamp_rect", DEFAULT_STAMP_RECT))
            == tuple(b.get("stamp_rect", DEFAULT_STAMP_RECT))
            and a.get("image_path") == b.get("image_path")
            and tuple(a.get("image_rect", DEFAULT_IMAGE_RECT))
            == tuple(b.get("image_rect", DEFAULT_IMAGE_RECT))
        )

    @staticmethod
    def _auto_fit_stamp_rect(ann: dict[str, Any], label_text: str) -> None:
        """Ajusta el ancho normalizado del marco del sello según la longitud del texto libre."""
        clean_len = len(label_text.strip())
        if clean_len == 0:
            return
        x0, y0, x1, y1 = ann.get("stamp_rect", DEFAULT_STAMP_RECT)
        cur_h = max(0.06, min(0.45, float(y1) - float(y0)))
        desired_w = max(0.18, min(0.90, 0.11 + clean_len * 0.021))
        cx = (float(x0) + float(x1)) * 0.5
        new_x0 = max(0.02, min(0.98 - desired_w, cx - desired_w * 0.5))
        new_x1 = min(0.98, new_x0 + desired_w)
        new_y1 = min(0.98, float(y0) + cur_h)
        new_y0 = max(0.02, new_y1 - cur_h)
        ann["stamp_rect"] = (
            round(new_x0, 4),
            round(new_y0, 4),
            round(new_x1, 4),
            round(new_y1, 4),
        )

    def _push_viewer_undo_state(
        self,
        page_index: int,
        previous_state: dict[str, Any],
        action_kind: str = "edit",
    ) -> None:
        self._viewer_undo_stack.append(
            {
                "page_index": int(page_index),
                "state": self._clone_annotation(previous_state),
                "kind": action_kind,
            }
        )
        if len(self._viewer_undo_stack) > MAX_VIEWER_UNDO_STEPS:
            del self._viewer_undo_stack[0]

    def _get_page_annotation(self, page_index: int) -> dict[str, Any]:
        """Obtiene o inicializa el estado de anotaciones (trazos, sello, firma PNG) por página."""
        if page_index not in self._page_annotations:
            self._page_annotations[page_index] = self._default_page_annotation(page_index)
        return self._page_annotations[page_index]

    @Property(bool, notify=viewerChanged)
    def canUndoViewer(self) -> bool:
        return len(self._viewer_undo_stack) > 0

    @Property(int, notify=viewerChanged)
    def viewerUndoCount(self) -> int:
        return len(self._viewer_undo_stack)

    @Property(bool, notify=viewerChanged)
    def hasViewerChanges(self) -> bool:
        if self._viewer_undo_stack:
            return True
        for p_idx, ann in self._page_annotations.items():
            if not self._annotations_equal(ann, self._default_page_annotation(p_idx)):
                return True
        return False

    @Slot()
    def captureViewerUndoCheckpoint(self) -> None:
        """Guarda instantánea previa antes de iniciar arrastre o edición continua."""
        ann = self._get_page_annotation(self._viewer_page_index)
        self._pending_undo_checkpoint = {
            "page_index": self._viewer_page_index,
            "state": self._clone_annotation(ann),
        }

    @Slot(str)
    def commitViewerUndoCheckpoint(self, action_kind: str = "edit") -> None:
        """Apila el checkpoint previo si el estado actual cambió tras finalizar el gesto."""
        cp = self._pending_undo_checkpoint
        self._pending_undo_checkpoint = None
        if cp is None:
            return
        p_idx = int(cp["page_index"])
        prev_state = cp["state"]
        curr_state = self._get_page_annotation(p_idx)
        if not self._annotations_equal(prev_state, curr_state):
            self._push_viewer_undo_state(p_idx, prev_state, action_kind=action_kind)
            self.viewerChanged.emit()

    @Slot(result=bool)
    def undoViewerAction(self) -> bool:
        """Deshace la última acción en Visor y Firma (trazo, sello, firma PNG o movimiento)."""
        self._pending_undo_checkpoint = None
        if not self._viewer_undo_stack:
            return False
        entry = self._viewer_undo_stack.pop()
        p_idx = int(entry["page_index"])
        self._page_annotations[p_idx] = self._clone_annotation(entry["state"])
        self._viewer_page_index = p_idx
        self._sync_current_page_viewer_state()
        self.viewerChanged.emit()
        return True

    @Slot()
    def restoreViewerOriginal(self) -> None:
        """Revierte todas las anotaciones del visor al estado inicial sin re-renderizar."""
        if not self.hasViewerChanges and not self._pending_undo_checkpoint:
            return
        self._page_annotations.clear()
        self._viewer_undo_stack.clear()
        self._pending_undo_checkpoint = None
        self._sync_current_page_viewer_state()
        self.viewerChanged.emit()

    def _sync_current_page_viewer_state(self) -> None:
        """Sincroniza los atributos rápidos de la página activa con el estado por página."""
        ann = self._get_page_annotation(self._viewer_page_index)
        self._signature_stamp = str(ann["stamp"])
        self._signature_image_path = str(ann["image_path"])
        self._freehand_strokes = [list(s["points"]) for s in ann["strokes"]]

    def _current_page_aspect_ratio(self) -> float:
        """Devuelve la relación de aspecto visual (ancho/alto) de la página actual del PDF primario."""
        valid_files = self._valid_queued_files()
        if not valid_files:
            return 595.0 / 842.0
        primary = valid_files[0]
        if primary.file_path.suffix.lower() != ".pdf" or primary.page_count < 1:
            return 595.0 / 842.0
        try:
            import pymupdf as fitz

            pwd = self._passwords.get(primary.file_path.resolve())
            with fitz.open(primary.file_path) as doc:
                if doc.needs_pass and pwd:
                    doc.authenticate(pwd)
                idx = max(0, min(doc.page_count - 1, self._viewer_page_index))
                rect = doc[idx].rect
                if rect.width > 1 and rect.height > 1:
                    return float(rect.width) / float(rect.height)
        except Exception:
            pass
        return 595.0 / 842.0

    @Property(bool, notify=viewerChanged)
    def viewerDrawMode(self) -> bool:
        return self._viewer_draw_mode

    @Slot(bool)
    def setViewerDrawMode(self, enabled: bool) -> None:
        if enabled != self._viewer_draw_mode:
            self._viewer_draw_mode = enabled
            self.viewerChanged.emit()

    @Property(str, notify=viewerChanged)
    def signatureStrokeWidthKey(self) -> str:
        return self._signature_stroke_width_key

    @Property(float, notify=viewerChanged)
    def signatureStrokeWidthPt(self) -> float:
        return float(
            STROKE_WIDTH_PT_MAP.get(
                self._signature_stroke_width_key,
                STROKE_WIDTH_PT_MAP[StrokeWidthPreset.FINE.value],
            )
        )

    @Slot(str)
    def setSignatureStrokeWidthKey(self, key: str) -> None:
        clean_key = key.strip().lower()
        if clean_key in STROKE_WIDTH_PT_MAP and clean_key != self._signature_stroke_width_key:
            self._signature_stroke_width_key = clean_key
            self.viewerChanged.emit()

    @Property(int, notify=viewerChanged)
    def viewerPageIndex(self) -> int:
        return self._viewer_page_index

    @Slot(int)
    def setViewerPageIndex(self, index: int) -> None:
        max_p = self.primaryDocumentPageCount
        if 0 <= index < max(1, max_p) and index != self._viewer_page_index:
            self._viewer_page_index = index
            self._sync_current_page_viewer_state()
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

    @Property(float, notify=viewerChanged)
    def viewerDevicePixelRatio(self) -> float:
        return self._viewer_dpr

    @Slot(float)
    def setViewerDevicePixelRatio(self, dpr: float) -> None:
        clamped = round(max(1.0, min(3.0, float(dpr))), 2)
        if clamped != self._viewer_dpr:
            self._viewer_dpr = clamped
            self.viewerChanged.emit()

    @Property(str, notify=viewerChanged)
    def currentViewerPageUrl(self) -> str:
        if not self._queued_files:
            return ""
        primary = self._queued_files[0]
        if primary.file_path.suffix.lower() != ".pdf" or primary.page_count < 1:
            return ""
        encoded = quote(str(primary.file_path.resolve()))
        real_dpi = max(72, min(360, int(round(144.0 * self._viewer_zoom * self._viewer_dpr))))
        return f"image://pdfpage/{self._viewer_page_index}?path={encoded}&dpi={real_dpi}"

    @Property(str, notify=viewerChanged)
    def initialSignatureDialogFolderUrl(self) -> str:
        """Carpeta inicial razonable para el FileDialog de Firma PNG."""
        if self._queued_files:
            parent = self._queued_files[0].file_path.parent
            if parent.exists():
                return QUrl.fromLocalFile(str(parent.resolve())).toString()
        if self._output_directory and Path(self._output_directory).exists():
            return QUrl.fromLocalFile(str(Path(self._output_directory).resolve())).toString()
        return QUrl.fromLocalFile(str(Path.home())).toString()

    @Property(str, notify=viewerChanged)
    def signatureStamp(self) -> str:
        ann = self._get_page_annotation(self._viewer_page_index)
        return str(ann["stamp"])

    @Slot(str)
    def setSignatureStamp(self, label: str) -> None:
        cleaned = "" if label.strip().upper() in {"", "SIN SELLO", "NINGUNO"} else label.strip()
        ann = self._get_page_annotation(self._viewer_page_index)
        if cleaned != ann["stamp"] or cleaned != self._signature_stamp:
            self._push_viewer_undo_state(self._viewer_page_index, ann, action_kind="stamp")
            ann["stamp"] = cleaned
            if cleaned:
                self._auto_fit_stamp_rect(ann, cleaned)
            self._signature_stamp = cleaned
            self.viewerChanged.emit()

    @Slot(str)
    def setSignatureStampLive(self, label: str) -> None:
        """Actualiza el texto libre del sello en tiempo real sin apilar undo por cada tecla."""
        raw = str(label)
        next_val = "" if not raw.strip() else raw
        ann = self._get_page_annotation(self._viewer_page_index)
        if next_val != ann["stamp"] or next_val != self._signature_stamp:
            ann["stamp"] = next_val
            if next_val.strip():
                self._auto_fit_stamp_rect(ann, next_val)
            self._signature_stamp = next_val
            self.viewerChanged.emit()

    @Slot()
    def clearSignatureStamp(self) -> None:
        """Desactiva y oculta cualquier sello dejando solo la firma."""
        self.setSignatureStamp("")

    @Property("QVariantMap", notify=viewerChanged)
    def signatureStampRect(self) -> dict[str, float]:
        ann = self._get_page_annotation(self._viewer_page_index)
        x0, y0, x1, y1 = ann["stamp_rect"]
        return {
            "x": float(x0),
            "y": float(y0),
            "width": float(max(0.05, x1 - x0)),
            "height": float(max(0.04, y1 - y0)),
        }

    @Slot(float, float, float, float)
    def setSignatureStampRect(self, x: float, y: float, width: float, height: float) -> None:
        w = max(0.08, min(0.95, float(width)))
        h = max(0.04, min(0.60, float(height)))
        x0 = max(0.0, min(1.0 - w, float(x)))
        y0 = max(0.0, min(1.0 - h, float(y)))
        ann = self._get_page_annotation(self._viewer_page_index)
        new_rect = (round(x0, 4), round(y0, 4), round(x0 + w, 4), round(y0 + h, 4))
        if new_rect != ann["stamp_rect"]:
            ann["stamp_rect"] = new_rect
            self.viewerChanged.emit()

    @Property(str, notify=viewerChanged)
    def signatureImagePath(self) -> str:
        ann = self._get_page_annotation(self._viewer_page_index)
        return str(ann["image_path"])

    @Property(str, notify=viewerChanged)
    def signatureImageUrl(self) -> str:
        img_p = self.signatureImagePath
        if not img_p:
            return ""
        return QUrl.fromLocalFile(str(Path(img_p).resolve())).toString()

    @Property("QVariantMap", notify=viewerChanged)
    def signatureImageRect(self) -> dict[str, float]:
        ann = self._get_page_annotation(self._viewer_page_index)
        x0, y0, x1, y1 = ann["image_rect"]
        return {
            "x": float(x0),
            "y": float(y0),
            "width": float(max(0.04, x1 - x0)),
            "height": float(max(0.02, y1 - y0)),
            "aspect": float(ann.get("image_aspect", 2.2)),
        }

    @Slot(float, float, float, float)
    def setSignatureImageRect(
        self, x: float, y: float, width: float, height: float
    ) -> None:
        """Actualiza la posición o tamaño normalizados (0..1) de la firma PNG en la página actual."""
        w = max(0.05, min(0.95, float(width)))
        h = max(0.02, min(0.95, float(height)))
        x0 = max(0.0, min(1.0 - w, float(x)))
        y0 = max(0.0, min(1.0 - h, float(y)))
        ann = self._get_page_annotation(self._viewer_page_index)
        new_rect = (round(x0, 4), round(y0, 4), round(x0 + w, 4), round(y0 + h, 4))
        if new_rect != ann["image_rect"]:
            ann["image_rect"] = new_rect
            self.viewerChanged.emit()

    @Slot()
    def clearSignatureImage(self) -> None:
        """Quita la imagen PNG de firma de la página actual."""
        ann = self._get_page_annotation(self._viewer_page_index)
        if ann["image_path"] or self._signature_image_path:
            self._push_viewer_undo_state(
                self._viewer_page_index, ann, action_kind="image_remove"
            )
            ann["image_path"] = ""
            self._signature_image_path = ""
            self.viewerChanged.emit()

    @Slot(str)
    def setSignatureImagePath(self, path_or_url: str) -> None:
        """Valida, escala si es necesario y coloca una imagen PNG transparente en la página actual."""
        if not path_or_url or not str(path_or_url).strip():
            # Cancelar el diálogo no debe producir ningún error ni cambiar el estado.
            return

        raw = str(path_or_url)
        if raw.lstrip().startswith("file:"):
            clean = QUrl(raw.strip()).toLocalFile()
        else:
            clean = raw.strip()

        if not clean:
            return

        img_path = Path(clean)
        if not img_path.exists() or not img_path.is_file():
            self._emit_error(f"No se encontró el archivo de imagen: '{img_path.name}'.")
            return

        ext = img_path.suffix.lower()
        if ext != ".png":
            self._emit_error(
                f"Formato no soportado ('{ext or 'sin extensión'}'). Por favor elige una imagen PNG."
            )
            return

        try:
            file_size = img_path.stat().st_size
        except OSError:
            self._emit_error(f"No se pudo leer el archivo PNG '{img_path.name}'.")
            return

        if file_size == 0:
            self._emit_error(f"El archivo PNG '{img_path.name}' está vacío (0 bytes).")
            return

        qimg = QImage(str(img_path))
        if qimg.isNull() or qimg.width() < 1 or qimg.height() < 1:
            self._emit_error(
                f"El archivo PNG '{img_path.name}' está dañado o no es una imagen válida."
            )
            return

        rgba_img = qimg.convertToFormat(QImage.Format.Format_RGBA8888)
        alpha_view = memoryview(rgba_img.constBits())[3::4]
        if not any(alpha_view):
            self._emit_error(
                f"La imagen PNG '{img_path.name}' es 100% transparente y no contiene trazos visibles."
            )
            return

        effective_path = img_path
        orig_w = qimg.width()
        orig_h = qimg.height()

        if orig_w > 4000 or orig_h > 4000 or file_size > 10 * 1024 * 1024:
            scaled_qimg = qimg.scaled(
                2400,
                2400,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
            temp_dir = Path(tempfile.gettempdir()) / "coquette_pdf_signatures"
            temp_dir.mkdir(parents=True, exist_ok=True)
            scaled_dest = temp_dir / f"sig_scaled_{img_path.stem}_{orig_w}x{orig_h}.png"
            if scaled_qimg.save(str(scaled_dest), "PNG"):
                effective_path = scaled_dest
                orig_w = scaled_qimg.width()
                orig_h = scaled_qimg.height()
            self._emit_notice(
                f"Imagen PNG grande ({qimg.width()}×{qimg.height()} px) escalada automáticamente para mantener fluidez.",
                is_error=False,
            )

        img_aspect = float(orig_w) / float(max(1, orig_h))
        page_aspect = self._current_page_aspect_ratio()

        # Ancho inicial ~25% del ancho de página manteniendo la proporción real del PNG
        norm_w = 0.25
        norm_h = (norm_w * page_aspect) / max(0.05, img_aspect)
        if norm_h > 0.50:
            norm_h = 0.50
            norm_w = min(0.80, (norm_h * img_aspect) / max(0.05, page_aspect))
        elif norm_h < 0.03:
            norm_h = 0.03

        x0 = round(max(0.0, min(1.0 - norm_w, 0.5 - norm_w / 2.0)), 4)
        y0 = round(max(0.0, min(1.0 - norm_h, 0.5 - norm_h / 2.0)), 4)
        x1 = round(min(1.0, x0 + norm_w), 4)
        y1 = round(min(1.0, y0 + norm_h), 4)

        ann = self._get_page_annotation(self._viewer_page_index)
        self._push_viewer_undo_state(self._viewer_page_index, ann, action_kind="image_add")
        ann["image_path"] = str(effective_path)
        ann["image_rect"] = (x0, y0, x1, y1)
        ann["image_aspect"] = round(img_aspect, 4)
        self._signature_image_path = str(effective_path)
        self.viewerChanged.emit()

    @Property("QVariantList", notify=viewerChanged)
    def currentPageStrokes(self) -> list[dict[str, Any]]:
        """Devuelve los trazos vectoriales registrados en la página activa con su grosor."""
        ann = self._get_page_annotation(self._viewer_page_index)
        result: list[dict[str, Any]] = []
        for s in ann["strokes"]:
            result.append(
                {
                    "points": [{"x": float(px), "y": float(py)} for px, py in s["points"]],
                    "widthPt": float(s["widthPt"]),
                    "widthKey": str(s["widthKey"]),
                }
            )
        return result

    @Slot("QVariantList")
    def addFreehandStroke(self, normalized_points: list[Any]) -> None:
        """Registra un trazo libre de firma (lista de puntos {x, y} normalizados 0..1) en la página activa."""
        stroke: list[tuple[float, float]] = []
        for pt in normalized_points:
            if isinstance(pt, dict) and "x" in pt and "y" in pt:
                stroke.append((float(pt["x"]), float(pt["y"])))
            elif isinstance(pt, (list, tuple)) and len(pt) >= 2:
                stroke.append((float(pt[0]), float(pt[1])))
        if len(stroke) >= 2:
            ann = self._get_page_annotation(self._viewer_page_index)
            self._push_viewer_undo_state(
                self._viewer_page_index, ann, action_kind="stroke"
            )
            ann["strokes"].append(
                {
                    "points": stroke,
                    "widthPt": self.signatureStrokeWidthPt,
                    "widthKey": self._signature_stroke_width_key,
                }
            )
            self._sync_current_page_viewer_state()
            self.viewerChanged.emit()

    @Slot()
    def clearFreehandStrokes(self) -> None:
        ann = self._get_page_annotation(self._viewer_page_index)
        if ann["strokes"]:
            self._push_viewer_undo_state(
                self._viewer_page_index, ann, action_kind="clear_strokes"
            )
            ann["strokes"].clear()
            self._sync_current_page_viewer_state()
            self.viewerChanged.emit()

    @Property(int, notify=viewerChanged)
    def freehandStrokeCount(self) -> int:
        ann = self._get_page_annotation(self._viewer_page_index)
        return len(ann["strokes"])

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
        ok, msg, indices = validate_page_ranges_realtime(self._range_expr, max_pages)
        self._range_valid = ok
        self._range_feedback = msg
        self._split_selected_indices = set(indices) if ok else set()

    @Property("QVariantList", notify=configChanged)
    def splitPages(self) -> list[dict[str, Any]]:
        """Miniaturas de páginas del PDF principal para selección visual en Dividir y Extraer."""
        valid_files = self._valid_queued_files()
        if not valid_files:
            return []
        primary = next(
            (qf for qf in valid_files if qf.file_path.suffix.lower() in SUPPORTED_PDF_EXTENSIONS),
            valid_files[0],
        )
        if primary.page_count < 1 or primary.file_path.suffix.lower() != ".pdf":
            return []
        encoded_path = quote(str(primary.file_path.resolve()))
        return [
            {
                "pageIndex": idx,
                "pageNumber": idx + 1,
                "selected": idx in self._split_selected_indices,
                "thumbnailUrl": f"image://pdfpage/{idx}?path={encoded_path}&dpi=72",
            }
            for idx in range(primary.page_count)
        ]

    @Property(int, notify=configChanged)
    def splitSelectedCount(self) -> int:
        max_pages = self.primaryDocumentPageCount
        if max_pages <= 0:
            return 0
        return sum(1 for idx in self._split_selected_indices if 0 <= idx < max_pages)

    @Slot(int)
    def toggleSplitPage(self, page_index: int) -> None:
        """Alterna la selección de una hoja en Dividir y Extraer y sincroniza el rango."""
        max_pages = self.primaryDocumentPageCount
        if page_index < 0 or page_index >= max_pages:
            return
        if page_index in self._split_selected_indices:
            self._split_selected_indices.remove(page_index)
        else:
            self._split_selected_indices.add(page_index)
        self._range_expr = format_page_ranges(sorted(self._split_selected_indices))
        self._revalidate_range()
        self.configChanged.emit()

    @Slot()
    def selectAllSplitPages(self) -> None:
        """Selecciona todas las páginas del documento principal en Dividir y Extraer."""
        max_pages = self.primaryDocumentPageCount
        if max_pages <= 0:
            return
        self._split_selected_indices = set(range(max_pages))
        self._range_expr = format_page_ranges(list(range(max_pages)))
        self._revalidate_range()
        self.configChanged.emit()

    @Slot()
    def clearSplitSelection(self) -> None:
        """Limpia la selección visual de páginas y vacía el rango en Dividir y Extraer."""
        self._split_selected_indices.clear()
        self._range_expr = ""
        self._revalidate_range()
        self.configChanged.emit()

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
        } and (level != self._compression_level or self._is_target_size_mode):
            self._compression_level = level
            self._is_target_size_mode = False
            self.configChanged.emit()

    @Property(bool, notify=configChanged)
    def isTargetSizeMode(self) -> bool:
        return self._is_target_size_mode

    @Slot(bool)
    def setTargetSizeMode(self, enabled: bool) -> None:
        val = bool(enabled)
        if val != self._is_target_size_mode:
            self._is_target_size_mode = val
            self.configChanged.emit()

    @Property(float, notify=configChanged)
    def targetSizeMb(self) -> float:
        return self._target_size_mb

    @Property(str, notify=configChanged)
    def targetSizeText(self) -> str:
        return self._target_size_text

    @Property(bool, notify=configChanged)
    def isTargetSizeValid(self) -> bool:
        return self._target_size_valid

    @Property(str, notify=configChanged)
    def targetSizeFeedback(self) -> str:
        return self._target_size_feedback

    @Property("QVariantList", constant=True)
    def targetSizePresets(self) -> list[int]:
        return [int(p) for p in TARGET_SIZE_PRESETS_MB]

    def _update_target_size_from_text(self, raw_text: str) -> None:
        normalized = str(raw_text).strip().replace(",", ".")
        if not normalized:
            self._target_size_valid = False
            self._target_size_feedback = (
                f"Ingresa un límite entre {TARGET_SIZE_MIN_MB:.1f} y {TARGET_SIZE_MAX_MB:.0f} MB."
            )
            return
        try:
            val = float(normalized)
        except ValueError:
            self._target_size_valid = False
            self._target_size_feedback = "Ingresa un valor numérico válido en MB."
            return
        if val < TARGET_SIZE_MIN_MB or val > TARGET_SIZE_MAX_MB:
            self._target_size_valid = False
            self._target_size_feedback = (
                f"El rango seguro es de {TARGET_SIZE_MIN_MB:.1f} a {TARGET_SIZE_MAX_MB:.0f} MB."
            )
            return
        self._target_size_mb = round(val, 2)
        self._target_size_valid = True
        eff_mb = (
            self._target_size_mb * DECIMAL_MB_BYTES * TARGET_SIZE_SAFETY_FACTOR
        ) / float(DECIMAL_MB_BYTES)
        self._target_size_feedback = (
            f"Límite efectivo: {eff_mb:.2f} MB (95% de seguridad)"
        )

    @Slot(str)
    def setTargetSizeText(self, text: str) -> None:
        raw = str(text)
        self._target_size_text = raw
        self._update_target_size_from_text(raw)
        if not self._is_target_size_mode:
            self._is_target_size_mode = True
        self.configChanged.emit()

    @Slot(float)
    def setTargetSizeMb(self, mb: float) -> None:
        val = float(mb)
        text = str(int(val)) if abs(val - round(val)) < 1e-6 else f"{val:g}"
        self._target_size_text = text
        self._update_target_size_from_text(text)
        if not self._is_target_size_mode:
            self._is_target_size_mode = True
        self.configChanged.emit()

    @Property(str, notify=configChanged)
    def targetWeightAnatomyNotice(self) -> str:
        pdf_files = self._queued_valid_pdf_files()
        if not pdf_files or self._is_estimating_compression:
            return ""
        target_bytes = (
            int(
                self._target_size_mb
                * DECIMAL_MB_BYTES
                * TARGET_SIZE_SAFETY_FACTOR
            )
            if self._target_size_valid
            else 0
        )
        if len(pdf_files) == 1:
            ck = self._file_cache_key(pdf_files[0].file_path)
            anat = self._target_anatomy_cache.get(ck) if ck is not None else None
            if anat is None:
                return ""
            if target_bytes > 0 and int(anat.get("originalBytes", 0)) <= target_bytes:
                return "Este archivo ya cumple el límite (no se modificará ni duplicará)."
            return str(anat.get("advisoryMessage", ""))

        for qf in pdf_files:
            ck = self._file_cache_key(qf.file_path)
            anat = self._target_anatomy_cache.get(ck) if ck is not None else None
            if anat and anat.get("isTextHeavy"):
                return (
                    "Uno o más PDFs son principalmente texto/vectores: "
                    "el ahorro de peso será limitado."
                )
        return ""

    @Property(str, notify=progressChanged)
    def lastCompressionComparison(self) -> str:
        return self._last_compression_comparison

    @Property(str, notify=progressChanged)
    def lastCompressionQualityLabel(self) -> str:
        return self._last_compression_quality_label

    @Property(str, notify=progressChanged)
    def lastCompressionPreviewUrl(self) -> str:
        return self._last_compression_preview_url

    @Property(bool, notify=progressChanged)
    def hasDifficultTargetResult(self) -> bool:
        return self._difficult_target_context is not None

    @Property(str, notify=progressChanged)
    def difficultTargetSummary(self) -> str:
        if self._difficult_target_context is None:
            return ""
        res = self._difficult_target_context["result"]
        return str(res.message)

    @Property(str, notify=progressChanged)
    def difficultTargetAdvisory(self) -> str:
        if self._difficult_target_context is None:
            return ""
        res = self._difficult_target_context["result"]
        return str(res.anatomy.advisory_message)

    @Slot()
    def dismissDifficultTargetResult(self) -> None:
        """Descarta la tarjeta de caso difícil y libera los bytes en RAM del mejor intento."""
        if self._difficult_target_context is not None:
            res = self._difficult_target_context.get("result")
            if res is not None:
                res.best_pdf_bytes = None
            self._difficult_target_context = None
            self.progressChanged.emit()

    @Slot()
    def openResultInViewer(self) -> None:
        """Abre el PDF comprimido generado dentro de Visor y Firma para comprobar su lectura."""
        raw = (self._last_output_file_path or self._last_output_file or "").strip()
        if not raw:
            return
        out_path = Path(raw)
        if not out_path.exists() or out_path.suffix.lower() != ".pdf":
            self._emit_error("No se encontró el PDF generado para previsualizar.")
            return
        self.clearFiles()
        self.addSingleFilePath(str(out_path))
        self.selectTool(ToolType.SIGN.value)

    def _file_cache_key(self, file_path: Path) -> tuple[str, int, int] | None:
        try:
            resolved = file_path.resolve()
            st = resolved.stat()
            return (str(resolved), int(st.st_mtime_ns), int(st.st_size))
        except OSError:
            return None

    def _queued_valid_pdf_files(self) -> list[QueuedFile]:
        return [
            qf
            for qf in self._valid_queued_files()
            if qf.file_path.suffix.lower() in SUPPORTED_PDF_EXTENSIONS
        ]

    @staticmethod
    def _estimate_batch_task(
        items: list[tuple[tuple[str, int, int], Path, str | None]],
        on_progress: Any = None,
        is_cancelled: Any = None,
    ) -> tuple[
        dict[tuple[str, int, int], dict[str, dict[str, float | int | bool]]],
        dict[tuple[str, int, int], dict[str, Any]],
    ]:
        """Calcula la estimación real basada en muestra y la anatomía de peso en un hilo QRunnable."""
        pdf_engine = _pdf_engine_module().PDFEngine
        results: dict[tuple[str, int, int], dict[str, dict[str, float | int | bool]]] = {}
        anatomies: dict[tuple[str, int, int], dict[str, Any]] = {}
        for cache_key, path, pwd in items:
            if is_cancelled is not None and is_cancelled():
                raise TaskCancelledError("Cálculo de estimación cancelado.")
            try:
                est = pdf_engine.estimate_pdf_compression_for_all_levels(
                    path, password=pwd, is_cancelled=is_cancelled
                )
                results[cache_key] = est
            except TaskCancelledError:
                raise
            except Exception:
                size_b = cache_key[2]
                results[cache_key] = {
                    lvl.value: {
                        "originalBytes": size_b,
                        "estimatedBytes": size_b,
                        "savedPct": 0.0,
                        "alreadyLight": True,
                    }
                    for lvl in CompressionLevel
                }
            try:
                anat = pdf_engine.analyze_pdf_weight_anatomy(
                    path, password=pwd, is_cancelled=is_cancelled
                )
                anatomies[cache_key] = {
                    "originalBytes": anat.original_bytes,
                    "imageBytes": anat.image_bytes,
                    "imageRatio": anat.image_ratio,
                    "isTextHeavy": anat.is_text_heavy,
                    "isSingleLargeImage": anat.is_single_large_image,
                    "advisoryMessage": anat.advisory_message,
                }
            except TaskCancelledError:
                raise
            except Exception:
                anatomies[cache_key] = {
                    "originalBytes": cache_key[2],
                    "imageBytes": 0,
                    "imageRatio": 0.0,
                    "isTextHeavy": False,
                    "isSingleLargeImage": False,
                    "advisoryMessage": "",
                }
        return results, anatomies

    def _schedule_compression_estimation(self) -> None:
        """Lanza o reutiliza en caché la estimación asíncrona de compresión y cancela cálculos obsoletos."""
        self._estimate_generation_id += 1
        gen_id = self._estimate_generation_id
        if self._active_estimate_worker is not None:
            self._active_estimate_worker.cancel()
            self._active_estimate_worker = None

        if self._active_tool != ToolType.COMPRESS.value:
            if self._is_estimating_compression:
                self._is_estimating_compression = False
            self.configChanged.emit()
            return

        pdf_files = self._queued_valid_pdf_files()
        if not pdf_files:
            if self._is_estimating_compression:
                self._is_estimating_compression = False
            self.configChanged.emit()
            return

        missing_items: list[tuple[tuple[str, int, int], Path, str | None]] = []
        for qf in pdf_files:
            ck = self._file_cache_key(qf.file_path)
            if ck is None:
                continue
            if (
                ck not in self._compression_estimate_cache
                or ck not in self._target_anatomy_cache
            ):
                pwd = self._passwords.get(qf.file_path.resolve())
                missing_items.append((ck, qf.file_path, pwd))

        if not missing_items:
            self._is_estimating_compression = False
            self.configChanged.emit()
            return

        self._is_estimating_compression = True
        self.configChanged.emit()

        worker = PDFOperationWorker(self._estimate_batch_task, missing_items)
        self._active_estimate_worker = worker

        def _on_est_finished(
            res: Any,
            expected_gen: int = gen_id,
        ) -> None:
            if isinstance(res, tuple) and len(res) == 2:
                est_map, anat_map = res
                if isinstance(est_map, dict):
                    self._compression_estimate_cache.update(est_map)
                if isinstance(anat_map, dict):
                    self._target_anatomy_cache.update(anat_map)
            elif isinstance(res, dict):
                self._compression_estimate_cache.update(res)
            if expected_gen == self._estimate_generation_id:
                self._is_estimating_compression = False
                self._active_estimate_worker = None
                self.configChanged.emit()

        def _on_est_stopped(
            _msg: str = "",
            expected_gen: int = gen_id,
        ) -> None:
            if expected_gen == self._estimate_generation_id:
                self._is_estimating_compression = False
                self._active_estimate_worker = None
                self.configChanged.emit()

        worker.signals.finished.connect(_on_est_finished)
        worker.signals.cancelled.connect(_on_est_stopped)
        worker.signals.error.connect(_on_est_stopped)
        self.task_manager.pool.start(worker)

    def _aggregate_compression_estimates(
        self,
    ) -> dict[str, dict[str, float | int | bool]] | None:
        """Suma las estimaciones en caché para todos los PDFs válidos en cola."""
        pdf_files = self._queued_valid_pdf_files()
        if not pdf_files:
            return None

        totals: dict[str, dict[str, int]] = {
            lvl.value: {"orig": 0, "est": 0} for lvl in CompressionLevel
        }
        for qf in pdf_files:
            ck = self._file_cache_key(qf.file_path)
            if ck is None or ck not in self._compression_estimate_cache:
                return None
            per_file = self._compression_estimate_cache[ck]
            for lvl in CompressionLevel:
                entry = per_file.get(lvl.value, {})
                totals[lvl.value]["orig"] += int(
                    entry.get("originalBytes", qf.original_size_bytes)
                )
                totals[lvl.value]["est"] += int(
                    entry.get("estimatedBytes", qf.original_size_bytes)
                )

        ext_orig = max(1, totals[CompressionLevel.EXTREME.value]["orig"])
        ext_est = totals[CompressionLevel.EXTREME.value]["est"]
        max_pct = max(0.0, ((ext_orig - ext_est) / float(ext_orig)) * 100.0)
        already_light_all = max_pct < 5.0

        agg: dict[str, dict[str, float | int | bool]] = {}
        for lvl in CompressionLevel:
            orig_b = totals[lvl.value]["orig"]
            est_b = totals[lvl.value]["est"]
            pct = (
                max(0.0, ((orig_b - est_b) / float(orig_b)) * 100.0)
                if orig_b > 0
                else 0.0
            )
            agg[lvl.value] = {
                "originalBytes": orig_b,
                "estimatedBytes": est_b,
                "savedPct": round(pct, 1),
                "alreadyLight": already_light_all or pct < 5.0 or (orig_b - est_b) < 2048,
            }
        return agg

    @Property(bool, notify=configChanged)
    def isEstimatingCompression(self) -> bool:
        return self._is_estimating_compression

    @Property("QVariantList", notify=configChanged)
    def compressionLevelOptions(self) -> list[dict[str, Any]]:
        """Opciones de nivel de compresión con porcentajes calculados por archivo (nunca fijos)."""
        agg = self._aggregate_compression_estimates()
        base_labels = [
            (CompressionLevel.EXTREME.value, "Extrema"),
            (CompressionLevel.RECOMMENDED.value, "Recomendada"),
            (CompressionLevel.LOW_LOSS.value, "Baja pérdida"),
        ]
        if agg is None or self._is_estimating_compression:
            return [
                {
                    "key": key,
                    "label": f"{title} (...)",
                    "savedPct": 0.0,
                }
                for key, title in base_labels
            ]

        options: list[dict[str, Any]] = []
        for key, title in base_labels:
            pct = float(agg[key]["savedPct"])
            pct_int = int(round(pct))
            options.append(
                {
                    "key": key,
                    "label": f"{title} (~{pct_int}%)",
                    "savedPct": pct,
                }
            )
        return options

    @Property(str, notify=configChanged)
    def estimatedCompressionSummary(self) -> str:
        pdf_files = self._queued_valid_pdf_files()
        if not pdf_files:
            return "Agrega un pliego PDF para calcular la reducción real."
        if self._is_target_size_mode:
            if not self._target_size_valid:
                return self._target_size_feedback
            anat_notice = self.targetWeightAnatomyNotice
            if anat_notice:
                return f"{self._target_size_feedback} · {anat_notice}"
            return self._target_size_feedback
        agg = self._aggregate_compression_estimates()
        if agg is None or self._is_estimating_compression:
            return "Calculando..."

        entry = agg.get(
            self._compression_level,
            agg[CompressionLevel.RECOMMENDED.value],
        )
        orig_b = int(entry["originalBytes"])
        est_b = int(entry["estimatedBytes"])
        pct = float(entry["savedPct"])
        already_light = bool(entry["alreadyLight"])

        summary = (
            f"Reducción estimada ~{pct:.0f}% (de {_format_bytes(orig_b)} a ~{_format_bytes(est_b)})"
        )
        if already_light:
            return f"Este pliego ya está muy ligero · {summary}"
        return summary

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

    # --- Nombre editable del archivo de salida ---

    def _output_target_spec(self) -> tuple[str, str]:
        """Devuelve (nombre_sugerido_sin_extension, extension) según la herramienta y cola activa."""
        valid_files = self._valid_queued_files()
        if not valid_files:
            return ("", ".pdf")

        primary_file = valid_files[0].file_path
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
        word_paths = [
            qf.file_path
            for qf in valid_files
            if qf.file_path.suffix.lower() in SUPPORTED_WORD_EXTENSIONS
        ]
        tool = self._active_tool

        if tool == ToolType.MERGE.value:
            suffix = "_integrado" if (img_paths or word_paths) else "_unido"
            return (f"{primary_file.stem}{suffix}", ".pdf")
        if tool == ToolType.WORD_TO_PDF.value:
            target = word_paths[0] if word_paths else primary_file
            return (target.stem, ".pdf")
        if tool == ToolType.SPLIT.value:
            target = pdf_paths[0] if pdf_paths else primary_file
            return (f"{target.stem}_extraido", ".pdf")
        if tool == ToolType.ORGANIZE.value:
            target = pdf_paths[0] if pdf_paths else primary_file
            return (f"{target.stem}_organizado", ".pdf")
        if tool == ToolType.COMPRESS.value:
            target = pdf_paths[0] if pdf_paths else primary_file
            return (f"{target.stem}_comprimido", ".pdf")
        if tool == ToolType.PDF_TO_IMAGES.value:
            target = pdf_paths[0] if pdf_paths else primary_file
            return (f"{target.stem}_imagenes", "")
        if tool == ToolType.IMAGES_TO_PDF.value:
            target = img_paths[0] if img_paths else primary_file
            return (f"{target.stem}_album", ".pdf")
        if tool == ToolType.WATERMARK.value:
            target = pdf_paths[0] if pdf_paths else primary_file
            return (f"{target.stem}_marca_agua", ".pdf")
        if tool == ToolType.SIGN.value:
            target = pdf_paths[0] if pdf_paths else primary_file
            return (f"{target.stem}_firmado", ".pdf")
        if tool == ToolType.PROTECT.value:
            target = pdf_paths[0] if pdf_paths else primary_file
            return (f"{target.stem}_protegido", ".pdf")
        if tool == ToolType.UNLOCK.value:
            target = pdf_paths[0] if pdf_paths else primary_file
            return (f"{target.stem}_desbloqueado", ".pdf")
        return (f"{primary_file.stem}_modificado", ".pdf")

    def _resolve_effective_output_stem(self, fallback_stem: str, ext: str) -> str:
        """Devuelve el nombre base efectivo sanitizado o el sugerido si no fue editado."""
        if not self._output_name_user_edited:
            return sanitize_windows_filename(
                fallback_stem, fallback=fallback_stem, extension=ext
            )
        return sanitize_windows_filename(
            self._custom_output_name,
            fallback=fallback_stem,
            extension=ext,
        )

    @Property(str, notify=configChanged)
    def suggestedOutputName(self) -> str:
        suggested, _ = self._output_target_spec()
        return suggested

    @Property(str, notify=configChanged)
    def outputFileName(self) -> str:
        if self._output_name_user_edited:
            return self._custom_output_name
        return self.suggestedOutputName

    @Property(str, notify=configChanged)
    def outputFileExtension(self) -> str:
        _, ext = self._output_target_spec()
        return ext

    @Property(bool, notify=configChanged)
    def isOutputNameCustomized(self) -> bool:
        return self._output_name_user_edited

    @Property(bool, notify=configChanged)
    def isBatchMultiFileOutput(self) -> bool:
        return (
            (
                self._active_tool
                in {
                    ToolType.COMPRESS.value,
                    ToolType.PDF_TO_IMAGES.value,
                    ToolType.WATERMARK.value,
                }
                and self.pdfCount > 1
            )
            or (self._active_tool == ToolType.WORD_TO_PDF.value and self.wordCount > 1)
        )

    @Slot(str)
    def setOutputFileName(self, name: str) -> None:
        """Actualiza el borrador del nombre personalizado mientras el usuario edita."""
        raw = str(name)
        if not self._output_name_user_edited and raw == self.suggestedOutputName:
            return
        if raw != self._custom_output_name or not self._output_name_user_edited:
            self._custom_output_name = raw
            self._output_name_user_edited = True
            self.configChanged.emit()

    @Slot(result=str)
    def commitOutputFileName(self) -> str:
        """Sanitiza el nombre de salida y revierte al sugerido si queda vacío o inválido."""
        suggested, ext = self._output_target_spec()
        if not self._output_name_user_edited:
            return suggested
        cleaned = clean_windows_filename_stem(self._custom_output_name, extension=ext)
        if not cleaned or cleaned == suggested:
            self._custom_output_name = ""
            self._output_name_user_edited = False
            self.configChanged.emit()
            return suggested
        if cleaned != self._custom_output_name:
            self._custom_output_name = cleaned
            self.configChanged.emit()
        return cleaned

    @Slot()
    def resetOutputFileName(self) -> None:
        """Restaura el nombre de salida al valor automático sugerido."""
        if self._output_name_user_edited or self._custom_output_name:
            self._custom_output_name = ""
            self._output_name_user_edited = False
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
    def lastOutputFilePath(self) -> str:
        """Ruta absoluta normalizada del último archivo generado, independiente de la cola."""
        return self._last_output_file_path

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

        if self._output_name_user_edited:
            self.commitOutputFileName()

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
        self._pending_target_request = None
        self._pending_rescue_preview = False
        try:
            worker = self._build_worker_for_tool(
                tool, primary_file, primary_pwd, out_dir
            )
        except PDFStudioError as exc:
            self._has_processing_error = True
            self._status_message = str(exc)
            self._emit_error(str(exc))
            return

        self._start_worker(worker)

    def _start_worker(
        self,
        worker: PDFOperationWorker,
        initial_status: str = "Iniciando tarea en segundo plano...",
    ) -> None:
        """Conecta señales y lanza un PDFOperationWorker en el pool con estado ocupado."""
        self._has_processing_error = False
        self._is_busy = True
        self._progress_percent = 5
        self._status_message = initial_status
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
        """Une e integra archivos PDF, documentos Word (.docx/.doc) e imágenes en un único PDF."""
        import pymupdf as fitz

        passwords = passwords or {}
        total_original_bytes = 0
        total_files = len(input_files)
        merged_doc = fitz.open()
        try:
            with tempfile.TemporaryDirectory(prefix="floral_word_merge_") as temp_dir_str:
                temp_dir = Path(temp_dir_str)
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
                    elif ext in SUPPORTED_WORD_EXTENSIONS:
                        temp_pdf = temp_dir / f"word_{idx}_{path.stem}.pdf"
                        convert_word_to_pdf(
                            path,
                            temp_pdf,
                            is_cancelled=is_cancelled,
                        )
                        word_pdf = fitz.open(temp_pdf)
                        try:
                            merged_doc.insert_pdf(word_pdf)
                        finally:
                            word_pdf.close()
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

            safe_dest = _pdf_engine_module().ensure_safe_output_path(
                Path(input_files[0]), output_path, default_suffix="_integrado"
            )
            merged_doc.save(str(safe_dest), deflate=True)
            if on_progress is not None:
                on_progress(100, "Documentos integrados en un PDF.")
            final_bytes = safe_dest.stat().st_size
            return OperationResult(
                tool=ToolType.MERGE,
                output_files=[safe_dest],
                original_size_bytes=total_original_bytes,
                final_size_bytes=final_bytes,
                saved_percentage=0.0,
                message=f"Se integraron {total_files} archivos en '{safe_dest.name}'.",
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
        custom_base_name: str = "",
        on_progress: Any = None,
        is_cancelled: Any = None,
    ) -> OperationResult:
        """Ejecuta compresión, exportación a imágenes o marca de agua sobre un lote de PDFs."""
        pe_mod = _pdf_engine_module()
        pdf_engine = pe_mod.PDFEngine
        clean_custom = clean_windows_filename_stem(custom_base_name, extension=".pdf")
        protected_set = {Path(p).resolve() for p in pdf_files}
        all_outputs: list[Path] = []
        per_file_summaries: list[str] = []
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
                fallback_stem = f"{pdf_path.stem}_comprimido"
                desired_stem = f"{clean_custom}_{idx + 1}" if clean_custom else fallback_stem
                dest = resolve_unique_output_path(
                    out_dir,
                    desired_stem,
                    fallback_stem,
                    extension=".pdf",
                    protected_inputs=protected_set,
                )
                res = pdf_engine.compress_pdf(
                    pdf_path,
                    dest,
                    level=compression_level,
                    password=pwd,
                    on_progress=_sub_progress,
                    is_cancelled=is_cancelled,
                )
            elif tool == ToolType.PDF_TO_IMAGES:
                fallback_stem = f"{pdf_path.stem}_imagenes"
                desired_stem = f"{clean_custom}_{idx + 1}" if clean_custom else fallback_stem
                subdir = resolve_unique_output_path(
                    out_dir,
                    desired_stem,
                    fallback_stem,
                    extension="",
                    protected_inputs=protected_set,
                )
                res = pdf_engine.pdf_to_images(
                    pdf_path,
                    subdir,
                    image_format=image_format,
                    password=pwd,
                    on_progress=_sub_progress,
                    is_cancelled=is_cancelled,
                )
            else:
                fallback_stem = f"{pdf_path.stem}_marca_agua"
                desired_stem = f"{clean_custom}_{idx + 1}" if clean_custom else fallback_stem
                dest = resolve_unique_output_path(
                    out_dir,
                    desired_stem,
                    fallback_stem,
                    extension=".pdf",
                    protected_inputs=protected_set,
                )
                res = pdf_engine.apply_watermark(
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
            if tool == ToolType.COMPRESS:
                per_file_summaries.append(f"{pdf_path.name}: {res.message}")

        saved_pct = (
            max(0.0, ((total_orig - total_final) / total_orig) * 100.0)
            if total_orig > 0 and tool == ToolType.COMPRESS
            else 0.0
        )
        if tool == ToolType.COMPRESS:
            orig_str = _format_bytes(total_orig).replace(".", ",")
            final_str = _format_bytes(total_final).replace(".", ",")
            batch_msg = (
                f"De {orig_str} a {final_str} (-{saved_pct:.0f}%) — "
                + " · ".join(per_file_summaries)
            )
        else:
            batch_msg = f"Lote procesado con éxito ({total} pliegos PDF, {len(all_outputs)} archivo(s) generados)."

        return OperationResult(
            tool=tool,
            output_files=all_outputs,
            original_size_bytes=total_orig,
            final_size_bytes=total_final,
            saved_percentage=round(saved_pct, 2),
            message=batch_msg,
        )

    @staticmethod
    def _batch_target_compress_task(
        pdf_files: list[Path],
        out_dir: Path,
        passwords: dict[Path, str],
        target_mb: float,
        custom_base_name: str = "",
        on_progress: Any = None,
        is_cancelled: Any = None,
    ) -> OperationResult:
        """Comprime un lote de PDFs apuntando al límite en MB de forma independiente por archivo."""
        pe_mod = _pdf_engine_module()
        pdf_engine = pe_mod.PDFEngine
        clean_custom = clean_windows_filename_stem(custom_base_name, extension=".pdf")
        protected_set = {Path(p).resolve() for p in pdf_files}
        all_outputs: list[Path] = []
        per_file_summaries: list[str] = []
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

            fallback_stem = f"{pdf_path.stem}_comprimido"
            desired_stem = f"{clean_custom}_{idx + 1}" if clean_custom else fallback_stem
            dest = resolve_unique_output_path(
                out_dir,
                desired_stem,
                fallback_stem,
                extension=".pdf",
                protected_inputs=protected_set,
            )
            t_res = pdf_engine.compress_pdf_to_target_size(
                pdf_path,
                dest,
                target_mb,
                password=pwd,
                on_progress=_sub_progress,
                is_cancelled=is_cancelled,
            )
            if t_res.already_within_limit:
                total_orig += t_res.original_size_bytes
                total_final += t_res.original_size_bytes
                per_file_summaries.append(f"{pdf_path.name}: ya cumple límite")
                continue
            if t_res.met_target and t_res.operation_result is not None:
                all_outputs.extend(t_res.operation_result.output_files)
                total_orig += t_res.original_size_bytes
                total_final += t_res.operation_result.final_size_bytes
                per_file_summaries.append(
                    f"{pdf_path.name}: {t_res.comparison_text} ({t_res.quality_label})"
                )
            elif t_res.best_pdf_bytes is not None:
                saved_res = pdf_engine.save_pdf_bytes_safely(
                    t_res.best_pdf_bytes,
                    pdf_path,
                    dest,
                    original_size_bytes=t_res.original_size_bytes,
                    quality_label=t_res.quality_label,
                    is_cancelled=is_cancelled,
                )
                t_res.best_pdf_bytes = None
                all_outputs.extend(saved_res.output_files)
                total_orig += t_res.original_size_bytes
                total_final += saved_res.final_size_bytes
                per_file_summaries.append(
                    f"{pdf_path.name}: mejor intento ({pe_mod.format_decimal_mb(saved_res.final_size_bytes)})"
                )

        saved_pct = (
            max(0.0, ((total_orig - total_final) / total_orig) * 100.0)
            if total_orig > 0
            else 0.0
        )
        batch_msg = (
            f"{pe_mod.format_decimal_mb(total_orig)} → {pe_mod.format_decimal_mb(total_final)} "
            f"— " + " · ".join(per_file_summaries)
        )
        return OperationResult(
            tool=ToolType.COMPRESS,
            output_files=all_outputs,
            original_size_bytes=total_orig,
            final_size_bytes=total_final,
            saved_percentage=round(saved_pct, 2),
            message=batch_msg,
        )

    def _build_worker_for_tool(
        self,
        tool: ToolType,
        primary_file: Path,
        primary_pwd: str | None,
        out_dir: Path,
    ) -> PDFOperationWorker:
        pe_mod = _pdf_engine_module()
        pdf_engine = pe_mod.PDFEngine
        valid_files = self._valid_queued_files()
        protected_inputs = {qf.file_path.resolve() for qf in valid_files}
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
        word_paths = [
            qf.file_path
            for qf in valid_files
            if qf.file_path.suffix.lower() in SUPPORTED_WORD_EXTENSIONS
        ]

        suggested_stem, target_ext = self._output_target_spec()
        desired_stem = self._resolve_effective_output_stem(suggested_stem, target_ext)

        if tool == ToolType.WORD_TO_PDF:
            target_words = word_paths or [qf.file_path for qf in valid_files]
            if len(target_words) > 1:
                custom_base = self._custom_output_name if self._output_name_user_edited else ""
                return PDFOperationWorker(
                    convert_word_batch,
                    target_words,
                    out_dir,
                    custom_base_name=custom_base,
                )
            dest = resolve_unique_output_path(
                out_dir,
                desired_stem,
                suggested_stem,
                extension=".pdf",
                protected_inputs=protected_inputs,
            )
            return PDFOperationWorker(
                convert_word_to_pdf,
                target_words[0],
                dest,
            )

        if tool == ToolType.MERGE:
            all_paths = [qf.file_path for qf in valid_files]
            dest = resolve_unique_output_path(
                out_dir,
                desired_stem,
                suggested_stem,
                extension=".pdf",
                protected_inputs=protected_inputs,
            )
            if img_paths or word_paths:
                return PDFOperationWorker(
                    self._merge_mixed_files_task,
                    all_paths,
                    dest,
                    passwords=dict(self._passwords),
                )
            return PDFOperationWorker(
                pdf_engine.merge_pdfs,
                pdf_paths or all_paths,
                dest,
                passwords=dict(self._passwords),
            )

        if tool == ToolType.SPLIT:
            target_pdf = pdf_paths[0] if pdf_paths else primary_file
            dest = resolve_unique_output_path(
                out_dir,
                desired_stem,
                suggested_stem,
                extension=".pdf",
                protected_inputs=protected_inputs,
            )
            return PDFOperationWorker(
                pdf_engine.split_pdf_by_range,
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
            dest = resolve_unique_output_path(
                out_dir,
                desired_stem,
                suggested_stem,
                extension=".pdf",
                protected_inputs=protected_inputs,
            )
            return PDFOperationWorker(
                pdf_engine.organize_pdf,
                target_pdf,
                dest,
                instructions,
                password=primary_pwd,
            )

        if tool in {ToolType.COMPRESS, ToolType.PDF_TO_IMAGES, ToolType.WATERMARK} and len(pdf_paths) > 1:
            custom_base = self._custom_output_name if self._output_name_user_edited else ""
            if tool == ToolType.COMPRESS and self._is_target_size_mode:
                if not self._target_size_valid:
                    raise PDFStudioError(self._target_size_feedback)
                return PDFOperationWorker(
                    self._batch_target_compress_task,
                    pdf_paths,
                    out_dir,
                    dict(self._passwords),
                    self._target_size_mb,
                    custom_base_name=custom_base,
                )
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
                custom_base_name=custom_base,
            )

        if tool == ToolType.COMPRESS:
            target_pdf = pdf_paths[0] if pdf_paths else primary_file
            dest = resolve_unique_output_path(
                out_dir,
                desired_stem,
                suggested_stem,
                extension=".pdf",
                protected_inputs=protected_inputs,
            )
            if self._is_target_size_mode:
                if not self._target_size_valid:
                    raise PDFStudioError(self._target_size_feedback)
                self._pending_target_request = {
                    "input_file": target_pdf,
                    "output_path": dest,
                    "password": primary_pwd,
                    "target_mb": self._target_size_mb,
                }
                return PDFOperationWorker(
                    pdf_engine.compress_pdf_to_target_size,
                    target_pdf,
                    dest,
                    self._target_size_mb,
                    password=primary_pwd,
                )
            return PDFOperationWorker(
                pdf_engine.compress_pdf,
                target_pdf,
                dest,
                level=CompressionLevel(self._compression_level),
                password=primary_pwd,
            )

        if tool == ToolType.PDF_TO_IMAGES:
            target_pdf = pdf_paths[0] if pdf_paths else primary_file
            export_subdir = resolve_unique_output_path(
                out_dir,
                desired_stem,
                suggested_stem,
                extension="",
                protected_inputs=protected_inputs,
            )
            return PDFOperationWorker(
                pdf_engine.pdf_to_images,
                target_pdf,
                export_subdir,
                image_format=ImageFormat(self._image_format),
                password=primary_pwd,
            )

        if tool == ToolType.IMAGES_TO_PDF:
            target_imgs = img_paths or [qf.file_path for qf in valid_files]
            dest = resolve_unique_output_path(
                out_dir,
                desired_stem,
                suggested_stem,
                extension=".pdf",
                protected_inputs=protected_inputs,
            )
            return PDFOperationWorker(
                pdf_engine.images_to_pdf,
                target_imgs,
                dest,
            )

        if tool == ToolType.WATERMARK:
            target_pdf = pdf_paths[0] if pdf_paths else primary_file
            dest = resolve_unique_output_path(
                out_dir,
                desired_stem,
                suggested_stem,
                extension=".pdf",
                protected_inputs=protected_inputs,
            )
            wm_cfg = WatermarkConfig(
                text=self._watermark_text,
                opacity=self._watermark_opacity,
                angle=self._watermark_angle,
                position=WatermarkPosition(self._watermark_position),
            )
            return PDFOperationWorker(
                pdf_engine.apply_watermark,
                target_pdf,
                dest,
                wm_cfg,
                password=primary_pwd,
            )

        # ToolType.SIGN
        target_pdf = pdf_paths[0] if pdf_paths else primary_file
        dest = resolve_unique_output_path(
            out_dir,
            desired_stem,
            suggested_stem,
            extension=".pdf",
            protected_inputs=protected_inputs,
        )
        # Asegurar que la página actual esté inicializada en _page_annotations
        self._get_page_annotation(self._viewer_page_index)
        overlays: list[SignatureOverlay] = []
        for p_idx in sorted(self._page_annotations.keys()):
            ann = self._page_annotations[p_idx]
            has_strokes = bool(ann["strokes"])
            has_stamp = bool(ann["stamp"])
            has_image = bool(ann["image_path"])
            if not (has_strokes or has_stamp or has_image):
                continue
            img_p = Path(ann["image_path"]) if has_image else None
            overlays.append(
                SignatureOverlay(
                    page_index=p_idx,
                    normalized_rect=ann["stamp_rect"],
                    stamp_label=str(ann["stamp"]) if has_stamp else None,
                    image_path=img_p,
                    image_normalized_rect=ann["image_rect"] if has_image else None,
                    freehand_strokes=[list(s["points"]) for s in ann["strokes"]],
                    stroke_widths_pt=[float(s["widthPt"]) for s in ann["strokes"]],
                    default_stroke_width_pt=self.signatureStrokeWidthPt,
                )
            )
        if not overlays:
            ann = self._get_page_annotation(self._viewer_page_index)
            overlays.append(
                SignatureOverlay(
                    page_index=self._viewer_page_index,
                    normalized_rect=ann["stamp_rect"],
                    stamp_label=str(ann["stamp"]) if ann["stamp"] else None,
                    image_path=Path(ann["image_path"]) if ann["image_path"] else None,
                    image_normalized_rect=ann["image_rect"] if ann["image_path"] else None,
                    freehand_strokes=[list(s["points"]) for s in ann["strokes"]],
                    stroke_widths_pt=[float(s["widthPt"]) for s in ann["strokes"]],
                    default_stroke_width_pt=self.signatureStrokeWidthPt,
                )
            )
        return PDFOperationWorker(
            pdf_engine.apply_signature_or_stamp,
            target_pdf,
            dest,
            overlays,
            password=primary_pwd,
        )

    @Slot()
    def cancelActiveOperation(self) -> None:
        self.task_manager.cancel_active_operation()

    def _on_worker_progress(self, percent: int, message: str) -> None:
        self._progress_percent = percent
        self._status_message = message
        self.progressChanged.emit()

    def _on_worker_finished(self, result: Any) -> None:
        self._is_busy = False
        self._has_processing_error = False
        self._progress_percent = 100

        if isinstance(result, TargetCompressionResult):
            req = self._pending_target_request
            self._pending_target_request = None
            self._pending_rescue_preview = False

            if result.already_within_limit:
                self._status_message = result.message
                self._difficult_target_context = None
                self._last_compression_comparison = result.comparison_text
                self._last_compression_quality_label = result.quality_label
                self._last_compression_preview_url = ""
                self.progressChanged.emit()
                self.activeToolChanged.emit()
                self._emit_notice(result.message, is_error=False)
                return

            if not result.met_target:
                self._status_message = result.message
                self._difficult_target_context = {
                    "result": result,
                    "input_file": req["input_file"] if req else Path(),
                    "output_path": req["output_path"] if req else Path(),
                    "password": req["password"] if req else None,
                    "target_mb": result.target_mb,
                }
                self.progressChanged.emit()
                self.activeToolChanged.emit()
                self.difficultCompressionOccurred.emit(
                    result.message, result.anatomy.advisory_message
                )
                return

            if result.operation_result is not None:
                self._difficult_target_context = None
                self._last_compression_comparison = result.comparison_text
                self._last_compression_quality_label = result.quality_label
                op_res = result.operation_result
                self._status_message = op_res.message
                resolved_first = (
                    str(Path(op_res.output_files[0]).resolve())
                    if op_res.output_files
                    else ""
                )
                folder_out = (
                    str(Path(op_res.output_files[0]).resolve().parent)
                    if op_res.output_files
                    else ""
                )
                self._last_output_file = resolved_first
                self._last_output_file_path = resolved_first
                self._last_output_folder = folder_out
                if resolved_first:
                    self.image_provider.invalidate_file(Path(resolved_first))
                    self._last_compression_preview_url = (
                        f"image://pdfpage/0?path={quote(resolved_first)}&dpi=120"
                    )
                else:
                    self._last_compression_preview_url = ""
                self.history_store.record_operation(op_res)
                self.progressChanged.emit()
                self.activeToolChanged.emit()
                self.historyChanged.emit()
                self.operationCompleted.emit(
                    op_res.message, resolved_first, folder_out
                )
                return

        is_rescue_preview = self._pending_rescue_preview
        self._pending_rescue_preview = False
        self._pending_target_request = None
        if not isinstance(result, OperationResult):
            self.progressChanged.emit()
            self.activeToolChanged.emit()
            return

        self._status_message = result.message
        resolved_first = (
            str(Path(result.output_files[0]).resolve()) if result.output_files else ""
        )
        folder_out = (
            str(Path(result.output_files[0]).resolve().parent)
            if result.output_files
            else ""
        )
        self._last_output_file = resolved_first
        self._last_output_file_path = resolved_first
        self._last_output_folder = folder_out

        if is_rescue_preview:
            self._difficult_target_context = None
            if resolved_first:
                self.image_provider.invalidate_file(Path(resolved_first))
                self._last_compression_preview_url = (
                    f"image://pdfpage/0?path={quote(resolved_first)}&dpi=120"
                )
            else:
                self._last_compression_preview_url = ""
        else:
            self._last_compression_comparison = ""
            self._last_compression_quality_label = ""
            self._last_compression_preview_url = ""

        self.history_store.record_operation(result)
        self.progressChanged.emit()
        self.activeToolChanged.emit()
        self.historyChanged.emit()
        self.operationCompleted.emit(result.message, resolved_first, folder_out)

    def _on_worker_cancelled(self, message: str) -> None:
        self._is_busy = False
        self._has_processing_error = False
        self._progress_percent = 0
        self._pending_target_request = None
        self._pending_rescue_preview = False
        self._status_message = message
        self.progressChanged.emit()
        self.activeToolChanged.emit()

    def _on_worker_error(self, error_msg: str) -> None:
        self._is_busy = False
        self._has_processing_error = True
        self._progress_percent = 0
        self._pending_target_request = None
        self._pending_rescue_preview = False
        self._status_message = f"No se pudo completar: {error_msg}"
        self.activeToolChanged.emit()
        self._emit_error(error_msg)

    @Slot()
    def rescueSaveBestAttempt(self) -> None:
        """Acción de rescate 1: guarda en disco el mejor intento generado en RAM."""
        if self._is_busy or self._difficult_target_context is None:
            return
        ctx = self._difficult_target_context
        res = ctx["result"]
        if not res.best_pdf_bytes:
            self._emit_error("No hay resultado previo en memoria para guardar.")
            return
        pdf_engine = _pdf_engine_module().PDFEngine
        self._last_compression_comparison = res.comparison_text
        self._last_compression_quality_label = res.quality_label
        self._pending_rescue_preview = True
        worker = PDFOperationWorker(
            pdf_engine.save_pdf_bytes_safely,
            res.best_pdf_bytes,
            ctx["input_file"],
            ctx["output_path"],
            original_size_bytes=res.original_size_bytes,
            quality_label=res.quality_label,
        )
        self._start_worker(worker, "Guardando el mejor intento alcanzado...")

    @Slot()
    def rescueConvertGrayscale(self) -> None:
        """Acción de rescate 2: convierte imágenes a blanco y negro (escala de grises) y re-evalúa."""
        if self._is_busy or self._difficult_target_context is None:
            return
        ctx = self._difficult_target_context
        pdf_engine = _pdf_engine_module().PDFEngine
        self._pending_target_request = {
            "input_file": ctx["input_file"],
            "output_path": ctx["output_path"],
            "password": ctx["password"],
            "target_mb": ctx["target_mb"],
        }
        worker = PDFOperationWorker(
            pdf_engine.compress_pdf_grayscale_rescue,
            ctx["input_file"],
            ctx["output_path"],
            ctx["target_mb"],
            password=ctx["password"],
        )
        self._start_worker(worker, "Convirtiendo imágenes a escala de grises...")

    @Slot()
    def rescueRemoveBlankPages(self) -> None:
        """Acción de rescate 3: detecta y descarta páginas en blanco a 36 DPI y re-evalúa."""
        if self._is_busy or self._difficult_target_context is None:
            return
        ctx = self._difficult_target_context
        pdf_engine = _pdf_engine_module().PDFEngine
        self._pending_target_request = {
            "input_file": ctx["input_file"],
            "output_path": ctx["output_path"],
            "password": ctx["password"],
            "target_mb": ctx["target_mb"],
        }
        worker = PDFOperationWorker(
            pdf_engine.remove_blank_pages_and_compress,
            ctx["input_file"],
            ctx["output_path"],
            ctx["target_mb"],
            password=ctx["password"],
        )
        self._start_worker(worker, "Analizando páginas en blanco a 36 DPI...")

    @Slot()
    def rescueSplitIntoParts(self) -> None:
        """Acción de rescate 4: divide el PDF en partes consecutivas bajo el límite objetivo."""
        if self._is_busy or self._difficult_target_context is None:
            return
        ctx = self._difficult_target_context
        res = ctx["result"]
        pdf_engine = _pdf_engine_module().PDFEngine
        self._last_compression_comparison = ""
        self._last_compression_quality_label = ""
        self._pending_rescue_preview = True
        worker = PDFOperationWorker(
            pdf_engine.split_pdf_to_target_size,
            ctx["input_file"],
            ctx["output_path"],
            ctx["target_mb"],
            password=ctx["password"],
            source_pdf_bytes=res.best_pdf_bytes,
        )
        self._start_worker(worker, "Dividiendo documento en partes bajo el límite...")

    @staticmethod
    def _normalize_target_path(raw_path: str) -> Path | None:
        text = (raw_path or "").strip()
        if not text:
            return None
        if text.startswith("file:"):
            text = QUrl(text).toLocalFile()
        if not text:
            return None
        return Path(text).resolve()

    @Slot(str, result=bool)
    def openFileInSystem(self, file_path_str: str = "") -> bool:
        """Abre el archivo generado en la aplicación predeterminada con manejo explícito de errores."""
        raw = (
            (file_path_str or "").strip()
            or self._last_output_file_path
            or self._last_output_file
        )
        target_path = self._normalize_target_path(raw)
        if target_path is None:
            self._emit_error("Todavía no hay ningún archivo generado para abrir.")
            return False
        if not target_path.exists():
            self._emit_error(
                f"No se encontró el archivo generado en '{target_path}'."
            )
            return False

        try:
            if sys.platform.startswith("win"):
                os.startfile(str(target_path))  # type: ignore[attr-defined]
            else:
                if not QDesktopServices.openUrl(QUrl.fromLocalFile(str(target_path))):
                    self._emit_error(
                        f"No se pudo abrir '{target_path.name}' con la aplicación predeterminada."
                    )
                    return False
            return True
        except OSError as exc:
            self._emit_error(f"No se pudo abrir '{target_path.name}': {exc}")
            return False

    @staticmethod
    def _open_folder_and_select_item_win(target_path: Path) -> bool:
        """Abre o enfoca la carpeta en el Explorador de Windows seleccionando el archivo vía Shell COM."""
        if not sys.platform.startswith("win"):
            return False

        ole32 = ctypes.windll.ole32  # type: ignore[attr-defined]
        shell32 = ctypes.windll.shell32  # type: ignore[attr-defined]

        ole32.CoInitialize.argtypes = [ctypes.c_void_p]
        ole32.CoInitialize.restype = ctypes.c_long
        ole32.CoUninitialize.argtypes = []
        ole32.CoUninitialize.restype = None

        shell32.ILCreateFromPathW.argtypes = [ctypes.c_wchar_p]
        shell32.ILCreateFromPathW.restype = ctypes.c_void_p
        shell32.ILFree.argtypes = [ctypes.c_void_p]
        shell32.ILFree.restype = None
        shell32.SHOpenFolderAndSelectItems.argtypes = [
            ctypes.c_void_p,
            ctypes.c_uint,
            ctypes.c_void_p,
            ctypes.c_ulong,
        ]
        shell32.SHOpenFolderAndSelectItems.restype = ctypes.c_long

        hr_init = ole32.CoInitialize(None)
        should_uninit = hr_init in (0, 1)  # S_OK o S_FALSE
        pidl = None
        try:
            pidl = shell32.ILCreateFromPathW(str(target_path.resolve()))
            if not pidl:
                return False
            hr = shell32.SHOpenFolderAndSelectItems(pidl, 0, None, 0)
            return hr == 0
        except Exception:
            return False
        finally:
            if pidl:
                shell32.ILFree(pidl)
            if should_uninit:
                ole32.CoUninitialize()

    @Slot(str, result=bool)
    def showFileInFolder(self, file_or_folder_str: str = "") -> bool:
        """Abre la carpeta de destino en el Explorador reutilizando la ventana existente si está abierta."""
        now = time.monotonic()
        if (now - self._last_show_folder_monotonic) < SHOW_FOLDER_DEBOUNCE_SECONDS:
            return True
        self._last_show_folder_monotonic = now

        raw = (
            (file_or_folder_str or "").strip()
            or self._last_output_file_path
            or self._last_output_file
            or self._last_output_folder
        )
        target_path = self._normalize_target_path(raw)
        if target_path is None:
            self._emit_error("Todavía no hay ninguna ubicación de salida para mostrar.")
            return False

        if sys.platform.startswith("win"):
            if target_path.exists() and target_path.is_file():
                if self._open_folder_and_select_item_win(target_path):
                    return True
                if target_path.parent.exists():
                    try:
                        os.startfile(str(target_path.parent))  # type: ignore[attr-defined]
                        return True
                    except OSError as exc:
                        self._emit_error(
                            f"No se pudo abrir la carpeta '{target_path.parent}': {exc}"
                        )
                        return False
                self._emit_error(
                    f"No se pudo abrir el Explorador para '{target_path}'."
                )
                return False

            if target_path.exists() and target_path.is_dir():
                try:
                    os.startfile(str(target_path))  # type: ignore[attr-defined]
                    return True
                except OSError as exc:
                    self._emit_error(
                        f"No se pudo abrir la carpeta '{target_path}': {exc}"
                    )
                    return False

            if target_path.parent.exists() and target_path.parent.is_dir():
                try:
                    os.startfile(str(target_path.parent))  # type: ignore[attr-defined]
                    self._emit_notice(
                        f"El archivo '{target_path.name}' ya no existe; se abrió su carpeta.",
                        is_error=False,
                    )
                    return True
                except OSError as exc:
                    self._emit_error(
                        f"No se pudo abrir la carpeta '{target_path.parent}': {exc}"
                    )
                    return False

            self._emit_error(
                f"La ubicación '{target_path}' ya no existe en el equipo."
            )
            return False

        if target_path.exists():
            folder = target_path if target_path.is_dir() else target_path.parent
        elif target_path.parent.exists():
            folder = target_path.parent
        else:
            self._emit_error(f"La ubicación '{target_path}' ya no existe.")
            return False

        if not QDesktopServices.openUrl(QUrl.fromLocalFile(str(folder))):
            self._emit_error(f"No se pudo abrir la carpeta '{folder}'.")
            return False
        return True

