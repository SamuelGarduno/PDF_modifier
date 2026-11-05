"""Modelos de datos y configuraciones del dominio de procesamiento PDF."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path


class ToolType(StrEnum):
    """Herramientas principales disponibles en la suite."""

    MERGE = "merge"
    SPLIT = "split"
    ORGANIZE = "organize"
    COMPRESS = "compress"
    PROTECT = "protect"
    UNLOCK = "unlock"
    PDF_TO_IMAGES = "pdf_to_images"
    IMAGES_TO_PDF = "images_to_pdf"
    WATERMARK = "watermark"
    SIGN = "sign"


class CompressionLevel(StrEnum):
    """Niveles de compresión disponibles con su estimación de ahorro."""

    EXTREME = "extreme"
    RECOMMENDED = "recommended"
    LOW_LOSS = "low_loss"


class ImageFormat(StrEnum):
    """Formatos soportados para exportación de páginas como imagen."""

    PNG = "png"
    JPG = "jpg"


class WatermarkPosition(StrEnum):
    """Posiciones posibles en una cuadrícula 3x3 para marcas de agua y sellos."""

    TOP_LEFT = "top_left"
    TOP_CENTER = "top_center"
    TOP_RIGHT = "top_right"
    MIDDLE_LEFT = "middle_left"
    CENTER = "center"
    MIDDLE_RIGHT = "middle_right"
    BOTTOM_LEFT = "bottom_left"
    BOTTOM_CENTER = "bottom_center"
    BOTTOM_RIGHT = "bottom_right"


@dataclass(slots=True)
class QueuedFile:
    """Representa un archivo en la cola de ingesta."""

    file_path: Path
    original_size_bytes: int
    page_count: int = 0
    is_encrypted: bool = False
    status: str = "Listo"
    password: str | None = None


@dataclass(slots=True)
class PageItemInstruction:
    """Instrucción de transformación para una página en el organizador."""

    source_page_index: int  # 0-based en el documento original
    rotation_degrees: int = 0  # Múltiplo de 90 (0, 90, 180, 270)


@dataclass(slots=True)
class WatermarkConfig:
    """Configuración para estampar marca de agua de texto."""

    text: str
    opacity: float = 0.35
    angle: float = 45.0
    position: WatermarkPosition = WatermarkPosition.CENTER
    font_size: float = 36.0
    color_rgb: tuple[float, float, float] = (0.408, 0.114, 0.227)  # #681D3A


@dataclass(slots=True)
class SignatureOverlay:
    """Datos de firma libre, sello predefinido o imagen PNG sobre una página."""

    page_index: int = 0  # 0-based
    stamp_label: str | None = None  # Ej. "APROBADO", "CONFIDENCIAL"
    image_path: Path | None = None  # Imagen PNG con transparencia
    freehand_strokes: list[list[tuple[float, float]]] = field(default_factory=list)
    normalized_rect: tuple[float, float, float, float] = (0.60, 0.78, 0.92, 0.92)


@dataclass(slots=True)
class OperationResult:
    """Resultado devuelto por cualquier operación del motor PDF."""

    tool: ToolType
    output_files: list[Path]
    original_size_bytes: int
    final_size_bytes: int
    saved_percentage: float
    message: str

