"""Motor síncrono puro de manipulación de documentos PDF con PyMuPDF (fitz) y pypdf."""

from __future__ import annotations

from collections.abc import Callable
import io
import os
from pathlib import Path
import shutil
import tempfile

import pymupdf as fitz  # PyMuPDF sin warning de deprecación en Python 3.14
from PIL import Image
from pypdf import PdfReader, PdfWriter
from pypdf.errors import PdfReadError, PdfStreamError
from PySide6.QtCore import QBuffer, QIODevice, QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QFontMetricsF, QImage, QPainter, QPainterPath, QPen

from core.exceptions import (
    InvalidPasswordError,
    PDFCorruptedError,
    PDFEncryptedError,
    PDFStudioError,
    TaskCancelledError,
)
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
from core.range_parser import parse_page_ranges

ProgressCallback = Callable[[int, str], None]
CancelCheckCallback = Callable[[], bool]

DEFAULT_THUMBNAIL_DPI = 96
HIGH_RES_RENDER_DPI = 160
COMPRESSION_ESTIMATES: dict[CompressionLevel, float] = {
    CompressionLevel.EXTREME: 62.0,
    CompressionLevel.RECOMMENDED: 38.0,
    CompressionLevel.LOW_LOSS: 16.0,
}


def ensure_safe_output_path(
    input_path: Path,
    requested_output: Path | None,
    default_suffix: str = "_modificado",
    extension: str = ".pdf",
    allow_overwrite: bool = False,
) -> Path:
    """Garantiza que nunca se sobrescriba el archivo original salvo confirmación explícita."""
    resolved_input = input_path.resolve()
    if requested_output is None:
        candidate = resolved_input.with_name(
            f"{resolved_input.stem}{default_suffix}{extension}"
        )
    else:
        candidate = requested_output.resolve()
        if candidate == resolved_input and not allow_overwrite:
            candidate = resolved_input.with_name(
                f"{resolved_input.stem}{default_suffix}{extension}"
            )

    if candidate.exists() and candidate == resolved_input and not allow_overwrite:
        counter = 1
        while True:
            alt = resolved_input.with_name(
                f"{resolved_input.stem}{default_suffix}_{counter}{extension}"
            )
            if not alt.exists():
                return alt
            counter += 1

    candidate.parent.mkdir(parents=True, exist_ok=True)
    return candidate


def _check_cancel(is_cancelled: CancelCheckCallback | None) -> None:
    if is_cancelled is not None and is_cancelled():
        raise TaskCancelledError("Operación cancelada por el usuario.")


def _emit_progress(
    on_progress: ProgressCallback | None, percent: int, status: str
) -> None:
    if on_progress is not None:
        clamped = max(0, min(100, percent))
        on_progress(clamped, status)


def inspect_pdf_file(
    file_path: Path, password: str | None = None
) -> QueuedFile:
    """Inspecciona un archivo PDF validando su integridad, páginas y estado de cifrado."""
    path = Path(file_path)
    if not path.exists() or not path.is_file():
        raise PDFCorruptedError(f"El archivo no existe: {path}")

    size_bytes = path.stat().st_size
    if size_bytes == 0:
        raise PDFCorruptedError(f"El archivo está vacío (0 bytes): {path.name}")

    try:
        doc = fitz.open(path)
    except Exception as exc:
        raise PDFCorruptedError(
            f"El archivo '{path.name}' no es un PDF válido o está dañado."
        ) from exc

    try:
        is_encrypted = bool(doc.needs_pass)
        if is_encrypted:
            if password:
                auth_result = doc.authenticate(password)
                if auth_result == 0:
                    raise InvalidPasswordError(
                        f"Contraseña incorrecta para '{path.name}'."
                    )
                page_count = doc.page_count
                return QueuedFile(
                    file_path=path,
                    original_size_bytes=size_bytes,
                    page_count=page_count,
                    is_encrypted=True,
                    status="Desbloqueado",
                    password=password,
                )
            return QueuedFile(
                file_path=path,
                original_size_bytes=size_bytes,
                page_count=0,
                is_encrypted=True,
                status="Protegido (requiere contraseña)",
                password=None,
            )

        page_count = doc.page_count
        if page_count < 1:
            raise PDFCorruptedError(
                f"El archivo '{path.name}' no contiene páginas válidas."
            )
        return QueuedFile(
            file_path=path,
            original_size_bytes=size_bytes,
            page_count=page_count,
            is_encrypted=False,
            status="Listo",
            password=None,
        )
    finally:
        doc.close()


def _open_verified_pypdf_reader(
    file_path: Path,
    password: str | None = None,
    allow_encrypted_without_pass: bool = False,
) -> PdfReader:
    """Abre un PdfReader verificando corrupción y cifrado."""
    path = Path(file_path)
    if not path.exists() or path.stat().st_size == 0:
        raise PDFCorruptedError(
            f"El archivo '{path.name}' no existe o está vacío (0 bytes)."
        )

    try:
        reader = PdfReader(str(path))
    except (PdfReadError, PdfStreamError, ValueError, OSError) as exc:
        raise PDFCorruptedError(
            f"El archivo '{path.name}' está corrupto o no tiene formato PDF válido."
        ) from exc

    if reader.is_encrypted:
        if password is not None:
            try:
                res = reader.decrypt(password)
            except Exception as exc:
                raise InvalidPasswordError(
                    f"No se pudo descifrar '{path.name}' con la contraseña dada."
                ) from exc
            if res == 0:
                raise InvalidPasswordError(
                    f"Contraseña inválida para el archivo '{path.name}'."
                )
        elif not allow_encrypted_without_pass:
            raise PDFEncryptedError(
                f"El archivo '{path.name}' está protegido con contraseña."
            )

    try:
        num_pages = len(reader.pages)
    except Exception as exc:
        if reader.is_encrypted:
            raise PDFEncryptedError(
                f"El archivo '{path.name}' requiere contraseña."
            ) from exc
        raise PDFCorruptedError(
            f"No se pudieron leer las páginas de '{path.name}'."
        ) from exc

    if num_pages < 1:
        raise PDFCorruptedError(f"El PDF '{path.name}' no tiene páginas.")

    return reader


def _atomic_write_pdf(
    writer: PdfWriter,
    destination: Path,
    is_cancelled: CancelCheckCallback | None = None,
) -> None:
    """Escribe un PdfWriter en un archivo temporal y lo mueve atómicamente al destino."""
    destination.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(
        prefix=".tmp_coquette_", suffix=".pdf", dir=str(destination.parent)
    )
    os.close(fd)
    tmp_path = Path(tmp_name)
    try:
        _check_cancel(is_cancelled)
        with tmp_path.open("wb") as out_stream:
            writer.write(out_stream)
        _check_cancel(is_cancelled)
        shutil.move(str(tmp_path), str(destination))
    except Exception:
        if tmp_path.exists():
            tmp_path.unlink(missing_ok=True)
        raise


class PDFEngine:
    """Motor principal para todas las operaciones sobre documentos PDF e imágenes."""

    @staticmethod
    def estimate_compression_savings(
        original_bytes: int, level: CompressionLevel
    ) -> tuple[int, float]:
        """Calcula el peso estimado final y porcentaje ahorrado según el nivel de compresión."""
        pct = COMPRESSION_ESTIMATES.get(level, 38.0)
        estimated_final = max(1, int(original_bytes * (1.0 - pct / 100.0)))
        return estimated_final, pct

    @staticmethod
    def render_page_png_bytes(
        file_path: Path,
        page_index: int,
        dpi: int = DEFAULT_THUMBNAIL_DPI,
        password: str | None = None,
    ) -> bytes:
        """Renderiza una página específica a bytes PNG usando PyMuPDF con DPI controlado."""
        path = Path(file_path)
        if not path.exists() or path.stat().st_size == 0:
            raise PDFCorruptedError(f"Archivo inválido o vacío: {path.name}")

        try:
            doc = fitz.open(path)
        except Exception as exc:
            raise PDFCorruptedError(
                f"No se pudo abrir '{path.name}' para previsualización."
            ) from exc

        try:
            if doc.needs_pass:
                if not password:
                    raise PDFEncryptedError(
                        f"El documento '{path.name}' está protegido con contraseña."
                    )
                if doc.authenticate(password) == 0:
                    raise InvalidPasswordError(
                        f"Contraseña incorrecta para '{path.name}'."
                    )

            if page_index < 0 or page_index >= doc.page_count:
                raise IndexError(
                    f"Índice de página {page_index} fuera de rango (0..{doc.page_count - 1})."
                )

            page = doc.load_page(page_index)
            zoom = max(0.25, dpi / 72.0)
            matrix = fitz.Matrix(zoom, zoom)
            pixmap = page.get_pixmap(matrix=matrix, alpha=False)
            return bytes(pixmap.tobytes("png"))
        finally:
            doc.close()

    @staticmethod
    def merge_pdfs(
        input_files: list[Path],
        output_path: Path,
        passwords: dict[Path, str] | None = None,
        on_progress: ProgressCallback | None = None,
        is_cancelled: CancelCheckCallback | None = None,
    ) -> OperationResult:
        """Une múltiples archivos PDF en uno solo manteniendo su orden."""
        if not input_files:
            raise PDFStudioError("Debes proporcionar al menos un archivo PDF para unir.")

        passwords = passwords or {}
        writer = PdfWriter()
        total_original_bytes = 0
        total_files = len(input_files)

        try:
            for idx, file_path in enumerate(input_files):
                _check_cancel(is_cancelled)
                path = Path(file_path)
                pwd = passwords.get(path) or passwords.get(path.resolve())
                reader = _open_verified_pypdf_reader(path, password=pwd)
                total_original_bytes += path.stat().st_size

                for page in reader.pages:
                    _check_cancel(is_cancelled)
                    writer.add_page(page)

                pct = int(((idx + 1) / total_files) * 85)
                _emit_progress(
                    on_progress,
                    pct,
                    f"Uniendo '{path.name}' ({idx + 1}/{total_files})...",
                )

            safe_dest = ensure_safe_output_path(
                Path(input_files[0]), output_path, default_suffix="_unido"
            )
            _emit_progress(on_progress, 92, "Guardando documento unido...")
            _atomic_write_pdf(writer, safe_dest, is_cancelled=is_cancelled)
            _emit_progress(on_progress, 100, "PDFs unidos correctamente.")

            final_bytes = safe_dest.stat().st_size
            return OperationResult(
                tool=ToolType.MERGE,
                output_files=[safe_dest],
                original_size_bytes=total_original_bytes,
                final_size_bytes=final_bytes,
                saved_percentage=0.0,
                message=f"Se unieron {total_files} archivos en '{safe_dest.name}'.",
            )
        finally:
            writer.close()

    @staticmethod
    def split_pdf_by_range(
        input_file: Path,
        output_path: Path,
        range_expr: str,
        password: str | None = None,
        split_into_separate_files: bool = False,
        on_progress: ProgressCallback | None = None,
        is_cancelled: CancelCheckCallback | None = None,
    ) -> OperationResult:
        """Extrae páginas según una expresión de rangos ('1-5, 8') en uno o varios PDFs."""
        path = Path(input_file)
        reader = _open_verified_pypdf_reader(path, password=password)
        total_pages = len(reader.pages)
        selected_indices = parse_page_ranges(range_expr, total_pages)
        original_bytes = path.stat().st_size

        created_files: list[Path] = []
        try:
            if not split_into_separate_files:
                writer = PdfWriter()
                try:
                    for idx, page_idx in enumerate(selected_indices):
                        _check_cancel(is_cancelled)
                        writer.add_page(reader.pages[page_idx])
                        pct = int(((idx + 1) / len(selected_indices)) * 88)
                        _emit_progress(
                            on_progress,
                            pct,
                            f"Extrayendo página {page_idx + 1}...",
                        )

                    safe_dest = ensure_safe_output_path(
                        path, output_path, default_suffix="_extraido"
                    )
                    _atomic_write_pdf(writer, safe_dest, is_cancelled=is_cancelled)
                    created_files.append(safe_dest)
                finally:
                    writer.close()
            else:
                base_dest = ensure_safe_output_path(
                    path, output_path, default_suffix="_parte"
                )
                for idx, page_idx in enumerate(selected_indices):
                    _check_cancel(is_cancelled)
                    writer = PdfWriter()
                    try:
                        writer.add_page(reader.pages[page_idx])
                        part_dest = base_dest.with_name(
                            f"{base_dest.stem}_pag_{page_idx + 1}.pdf"
                        )
                        _atomic_write_pdf(writer, part_dest, is_cancelled=is_cancelled)
                        created_files.append(part_dest)
                    finally:
                        writer.close()
                    pct = int(((idx + 1) / len(selected_indices)) * 95)
                    _emit_progress(
                        on_progress,
                        pct,
                        f"Guardada página {page_idx + 1} ({idx + 1}/{len(selected_indices)})...",
                    )

            _emit_progress(on_progress, 100, "Extracción completada.")
            final_bytes = sum(f.stat().st_size for f in created_files if f.exists())
            return OperationResult(
                tool=ToolType.SPLIT,
                output_files=created_files,
                original_size_bytes=original_bytes,
                final_size_bytes=final_bytes,
                saved_percentage=0.0,
                message=f"Se extrajeron {len(selected_indices)} página(s) correctamente.",
            )
        except Exception:
            for partial in created_files:
                partial.unlink(missing_ok=True)
            raise

    @staticmethod
    def organize_pdf(
        input_file: Path,
        output_path: Path,
        instructions: list[PageItemInstruction],
        password: str | None = None,
        on_progress: ProgressCallback | None = None,
        is_cancelled: CancelCheckCallback | None = None,
    ) -> OperationResult:
        """Reordena, rota, duplica o elimina páginas según la lista de instrucciones."""
        if not instructions:
            raise PDFStudioError(
                "El documento resultante debe conservar al menos una página."
            )

        path = Path(input_file)
        reader = _open_verified_pypdf_reader(path, password=password)
        max_pages = len(reader.pages)
        original_bytes = path.stat().st_size

        writer = PdfWriter()
        try:
            for idx, item in enumerate(instructions):
                _check_cancel(is_cancelled)
                if item.source_page_index < 0 or item.source_page_index >= max_pages:
                    raise PDFStudioError(
                        f"Índice de página fuera de límites: {item.source_page_index}"
                    )
                page = writer.add_page(reader.pages[item.source_page_index])
                rotation = item.rotation_degrees % 360
                if rotation != 0:
                    page.rotate(rotation)

                pct = int(((idx + 1) / len(instructions)) * 90)
                _emit_progress(
                    on_progress,
                    pct,
                    f"Organizando página {idx + 1} de {len(instructions)}...",
                )

            safe_dest = ensure_safe_output_path(
                path, output_path, default_suffix="_organizado"
            )
            _atomic_write_pdf(writer, safe_dest, is_cancelled=is_cancelled)
            _emit_progress(on_progress, 100, "Páginas organizadas correctamente.")

            final_bytes = safe_dest.stat().st_size
            return OperationResult(
                tool=ToolType.ORGANIZE,
                output_files=[safe_dest],
                original_size_bytes=original_bytes,
                final_size_bytes=final_bytes,
                saved_percentage=0.0,
                message=f"Documento organizado ({len(instructions)} páginas).",
            )
        finally:
            writer.close()

    @staticmethod
    def compress_pdf(
        input_file: Path,
        output_path: Path,
        level: CompressionLevel = CompressionLevel.RECOMMENDED,
        password: str | None = None,
        on_progress: ProgressCallback | None = None,
        is_cancelled: CancelCheckCallback | None = None,
    ) -> OperationResult:
        """Comprime un PDF limpiando objetos huérfanos, flujos y reescalando imágenes con PyMuPDF."""
        path = Path(input_file)
        info = inspect_pdf_file(path, password=password)
        if info.is_encrypted and not password:
            raise PDFEncryptedError(
                f"El archivo '{path.name}' está protegido con contraseña."
            )

        original_bytes = info.original_size_bytes
        safe_dest = ensure_safe_output_path(
            path, output_path, default_suffix="_comprimido"
        )

        fd, tmp_name = tempfile.mkstemp(
            prefix=".tmp_compress_", suffix=".pdf", dir=str(safe_dest.parent)
        )
        os.close(fd)
        tmp_path = Path(tmp_name)

        doc = fitz.open(path)
        try:
            if doc.needs_pass and password:
                doc.authenticate(password)

            _emit_progress(on_progress, 20, "Analizando estructura y recursos...")
            _check_cancel(is_cancelled)

            # Ajustar parámetros de reescritura de imágenes según el nivel
            if hasattr(doc, "rewrite_images"):
                if level == CompressionLevel.EXTREME:
                    doc.rewrite_images(dpi_threshold=100, dpi_target=72, quality=50)
                elif level == CompressionLevel.RECOMMENDED:
                    doc.rewrite_images(dpi_threshold=150, dpi_target=110, quality=72)
                else:
                    doc.rewrite_images(dpi_threshold=220, dpi_target=150, quality=85)

            _emit_progress(on_progress, 65, "Compactando flujos y tabla XREF...")
            _check_cancel(is_cancelled)

            garbage_level = 4 if level != CompressionLevel.LOW_LOSS else 3
            doc.save(
                str(tmp_path),
                garbage=garbage_level,
                deflate=True,
                clean=True,
                deflate_images=True,
                deflate_fonts=True,
            )
            doc.close()
            _check_cancel(is_cancelled)
            shutil.move(str(tmp_path), str(safe_dest))
        except Exception:
            doc.close()
            tmp_path.unlink(missing_ok=True)
            raise

        final_bytes = safe_dest.stat().st_size
        saved_pct = (
            max(0.0, ((original_bytes - final_bytes) / original_bytes) * 100.0)
            if original_bytes > 0
            else 0.0
        )
        _emit_progress(on_progress, 100, "Compresión finalizada.")

        return OperationResult(
            tool=ToolType.COMPRESS,
            output_files=[safe_dest],
            original_size_bytes=original_bytes,
            final_size_bytes=final_bytes,
            saved_percentage=round(saved_pct, 2),
            message=(
                f"Archivo comprimido ({saved_pct:.1f}% reducido, "
                f"{final_bytes / 1024:.1f} KB finales)."
            ),
        )

    @staticmethod
    def protect_pdf(
        input_file: Path,
        output_path: Path,
        new_password: str,
        current_password: str | None = None,
        on_progress: ProgressCallback | None = None,
        is_cancelled: CancelCheckCallback | None = None,
    ) -> OperationResult:
        """Cifra un archivo PDF con contraseña usando AES-256."""
        if not new_password or not new_password.strip():
            raise PDFStudioError(
                "La contraseña para proteger el PDF no puede estar vacía."
            )

        path = Path(input_file)
        reader = _open_verified_pypdf_reader(path, password=current_password)
        original_bytes = path.stat().st_size

        writer = PdfWriter()
        try:
            total = len(reader.pages)
            for idx, page in enumerate(reader.pages):
                _check_cancel(is_cancelled)
                writer.add_page(page)
                _emit_progress(
                    on_progress,
                    int(((idx + 1) / total) * 75),
                    f"Copiando página {idx + 1}/{total}...",
                )

            _emit_progress(on_progress, 85, "Aplicando cifrado AES-256...")
            writer.encrypt(user_password=new_password, algorithm="AES-256")

            safe_dest = ensure_safe_output_path(
                path, output_path, default_suffix="_protegido"
            )
            _atomic_write_pdf(writer, safe_dest, is_cancelled=is_cancelled)
            _emit_progress(on_progress, 100, "PDF protegido con éxito.")

            final_bytes = safe_dest.stat().st_size
            return OperationResult(
                tool=ToolType.PROTECT,
                output_files=[safe_dest],
                original_size_bytes=original_bytes,
                final_size_bytes=final_bytes,
                saved_percentage=0.0,
                message=f"Documento cifrado guardado en '{safe_dest.name}'.",
            )
        finally:
            writer.close()

    @staticmethod
    def unlock_pdf(
        input_file: Path,
        output_path: Path,
        password: str,
        on_progress: ProgressCallback | None = None,
        is_cancelled: CancelCheckCallback | None = None,
    ) -> OperationResult:
        """Elimina la contraseña de un PDF protegido conociendo su clave actual."""
        if not password:
            raise InvalidPasswordError(
                "Debes ingresar la contraseña del documento para desbloquearlo."
            )

        path = Path(input_file)
        reader = _open_verified_pypdf_reader(path, password=password)
        original_bytes = path.stat().st_size

        writer = PdfWriter()
        try:
            total = len(reader.pages)
            for idx, page in enumerate(reader.pages):
                _check_cancel(is_cancelled)
                writer.add_page(page)
                _emit_progress(
                    on_progress,
                    int(((idx + 1) / total) * 85),
                    f"Desbloqueando página {idx + 1}/{total}...",
                )

            safe_dest = ensure_safe_output_path(
                path, output_path, default_suffix="_desbloqueado"
            )
            _atomic_write_pdf(writer, safe_dest, is_cancelled=is_cancelled)
            _emit_progress(on_progress, 100, "Contraseña eliminada del PDF.")

            final_bytes = safe_dest.stat().st_size
            return OperationResult(
                tool=ToolType.UNLOCK,
                output_files=[safe_dest],
                original_size_bytes=original_bytes,
                final_size_bytes=final_bytes,
                saved_percentage=0.0,
                message=f"PDF desbloqueado guardado en '{safe_dest.name}'.",
            )
        finally:
            writer.close()

    @staticmethod
    def pdf_to_images(
        input_file: Path,
        output_dir: Path,
        image_format: ImageFormat = ImageFormat.PNG,
        dpi: int = HIGH_RES_RENDER_DPI,
        password: str | None = None,
        on_progress: ProgressCallback | None = None,
        is_cancelled: CancelCheckCallback | None = None,
    ) -> OperationResult:
        """Exporta todas las páginas de un PDF como archivos de imagen PNG o JPG."""
        path = Path(input_file)
        info = inspect_pdf_file(path, password=password)
        if info.is_encrypted and not password:
            raise PDFEncryptedError(
                f"El archivo '{path.name}' está protegido con contraseña."
            )

        out_folder = Path(output_dir)
        out_folder.mkdir(parents=True, exist_ok=True)
        ext = "jpg" if image_format == ImageFormat.JPG else "png"

        doc = fitz.open(path)
        created_files: list[Path] = []
        try:
            if doc.needs_pass and password:
                doc.authenticate(password)

            total = doc.page_count
            zoom = max(0.5, dpi / 72.0)
            matrix = fitz.Matrix(zoom, zoom)

            for page_idx in range(total):
                _check_cancel(is_cancelled)
                page = doc.load_page(page_idx)
                pix = page.get_pixmap(matrix=matrix, alpha=False)
                img_path = out_folder / f"{path.stem}_pag_{page_idx + 1:03d}.{ext}"
                pix.save(str(img_path))
                created_files.append(img_path)

                pct = int(((page_idx + 1) / total) * 100)
                _emit_progress(
                    on_progress,
                    pct,
                    f"Exportada página {page_idx + 1}/{total} a {ext.upper()}...",
                )

            final_bytes = sum(f.stat().st_size for f in created_files if f.exists())
            return OperationResult(
                tool=ToolType.PDF_TO_IMAGES,
                output_files=created_files,
                original_size_bytes=info.original_size_bytes,
                final_size_bytes=final_bytes,
                saved_percentage=0.0,
                message=f"Se exportaron {len(created_files)} imágenes ({ext.upper()}).",
            )
        except Exception:
            for f in created_files:
                f.unlink(missing_ok=True)
            raise
        finally:
            doc.close()

    @staticmethod
    def images_to_pdf(
        image_files: list[Path],
        output_path: Path,
        on_progress: ProgressCallback | None = None,
        is_cancelled: CancelCheckCallback | None = None,
    ) -> OperationResult:
        """Convierte una lista de imágenes (PNG/JPG) en un documento PDF multipágina."""
        if not image_files:
            raise PDFStudioError(
                "Debes seleccionar al menos una imagen para convertir a PDF."
            )

        total_original_bytes = 0
        doc = fitz.open()
        try:
            for idx, img_file in enumerate(image_files):
                _check_cancel(is_cancelled)
                img_path = Path(img_file)
                if not img_path.exists() or img_path.stat().st_size == 0:
                    raise PDFCorruptedError(
                        f"La imagen '{img_path.name}' no existe o está vacía."
                    )

                total_original_bytes += img_path.stat().st_size
                try:
                    with Image.open(img_path) as pil_img:
                        pil_img.verify()
                except Exception as exc:
                    raise PDFCorruptedError(
                        f"El archivo '{img_path.name}' no es una imagen válida."
                    ) from exc

                img_doc = fitz.open(img_path)
                try:
                    pdf_bytes = img_doc.convert_to_pdf()
                    img_pdf = fitz.open("pdf", pdf_bytes)
                    doc.insert_pdf(img_pdf)
                    img_pdf.close()
                finally:
                    img_doc.close()

                pct = int(((idx + 1) / len(image_files)) * 90)
                _emit_progress(
                    on_progress,
                    pct,
                    f"Insertando imagen '{img_path.name}' ({idx + 1}/{len(image_files)})...",
                )

            safe_dest = ensure_safe_output_path(
                Path(image_files[0]),
                output_path,
                default_suffix="_imagenes",
                extension=".pdf",
            )
            doc.save(str(safe_dest), deflate=True)
            _emit_progress(on_progress, 100, "Imágenes convertidas a PDF.")
            final_bytes = safe_dest.stat().st_size

            return OperationResult(
                tool=ToolType.IMAGES_TO_PDF,
                output_files=[safe_dest],
                original_size_bytes=total_original_bytes,
                final_size_bytes=final_bytes,
                saved_percentage=0.0,
                message=f"Se creó '{safe_dest.name}' a partir de {len(image_files)} imagen(es).",
            )
        finally:
            doc.close()

    @staticmethod
    def apply_watermark(
        input_file: Path,
        output_path: Path,
        config: WatermarkConfig,
        password: str | None = None,
        on_progress: ProgressCallback | None = None,
        is_cancelled: CancelCheckCallback | None = None,
    ) -> OperationResult:
        """Estampa una marca de agua de texto con opacidad, ángulo y posición 3x3."""
        if not config.text or not config.text.strip():
            raise PDFStudioError("El texto de la marca de agua no puede estar vacío.")

        path = Path(input_file)
        info = inspect_pdf_file(path, password=password)
        if info.is_encrypted and not password:
            raise PDFEncryptedError(
                f"El archivo '{path.name}' está protegido con contraseña."
            )

        safe_dest = ensure_safe_output_path(
            path, output_path, default_suffix="_marca_agua"
        )
        fd, tmp_name = tempfile.mkstemp(
            prefix=".tmp_wm_", suffix=".pdf", dir=str(safe_dest.parent)
        )
        os.close(fd)
        tmp_path = Path(tmp_name)

        doc = fitz.open(path)
        try:
            if doc.needs_pass and password:
                doc.authenticate(password)

            total = doc.page_count
            opacity = max(0.05, min(1.0, config.opacity))

            for page_idx in range(total):
                _check_cancel(is_cancelled)
                page = doc.load_page(page_idx)
                page.wrap_contents()
                rect = page.rect
                anchor = _calculate_grid_anchor(rect, config.position)

                shape = page.new_shape()
                shape.insert_text(
                    anchor,
                    config.text.strip(),
                    fontsize=config.font_size,
                    color=config.color_rgb,
                    fill_opacity=opacity,
                    stroke_opacity=opacity,
                    morph=(anchor, fitz.Matrix(config.angle)),
                )
                shape.commit(overlay=True)

                pct = int(((page_idx + 1) / total) * 90)
                _emit_progress(
                    on_progress,
                    pct,
                    f"Estampando marca de agua en página {page_idx + 1}/{total}...",
                )

            doc.save(str(tmp_path), deflate=True)
            doc.close()
            _check_cancel(is_cancelled)
            shutil.move(str(tmp_path), str(safe_dest))
        except Exception:
            doc.close()
            tmp_path.unlink(missing_ok=True)
            raise

        _emit_progress(on_progress, 100, "Marca de agua aplicada.")
        final_bytes = safe_dest.stat().st_size
        return OperationResult(
            tool=ToolType.WATERMARK,
            output_files=[safe_dest],
            original_size_bytes=info.original_size_bytes,
            final_size_bytes=final_bytes,
            saved_percentage=0.0,
            message=f"Marca de agua '{config.text}' aplicada en {info.page_count} página(s).",
        )

    @staticmethod
    def render_signature_overlay_png(
        overlay: SignatureOverlay,
        page_width_pt: float,
        page_height_pt: float,
        scale: float = 2.0,
    ) -> bytes:
        """Genera una imagen PNG RGBA 100% transparente (alpha=0) con trazos negros (#000000) y sello opcional al derecho."""
        from PySide6.QtWidgets import QApplication

        if QApplication.instance() is None:
            _ = QApplication([])

        w_px = max(64, int(round(page_width_pt * scale)))
        h_px = max(64, int(round(page_height_pt * scale)))

        qimg = QImage(w_px, h_px, QImage.Format.Format_ARGB32)
        qimg.fill(Qt.GlobalColor.transparent)

        painter = QPainter(qimg)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)

        x0, y0, x1, y1 = overlay.normalized_rect
        rx = x0 * w_px
        ry = y0 * h_px
        rw = max(16.0, (x1 - x0) * w_px)
        rh = max(16.0, (y1 - y0) * h_px)
        target_qrect = QRectF(rx, ry, rw, rh)

        # 1. Imagen PNG de firma externa (si se adjuntó)
        if overlay.image_path is not None and Path(overlay.image_path).exists():
            ext_img = QImage(str(overlay.image_path))
            if not ext_img.isNull():
                scaled_ext = ext_img.scaled(
                    int(rw),
                    int(rh),
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )
                dx = rx + (rw - scaled_ext.width()) / 2.0
                dy = ry + (rh - scaled_ext.height()) / 2.0
                painter.drawImage(QPointF(dx, dy), scaled_ext)

        # 2. Sello predefinido opcional (sin fondo rosado opaco ni borde rectangular que recorte)
        if overlay.stamp_label and overlay.stamp_label.strip():
            stamp_text = f"✦ {overlay.stamp_label.strip().upper()} ✦"
            font = QFont("Georgia")
            font.setBold(True)
            font_px = max(12, int(rh * 0.36))
            font.setPixelSize(font_px)
            metrics = QFontMetricsF(font)
            text_w = metrics.horizontalAdvance(stamp_text)
            if text_w > rw * 0.92 and text_w > 0:
                font_px = max(10, int(font_px * (rw * 0.92) / text_w))
                font.setPixelSize(font_px)

            painter.setFont(font)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.setPen(QColor("#681D3A"))
            painter.drawText(
                target_qrect,
                int(Qt.AlignmentFlag.AlignCenter),
                stamp_text,
            )

        # 3. Trazos libres de firma manuscrita en negro puro (#000000)
        if overlay.freehand_strokes:
            pen = QPen(QColor(0, 0, 0, 255))
            pen.setWidthF(max(3.6, w_px * 0.0055))
            pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
            painter.setPen(pen)
            painter.setBrush(Qt.BrushStyle.NoBrush)

            for stroke in overlay.freehand_strokes:
                if len(stroke) >= 2:
                    path = QPainterPath()
                    path.moveTo(stroke[0][0] * w_px, stroke[0][1] * h_px)
                    for pt in stroke[1:]:
                        path.lineTo(pt[0] * w_px, pt[1] * h_px)
                    painter.drawPath(path)

        painter.end()

        buf = QBuffer()
        buf.open(QIODevice.OpenModeFlag.WriteOnly)
        qimg.save(buf, "PNG")
        return bytes(buf.data())

    @staticmethod
    def apply_signature_or_stamp(
        input_file: Path,
        output_path: Path,
        overlay: SignatureOverlay,
        password: str | None = None,
        on_progress: ProgressCallback | None = None,
        is_cancelled: CancelCheckCallback | None = None,
    ) -> OperationResult:
        """Estampa trazos libres de firma (#000000), sello opcional o imagen PNG con fondo 100% transparente y orientación exacta."""
        path = Path(input_file)
        info = inspect_pdf_file(path, password=password)
        if info.is_encrypted and not password:
            raise PDFEncryptedError(
                f"El archivo '{path.name}' está protegido con contraseña."
            )

        safe_dest = ensure_safe_output_path(
            path, output_path, default_suffix="_firmado"
        )
        fd, tmp_name = tempfile.mkstemp(
            prefix=".tmp_sign_", suffix=".pdf", dir=str(safe_dest.parent)
        )
        os.close(fd)
        tmp_path = Path(tmp_name)

        doc = fitz.open(path)
        try:
            if doc.needs_pass and password:
                doc.authenticate(password)

            if overlay.page_index < 0 or overlay.page_index >= doc.page_count:
                raise PDFStudioError(
                    f"Índice de página inválido para firma: {overlay.page_index}"
                )

            _check_cancel(is_cancelled)
            page = doc.load_page(overlay.page_index)
            # Aislar el estado gráfico CTM existente (evita inversión vertical de streams no envueltos)
            page.wrap_contents()

            visual_rect = page.rect
            _emit_progress(on_progress, 45, "Superponiendo firma/sello transparente en página...")

            has_strokes = bool(overlay.freehand_strokes)
            has_stamp = bool(overlay.stamp_label and overlay.stamp_label.strip())
            has_image = bool(overlay.image_path is not None and Path(overlay.image_path).exists())

            if has_strokes or has_stamp or has_image:
                overlay_png = PDFEngine.render_signature_overlay_png(
                    overlay=overlay,
                    page_width_pt=visual_rect.width,
                    page_height_pt=visual_rect.height,
                    scale=2.0,
                )
                unrotated_rect = (visual_rect * page.derotation_matrix).normalize()
                page.insert_image(
                    unrotated_rect,
                    stream=overlay_png,
                    rotate=page.rotation,
                    keep_proportion=False,
                    overlay=True,
                )

            doc.save(str(tmp_path), deflate=True)
            doc.close()
            _check_cancel(is_cancelled)
            shutil.move(str(tmp_path), str(safe_dest))
        except Exception:
            doc.close()
            tmp_path.unlink(missing_ok=True)
            raise

        _emit_progress(on_progress, 100, "Firma/sello aplicado correctamente.")
        final_bytes = safe_dest.stat().st_size
        return OperationResult(
            tool=ToolType.SIGN,
            output_files=[safe_dest],
            original_size_bytes=info.original_size_bytes,
            final_size_bytes=final_bytes,
            saved_percentage=0.0,
            message=f"Documento firmado guardado en '{safe_dest.name}'.",
        )


def _calculate_grid_anchor(
    rect: fitz.Rect, position: WatermarkPosition
) -> fitz.Point:
    """Calcula el punto de anclaje en la cuadrícula 3x3 dentro de una página."""
    margin_x = rect.width * 0.15
    margin_y = rect.height * 0.14
    cx = rect.width * 0.36
    cy = rect.height * 0.52

    mapping: dict[WatermarkPosition, tuple[float, float]] = {
        WatermarkPosition.TOP_LEFT: (margin_x, margin_y),
        WatermarkPosition.TOP_CENTER: (cx, margin_y),
        WatermarkPosition.TOP_RIGHT: (rect.width - margin_x * 2.2, margin_y),
        WatermarkPosition.MIDDLE_LEFT: (margin_x, cy),
        WatermarkPosition.CENTER: (cx, cy),
        WatermarkPosition.MIDDLE_RIGHT: (rect.width - margin_x * 2.2, cy),
        WatermarkPosition.BOTTOM_LEFT: (margin_x, rect.height - margin_y),
        WatermarkPosition.BOTTOM_CENTER: (cx, rect.height - margin_y),
        WatermarkPosition.BOTTOM_RIGHT: (
            rect.width - margin_x * 2.2,
            rect.height - margin_y,
        ),
    }
    x, y = mapping.get(position, (cx, cy))
    return fitz.Point(x, y)
