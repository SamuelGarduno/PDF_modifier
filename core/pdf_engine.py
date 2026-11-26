"""Motor síncrono puro de manipulación de documentos PDF con PyMuPDF (fitz) y pypdf."""

from __future__ import annotations

from collections.abc import Callable
import importlib
import io
import math
import os
from pathlib import Path
import shutil
import tempfile
from typing import TYPE_CHECKING, Any

from PySide6.QtCore import QBuffer, QIODevice, QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QFontMetricsF, QImage, QPainter, QPainterPath, QPen

if TYPE_CHECKING:
    import pymupdf as fitz
    from PIL import Image, ImageOps
    from pypdf import PdfReader, PdfWriter
    from pypdf.errors import PdfReadError, PdfStreamError


class _LazyModule:
    """Proxy perezoso para diferir imports pesados (pymupdf, Pillow) hasta su primer uso real."""

    def __init__(self, module_name: str, global_name: str) -> None:
        self._module_name = module_name
        self._global_name = global_name

    def _load(self) -> Any:
        mod = importlib.import_module(self._module_name)
        globals()[self._global_name] = mod
        return mod

    def __getattr__(self, item: str) -> Any:
        return getattr(self._load(), item)


fitz: Any = _LazyModule("pymupdf", "fitz")
Image: Any = _LazyModule("PIL.Image", "Image")
ImageOps: Any = _LazyModule("PIL.ImageOps", "ImageOps")


def _get_pypdf() -> tuple[Any, Any, Any, Any]:
    """Carga pypdf bajo demanda y almacena sus clases/excepciones en caché global."""
    pypdf_mod = importlib.import_module("pypdf")
    errors_mod = importlib.import_module("pypdf.errors")
    pdf_reader = pypdf_mod.PdfReader
    pdf_writer = pypdf_mod.PdfWriter
    pdf_read_err = errors_mod.PdfReadError
    pdf_stream_err = errors_mod.PdfStreamError
    globals().update(
        {
            "PdfReader": pdf_reader,
            "PdfWriter": pdf_writer,
            "PdfReadError": pdf_read_err,
            "PdfStreamError": pdf_stream_err,
        }
    )
    return pdf_reader, pdf_writer, pdf_read_err, pdf_stream_err


def __getattr__(name: str) -> Any:
    if name in {"PdfReader", "PdfWriter", "PdfReadError", "PdfStreamError"}:
        _get_pypdf()
        return globals()[name]
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

from core.exceptions import (
    InvalidPasswordError,
    PDFCorruptedError,
    PDFEncryptedError,
    PDFStudioError,
    TaskCancelledError,
)
from core.models import (
    BLANK_PAGE_MAX_INK_RATIO,
    BLANK_PAGE_NON_WHITE_THRESHOLD,
    BLANK_PAGE_RENDER_DPI,
    COMPRESSION_PROFILES,
    DECIMAL_MB_BYTES,
    SAMPLE_ESTIMATION_MAX_PAGES,
    SAMPLE_ESTIMATION_MIN_PAGES,
    SAMPLE_PIVOT_STEP_INDEX,
    SINGLE_LARGE_IMAGE_RATIO_THRESHOLD,
    TARGET_COMPRESSION_LADDER,
    TARGET_SIZE_MAX_MB,
    TARGET_SIZE_MIN_MB,
    TARGET_SIZE_SAFETY_FACTOR,
    TEXT_HEAVY_IMAGE_RATIO_THRESHOLD,
    CompressionLevel,
    CompressionProfile,
    ImageFormat,
    OperationResult,
    PageItemInstruction,
    QueuedFile,
    SignatureOverlay,
    TargetCompressionResult,
    TargetCompressionStep,
    TargetQualityLabel,
    ToolType,
    WatermarkConfig,
    WatermarkPosition,
    WeightAnatomy,
)
from core.range_parser import parse_page_ranges

ProgressCallback = Callable[[int, str], None]
CancelCheckCallback = Callable[[], bool]

QUEUE_THUMBNAIL_DPI = 60
DEFAULT_THUMBNAIL_DPI = 72
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

    if candidate.exists() and not allow_overwrite:
        counter = 1
        suffix = candidate.suffix or extension
        while True:
            alt = candidate.with_name(
                f"{candidate.stem} ({counter}){suffix}"
            )
            if not alt.exists() and alt.resolve() != resolved_input:
                alt.parent.mkdir(parents=True, exist_ok=True)
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
    PdfReaderCls, _, PdfReadErrorCls, PdfStreamErrorCls = _get_pypdf()
    path = Path(file_path)
    if not path.exists() or path.stat().st_size == 0:
        raise PDFCorruptedError(
            f"El archivo '{path.name}' no existe o está vacío (0 bytes)."
        )

    try:
        reader = PdfReaderCls(str(path))
    except (PdfReadErrorCls, PdfStreamErrorCls, ValueError, OSError) as exc:
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


def _format_size_es(size_bytes: int) -> str:
    """Formatea un tamaño en bytes con coma decimal en español (ej. '2,8 MB', '420 KB')."""
    if size_bytes < 1024:
        return f"{size_bytes} B"
    kb = size_bytes / 1024.0
    if kb < 1024.0:
        if kb >= 100.0 or abs(kb - round(kb)) < 0.05:
            return f"{int(round(kb))} KB"
        return f"{kb:.1f}".replace(".", ",") + " KB"
    mb = kb / 1024.0
    return f"{mb:.1f}".replace(".", ",") + " MB"


def compute_target_bytes(target_mb: float) -> int:
    """Valida el límite en MB y calcula el objetivo estricto (95% en base decimal 1 MB = 1,000,000 bytes)."""
    if not math.isfinite(target_mb):
        raise PDFStudioError("El tamaño objetivo en MB debe ser un número válido.")
    if target_mb < TARGET_SIZE_MIN_MB or target_mb > TARGET_SIZE_MAX_MB:
        raise PDFStudioError(
            f"El tamaño objetivo debe estar entre {TARGET_SIZE_MIN_MB:.1f} MB y {TARGET_SIZE_MAX_MB:.0f} MB."
        )
    return max(1, int(target_mb * DECIMAL_MB_BYTES * TARGET_SIZE_SAFETY_FACTOR))


def format_decimal_mb(size_bytes: int) -> str:
    """Formatea bytes en MB decimales (1 MB = 1,000,000 bytes) con punto decimal."""
    mb = max(0, int(size_bytes)) / float(DECIMAL_MB_BYTES)
    if mb >= 1.0:
        return f"{mb:.1f} MB"
    return f"{mb:.2f} MB"


class PDFEngine:
    """Motor principal para todas las operaciones sobre documentos PDF e imágenes."""

    @staticmethod
    def estimate_compression_savings(
        original_bytes: int, level: CompressionLevel
    ) -> tuple[int, float]:
        """Calcula el peso estimado final y porcentaje ahorrado de respaldo."""
        pct = COMPRESSION_ESTIMATES.get(level, 38.0)
        estimated_final = max(1, int(original_bytes * (1.0 - pct / 100.0)))
        return estimated_final, pct

    @staticmethod
    def has_digital_signature(
        file_path: Path, password: str | None = None
    ) -> bool:
        """Detecta si el PDF contiene campos u objetos de firma digital criptográfica (/Sig /ByteRange)."""
        path = Path(file_path)
        if not path.exists() or not path.is_file() or path.stat().st_size == 0:
            return False
        try:
            doc = fitz.open(path)
        except Exception:
            return False
        try:
            if doc.needs_pass:
                if not password or doc.authenticate(password) == 0:
                    return False
            for p_idx in range(min(doc.page_count, 50)):
                page = doc.load_page(p_idx)
                for w in page.widgets() or []:
                    if getattr(w, "field_type", None) == getattr(
                        fitz, "PDF_WIDGET_TYPE_SIGNATURE", 6
                    ):
                        return True
            xref_len = doc.xref_length()
            for xref in range(1, min(xref_len, 800)):
                try:
                    obj_str = doc.xref_object(xref, compressed=True)
                except Exception:
                    continue
                if "/ByteRange" in obj_str and (
                    "/Type/Sig" in obj_str
                    or "/Type /Sig" in obj_str
                    or "/FT/Sig" in obj_str
                    or "/FT /Sig" in obj_str
                    or "/SubFilter" in obj_str
                ):
                    return True
            return False
        finally:
            doc.close()

    @staticmethod
    def _collect_document_image_xrefs(
        doc: fitz.Document,
        is_cancelled: CancelCheckCallback | None = None,
    ) -> dict[int, dict[str, object]]:
        """Recorre el documento y agrupa todas las imágenes únicas por XREF calculando su máximo DPI efectivo."""
        xref_map: dict[int, dict[str, object]] = {}
        smask_xrefs: set[int] = set()

        for p_idx in range(doc.page_count):
            _check_cancel(is_cancelled)
            page = doc.load_page(p_idx)
            page_imgs = doc.get_page_images(p_idx)
            smask_by_xref: dict[int, int] = {}
            bpc_by_xref: dict[int, int] = {}
            cs_by_xref: dict[int, str] = {}
            filter_by_xref: dict[int, str] = {}

            for item in page_imgs:
                xr = int(item[0])
                sm = int(item[1])
                if sm > 0:
                    smask_xrefs.add(sm)
                    smask_by_xref[xr] = sm
                bpc_by_xref[xr] = int(item[4]) if len(item) > 4 else 8
                cs_by_xref[xr] = str(item[5]) if len(item) > 5 else ""
                filter_by_xref[xr] = str(item[8]) if len(item) > 8 else ""

            try:
                infos = page.get_image_info(xrefs=True)
            except Exception:
                infos = []

            for info in infos:
                xr = int(info.get("xref", 0) or 0)
                if xr <= 0:
                    continue
                w_px = int(info.get("width", 0) or 0)
                h_px = int(info.get("height", 0) or 0)
                bbox = info.get("bbox", (0.0, 0.0, 72.0, 72.0))
                bw_pt = max(1.0, abs(float(bbox[2]) - float(bbox[0])))
                bh_pt = max(1.0, abs(float(bbox[3]) - float(bbox[1])))
                eff_dpi_x = w_px / (bw_pt / 72.0)
                eff_dpi_y = h_px / (bh_pt / 72.0)
                eff_dpi = max(eff_dpi_x, eff_dpi_y)

                if xr not in xref_map:
                    try:
                        raw_bytes = doc.xref_stream_raw(xr)
                        raw_len = len(raw_bytes)
                    except Exception:
                        raw_len = 0
                    xref_map[xr] = {
                        "xref": xr,
                        "first_page": p_idx,
                        "smask": smask_by_xref.get(xr, 0),
                        "width": w_px,
                        "height": h_px,
                        "bpc": int(info.get("bpc", bpc_by_xref.get(xr, 8)) or 8),
                        "colorspace": cs_by_xref.get(xr, ""),
                        "filter": filter_by_xref.get(xr, ""),
                        "max_eff_dpi": eff_dpi,
                        "raw_len": raw_len,
                    }
                else:
                    prev_dpi = float(xref_map[xr]["max_eff_dpi"])
                    if eff_dpi > prev_dpi:
                        xref_map[xr]["max_eff_dpi"] = eff_dpi

        # Excluir cualquier xref que actúe como máscara de transparencia (SMask)
        for sm in smask_xrefs:
            xref_map.pop(sm, None)

        return xref_map

    @staticmethod
    def _decode_xref_to_qimage(
        doc: fitz.Document, meta: dict[str, object]
    ) -> QImage | None:
        """Decodifica un XREF de imagen (incluyendo CMYK/ICC/JPX) a un QImage independiente en memoria."""
        from PySide6.QtGui import QGuiApplication

        if QGuiApplication.instance() is None:
            _ = QGuiApplication([])

        xref = int(meta["xref"])
        raw_len = int(meta["raw_len"])
        if raw_len < 512:
            return None

        try:
            pix = fitz.Pixmap(doc, xref)
        except Exception:
            return None

        try:
            if pix.width < 16 or pix.height < 16 or pix.colorspace is None:
                return None

            base_channels = pix.n - pix.alpha
            if base_channels not in (1, 3):
                pix = fitz.Pixmap(fitz.csRGB, pix)
            if pix.alpha:
                pix = fitz.Pixmap(pix, 0)

            w, h, n = pix.width, pix.height, pix.n
            if n == 1:
                qimg = QImage(
                    pix.samples, w, h, pix.stride, QImage.Format.Format_Grayscale8
                ).copy()
            else:
                if n != 3:
                    pix = fitz.Pixmap(fitz.csRGB, pix)
                    w, h = pix.width, pix.height
                qimg = QImage(
                    pix.samples, w, h, pix.stride, QImage.Format.Format_RGB888
                ).copy()
            return qimg
        except Exception:
            return None
        finally:
            pix = None

    @staticmethod
    def _encode_qimage_for_profile(
        qimg: QImage,
        meta: dict[str, object],
        profile: CompressionProfile,
    ) -> tuple[bytes | None, int, int]:
        """Escala un QImage según el DPI objetivo del perfil y lo codifica en JPEG si reduce el tamaño real."""
        orig_w = qimg.width()
        orig_h = qimg.height()
        raw_len = int(meta["raw_len"])
        bpc = int(meta["bpc"])
        max_eff_dpi = float(meta["max_eff_dpi"])

        # Escaneos bitonales (1-bit B/N, JBIG2, CCITT): conservar intactos salvo en Extrema con DPI muy alto
        if bpc == 1 and (
            profile.level != CompressionLevel.EXTREME or max_eff_dpi <= 250.0
        ):
            return None, orig_w, orig_h

        target_w, target_h = orig_w, orig_h
        if max_eff_dpi > profile.dpi_threshold and max_eff_dpi > 1.0:
            ratio = profile.dpi_target / max_eff_dpi
            if ratio < 0.98:
                target_w = max(16, int(round(orig_w * ratio)))
                target_h = max(16, int(round(orig_h * ratio)))

        max_dim = max(target_w, target_h)
        if max_dim > profile.max_side_px:
            cap_ratio = profile.max_side_px / float(max_dim)
            target_w = max(16, int(round(target_w * cap_ratio)))
            target_h = max(16, int(round(target_h * cap_ratio)))

        work_img = (
            qimg.scaled(
                target_w,
                target_h,
                Qt.AspectRatioMode.IgnoreAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
            if (target_w != orig_w or target_h != orig_h)
            else qimg
        )

        buf = QBuffer()
        buf.open(QIODevice.OpenModeFlag.WriteOnly)
        ok = work_img.save(buf, "JPG", profile.jpeg_quality)
        if not ok:
            return None, orig_w, orig_h
        jpg_bytes = bytes(buf.data())

        if len(jpg_bytes) < raw_len - 64:
            return jpg_bytes, work_img.width(), work_img.height()
        return None, orig_w, orig_h

    @staticmethod
    def _scale_smask_if_needed(
        doc: fitz.Document, smask_xref: int, target_w: int, target_h: int
    ) -> None:
        """Escala la máscara de transparencia (SMask) cuando la imagen base cambia de resolución."""
        if smask_xref <= 0:
            return
        try:
            sm_pix = fitz.Pixmap(doc, smask_xref)
            if sm_pix.width == target_w and sm_pix.height == target_h:
                return
            if sm_pix.n != 1:
                sm_pix = fitz.Pixmap(fitz.csGRAY, sm_pix)
            qsm = QImage(
                sm_pix.samples,
                sm_pix.width,
                sm_pix.height,
                sm_pix.stride,
                QImage.Format.Format_Grayscale8,
            ).copy()
            sm_pix = None
            scaled_sm = qsm.scaled(
                target_w,
                target_h,
                Qt.AspectRatioMode.IgnoreAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            ).convertToFormat(QImage.Format.Format_Grayscale8)
            raw_rows = bytearray()
            ptr = memoryview(scaled_sm.constBits())
            bpl = scaled_sm.bytesPerLine()
            for r in range(target_h):
                raw_rows.extend(ptr[r * bpl : r * bpl + target_w])
            doc.update_stream(smask_xref, bytes(raw_rows), compress=True)
            doc.xref_set_key(smask_xref, "Width", str(target_w))
            doc.xref_set_key(smask_xref, "Height", str(target_h))
            doc.xref_set_key(smask_xref, "Filter", "/FlateDecode")
        except Exception:
            pass

    @staticmethod
    def _verify_compressed_pdf_integrity(
        comp_path: Path,
        orig_meta: dict[str, object],
    ) -> None:
        """Verifica que el PDF comprimido abra sin errores y conserve páginas, texto seleccionable, TOC, formularios y SMask."""
        try:
            out_doc = fitz.open(comp_path)
        except Exception as exc:
            raise PDFStudioError(
                "El archivo comprimido generado no superó la validación de apertura."
            ) from exc

        try:
            if out_doc.page_count != int(orig_meta["page_count"]):
                raise PDFStudioError(
                    "El número de páginas del PDF comprimido no coincide con el original."
                )

            if len(out_doc.get_toc()) != int(orig_meta["toc_count"]):
                raise PDFStudioError(
                    "Los marcadores (TOC) del PDF no se conservaron tras la compresión."
                )

            text_sample_pages: list[int] = list(orig_meta.get("text_pages", []))  # type: ignore[arg-type]
            for p_idx in text_sample_pages:
                if len(out_doc.load_page(p_idx).get_text("text").strip()) == 0:
                    raise PDFStudioError(
                        f"El texto seleccionable de la página {p_idx + 1} se perdió durante la compresión."
                    )

            smask_pages: list[int] = list(orig_meta.get("smask_pages", []))  # type: ignore[arg-type]
            for p_idx in smask_pages:
                imgs = out_doc.get_page_images(p_idx)
                if not any(int(item[1]) > 0 for item in imgs):
                    raise PDFStudioError(
                        f"La transparencia (SMask) en la página {p_idx + 1} no se conservó."
                    )
        finally:
            out_doc.close()

    @staticmethod
    def estimate_pdf_compression_for_all_levels(
        file_path: Path,
        password: str | None = None,
        is_cancelled: CancelCheckCallback | None = None,
    ) -> dict[str, dict[str, float | int | bool]]:
        """Calcula en segundo plano la estimación real basada en muestra para los 3 niveles (Extrema, Recomendada, Baja pérdida)."""
        path = Path(file_path)
        info = inspect_pdf_file(path, password=password)
        orig_bytes = info.original_size_bytes
        if info.is_encrypted and not password:
            return {
                lvl.value: {
                    "originalBytes": orig_bytes,
                    "estimatedBytes": orig_bytes,
                    "savedPct": 0.0,
                    "alreadyLight": True,
                }
                for lvl in CompressionLevel
            }

        doc = fitz.open(path)
        try:
            if doc.needs_pass and password:
                doc.authenticate(password)

            _check_cancel(is_cancelled)
            xref_map = PDFEngine._collect_document_image_xrefs(
                doc, is_cancelled=is_cancelled
            )
            total_img_raw = sum(int(m["raw_len"]) for m in xref_map.values())
            non_img_bytes = max(0, orig_bytes - total_img_raw)

            # Seleccionar muestra: hasta las 4 imágenes de mayor peso (o todas si hay <= 6 y son ligeras)
            sorted_metas = sorted(
                xref_map.values(), key=lambda m: int(m["raw_len"]), reverse=True
            )
            sample_count = min(len(sorted_metas), 4)
            sample_metas = sorted_metas[:sample_count]
            sample_orig_raw = sum(int(m["raw_len"]) for m in sample_metas)

            # Decodificar cada imagen de la muestra UNA sola vez a QImage y probar los 3 perfiles
            decoded_samples: list[tuple[dict[str, object], QImage]] = []
            for meta in sample_metas:
                _check_cancel(is_cancelled)
                qimg = PDFEngine._decode_xref_to_qimage(doc, meta)
                if qimg is not None:
                    decoded_samples.append((meta, qimg))

            # Si el archivo es pequeño/mediano (<= 2.5 MB) o dominado por vectores/estructura,
            # medir el ahorro estructural exacto de tobytes() sin tocar imágenes (~5-12 ms)
            struct_saved_by_level: dict[CompressionLevel, int] = {
                CompressionLevel.LOW_LOSS: int(non_img_bytes * 0.04),
                CompressionLevel.RECOMMENDED: int(non_img_bytes * 0.08),
                CompressionLevel.EXTREME: int(non_img_bytes * 0.18),
            }
            if orig_bytes <= 2_500_000:
                for lvl, prof in COMPRESSION_PROFILES.items():
                    _check_cancel(is_cancelled)
                    try:
                        probe_doc = fitz.open(path)
                        try:
                            if probe_doc.needs_pass and password:
                                probe_doc.authenticate(password)
                            if prof.strip_metadata:
                                probe_doc.set_metadata({})
                            if prof.strip_xml_metadata:
                                try:
                                    probe_doc.del_xml_metadata()
                                except Exception:
                                    pass
                            struct_bytes = len(
                                probe_doc.tobytes(
                                    garbage=prof.garbage,
                                    deflate=True,
                                    clean=True,
                                    deflate_images=True,
                                    deflate_fonts=True,
                                    use_objstms=prof.use_objstms,
                                )
                            )
                            struct_saved_by_level[lvl] = max(0, orig_bytes - struct_bytes)
                        finally:
                            probe_doc.close()
                    except Exception:
                        pass

            raw_est_by_level: dict[CompressionLevel, int] = {}
            for lvl in (
                CompressionLevel.LOW_LOSS,
                CompressionLevel.RECOMMENDED,
                CompressionLevel.EXTREME,
            ):
                _check_cancel(is_cancelled)
                prof = COMPRESSION_PROFILES[lvl]
                sample_saved = 0
                for meta, qimg in decoded_samples:
                    jpg_bytes, _, _ = PDFEngine._encode_qimage_for_profile(
                        qimg, meta, prof
                    )
                    if jpg_bytes is not None:
                        sample_saved += max(0, int(meta["raw_len"]) - len(jpg_bytes))

                if sample_orig_raw > 0 and total_img_raw > 0:
                    extrapolated_img_saved = int(
                        round(total_img_raw * (sample_saved / float(sample_orig_raw)))
                    )
                else:
                    extrapolated_img_saved = 0

                total_saved = struct_saved_by_level[lvl] + extrapolated_img_saved
                est_final = max(128, orig_bytes - total_saved)
                if est_final >= orig_bytes:
                    est_final = orig_bytes
                raw_est_by_level[lvl] = est_final

            # Garantizar monotonía estricta en la estimación: Extrema <= Recomendada <= Baja pérdida <= original
            est_low = min(orig_bytes, raw_est_by_level[CompressionLevel.LOW_LOSS])
            est_rec = min(est_low, raw_est_by_level[CompressionLevel.RECOMMENDED])
            est_ext = min(est_rec, raw_est_by_level[CompressionLevel.EXTREME])

            final_map = {
                CompressionLevel.LOW_LOSS: est_low,
                CompressionLevel.RECOMMENDED: est_rec,
                CompressionLevel.EXTREME: est_ext,
            }
            max_pct = (
                ((orig_bytes - est_ext) / float(orig_bytes)) * 100.0
                if orig_bytes > 0
                else 0.0
            )
            already_light = max_pct < 5.0

            out: dict[str, dict[str, float | int | bool]] = {}
            for lvl, est_b in final_map.items():
                pct = (
                    max(0.0, ((orig_bytes - est_b) / float(orig_bytes)) * 100.0)
                    if orig_bytes > 0
                    else 0.0
                )
                out[lvl.value] = {
                    "originalBytes": orig_bytes,
                    "estimatedBytes": est_b,
                    "savedPct": round(pct, 1),
                    "alreadyLight": already_light or pct < 5.0 or (orig_bytes - est_b) < 2048,
                }
            return out
        finally:
            doc.close()

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

            page = None
            pixmap = None
            try:
                page = doc.load_page(page_index)
                zoom = max(0.25, dpi / 72.0)
                matrix = fitz.Matrix(zoom, zoom)
                pixmap = page.get_pixmap(matrix=matrix, alpha=False)
                return bytes(pixmap.tobytes("png"))
            finally:
                del pixmap
                del page
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
        _, PdfWriterCls, _, _ = _get_pypdf()
        writer = PdfWriterCls()
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

        _, PdfWriterCls, _, _ = _get_pypdf()
        created_files: list[Path] = []
        try:
            if not split_into_separate_files:
                writer = PdfWriterCls()
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
                    writer = PdfWriterCls()
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

        _, PdfWriterCls, _, _ = _get_pypdf()
        writer = PdfWriterCls()
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
        """Comprime un PDF de forma monótona por nivel recodificando imágenes según su DPI efectivo y compactando flujos."""
        path = Path(input_file)
        info = inspect_pdf_file(path, password=password)
        if info.is_encrypted and not password:
            raise PDFEncryptedError(
                f"El archivo '{path.name}' está protegido con contraseña."
            )

        original_bytes = info.original_size_bytes
        profile = COMPRESSION_PROFILES.get(
            level, COMPRESSION_PROFILES[CompressionLevel.RECOMMENDED]
        )
        safe_dest = ensure_safe_output_path(
            path, output_path, default_suffix="_comprimido"
        )

        try:
            fd, tmp_name = tempfile.mkstemp(
                prefix=".tmp_compress_", suffix=".pdf", dir=str(safe_dest.parent)
            )
            os.close(fd)
        except OSError as exc:
            raise PDFStudioError(
                f"No se pudo crear archivo temporal en '{safe_dest.parent}': verifica permisos y espacio en disco."
            ) from exc

        tmp_path = Path(tmp_name)
        has_sig = PDFEngine.has_digital_signature(path, password=password)

        doc = fitz.open(path)
        try:
            if doc.needs_pass and password:
                doc.authenticate(password)

            total_pages = doc.page_count
            sample_check_indices = sorted(
                {0, total_pages // 2, max(0, total_pages - 1)}
            )
            text_pages = [
                p_idx
                for p_idx in sample_check_indices
                if len(doc.load_page(p_idx).get_text("text").strip()) > 0
            ]
            smask_pages = [
                p_idx
                for p_idx in sample_check_indices
                if any(int(item[1]) > 0 for item in doc.get_page_images(p_idx))
            ]
            orig_meta: dict[str, object] = {
                "page_count": total_pages,
                "toc_count": len(doc.get_toc()),
                "text_pages": text_pages,
                "smask_pages": smask_pages,
            }

            _emit_progress(
                on_progress, 10, f"Analizando {total_pages} página(s) e imágenes..."
            )
            _check_cancel(is_cancelled)

            xref_map = PDFEngine._collect_document_image_xrefs(
                doc, is_cancelled=is_cancelled
            )
            total_imgs = len(xref_map)

            for idx, (xref, meta) in enumerate(xref_map.items()):
                _check_cancel(is_cancelled)
                pct = 15 + int(((idx + 1) / max(1, total_imgs)) * 60)
                _emit_progress(
                    on_progress,
                    pct,
                    f"Optimizando imagen {idx + 1}/{total_imgs} (pág. {int(meta['first_page']) + 1}/{total_pages})...",
                )
                qimg = PDFEngine._decode_xref_to_qimage(doc, meta)
                if qimg is None:
                    continue
                jpg_bytes, new_w, new_h = PDFEngine._encode_qimage_for_profile(
                    qimg, meta, profile
                )
                qimg = None
                if jpg_bytes is None:
                    continue

                first_page_idx = int(meta["first_page"])
                smask_xref = int(meta["smask"])
                doc.load_page(first_page_idx).replace_image(xref, stream=jpg_bytes)
                if smask_xref > 0:
                    PDFEngine._scale_smask_if_needed(
                        doc, smask_xref, new_w, new_h
                    )
                    try:
                        doc.xref_set_key(xref, "SMask", f"{smask_xref} 0 R")
                    except Exception:
                        pass

            _emit_progress(on_progress, 82, "Compactando flujos y tabla de objetos...")
            _check_cancel(is_cancelled)

            if profile.strip_metadata:
                try:
                    doc.set_metadata({})
                except Exception:
                    pass
            if profile.strip_xml_metadata:
                try:
                    doc.del_xml_metadata()
                except Exception:
                    pass

            doc.save(
                str(tmp_path),
                garbage=profile.garbage,
                deflate=True,
                clean=True,
                deflate_images=True,
                deflate_fonts=True,
                use_objstms=profile.use_objstms,
            )
            doc.close()
            _check_cancel(is_cancelled)

            tmp_size = tmp_path.stat().st_size
            if tmp_size >= original_bytes:
                tmp_path.unlink(missing_ok=True)
                _emit_progress(
                    on_progress,
                    100,
                    "Este pliego ya está optimizado; no se puede reducir más sin perder calidad.",
                )
                return OperationResult(
                    tool=ToolType.COMPRESS,
                    output_files=[path],
                    original_size_bytes=original_bytes,
                    final_size_bytes=original_bytes,
                    saved_percentage=0.0,
                    message=(
                        f"Este pliego ya está optimizado; no se puede reducir más sin perder calidad "
                        f"(De {_format_size_es(original_bytes)} a {_format_size_es(original_bytes)}, -0%)."
                    ),
                )

            PDFEngine._verify_compressed_pdf_integrity(tmp_path, orig_meta)
            _check_cancel(is_cancelled)

            try:
                shutil.move(str(tmp_path), str(safe_dest))
            except PermissionError as exc:
                raise PDFStudioError(
                    f"El archivo de destino '{safe_dest.name}' está bloqueado por otro programa."
                ) from exc
            except OSError as exc:
                raise PDFStudioError(
                    f"No se pudo guardar '{safe_dest.name}': espacio insuficiente en disco o error de escritura."
                ) from exc
        except Exception:
            if not doc.is_closed:
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

        sig_notice = (
            " (Nota: la firma digital previa quedó invalidada al recomprimir)"
            if has_sig
            else ""
        )
        return OperationResult(
            tool=ToolType.COMPRESS,
            output_files=[safe_dest],
            original_size_bytes=original_bytes,
            final_size_bytes=final_bytes,
            saved_percentage=round(saved_pct, 2),
            message=(
                f"De {_format_size_es(original_bytes)} a {_format_size_es(final_bytes)} "
                f"(-{saved_pct:.0f}%){sig_notice}"
            ),
        )

    @staticmethod
    def _capture_pdf_integrity_meta(doc: fitz.Document) -> dict[str, object]:
        """Captura metadatos estructurales básicos para validar integridad tras recomprimir."""
        total_pages = doc.page_count
        sample_check_indices = sorted({0, total_pages // 2, max(0, total_pages - 1)})
        text_pages = [
            p_idx
            for p_idx in sample_check_indices
            if len(doc.load_page(p_idx).get_text("text").strip()) > 0
        ]
        smask_pages = [
            p_idx
            for p_idx in sample_check_indices
            if any(int(item[1]) > 0 for item in doc.get_page_images(p_idx))
        ]
        return {
            "page_count": total_pages,
            "toc_count": len(doc.get_toc()),
            "text_pages": text_pages,
            "smask_pages": smask_pages,
        }

    @staticmethod
    def analyze_pdf_weight_anatomy(
        file_path: Path,
        password: str | None = None,
        is_cancelled: CancelCheckCallback | None = None,
    ) -> WeightAnatomy:
        """Inspecciona XREFs únicos de imágenes para medir peso de imágenes frente a texto/vectores."""
        path = Path(file_path)
        info = inspect_pdf_file(path, password=password)
        if info.is_encrypted and not password:
            raise PDFEncryptedError(
                f"El archivo '{path.name}' está protegido con contraseña."
            )

        orig_bytes = info.original_size_bytes
        doc = fitz.open(path)
        try:
            if doc.needs_pass and password:
                doc.authenticate(password)
            _check_cancel(is_cancelled)
            xref_map = PDFEngine._collect_document_image_xrefs(
                doc, is_cancelled=is_cancelled
            )
            page_image_bytes: dict[int, int] = {}
            for p_idx in range(doc.page_count):
                _check_cancel(is_cancelled)
                seen_on_page: set[int] = set()
                p_sum = 0
                for item in doc.get_page_images(p_idx):
                    xr = int(item[0])
                    if xr in xref_map and xr not in seen_on_page:
                        seen_on_page.add(xr)
                        p_sum += int(xref_map[xr]["raw_len"])
                page_image_bytes[p_idx] = p_sum

            image_bytes = sum(int(m["raw_len"]) for m in xref_map.values())
            non_image_bytes = max(0, orig_bytes - image_bytes)
            image_ratio = (
                min(1.0, image_bytes / float(orig_bytes)) if orig_bytes > 0 else 0.0
            )
            is_text_heavy = image_ratio < TEXT_HEAVY_IMAGE_RATIO_THRESHOLD
            is_single_large_image = (
                doc.page_count == 1
                and len(xref_map) == 1
                and image_ratio >= SINGLE_LARGE_IMAGE_RATIO_THRESHOLD
            )
            if is_text_heavy:
                advisory = (
                    "Este PDF es principalmente texto/vectores (menos del 15% en imágenes): "
                    "el ahorro de peso será limitado."
                )
            elif is_single_large_image:
                advisory = (
                    "PDF de una sola imagen de alta resolución: se priorizará reducción directa de DPI."
                )
            else:
                advisory = ""

            return WeightAnatomy(
                original_bytes=orig_bytes,
                image_bytes=image_bytes,
                non_image_bytes=non_image_bytes,
                image_ratio=round(image_ratio, 4),
                unique_image_count=len(xref_map),
                page_count=doc.page_count,
                is_text_heavy=is_text_heavy,
                is_single_large_image=is_single_large_image,
                page_image_bytes=page_image_bytes,
                advisory_message=advisory,
            )
        finally:
            doc.close()

    @staticmethod
    def _select_sample_pages(
        anatomy: WeightAnatomy,
        max_pages: int = SAMPLE_ESTIMATION_MAX_PAGES,
    ) -> list[int]:
        """Selecciona hasta 5 páginas representativas priorizando la primera y las más pesadas en imágenes."""
        if anatomy.page_count <= 0:
            return []
        if anatomy.page_count <= max_pages:
            return list(range(anatomy.page_count))
        candidates = sorted(
            range(1, anatomy.page_count),
            key=lambda p: anatomy.page_image_bytes.get(p, 0),
            reverse=True,
        )
        selected = [0, *candidates[: max(0, max_pages - 1)]]
        return sorted(selected)

    @staticmethod
    def _encode_image_for_target_step(
        qimg: QImage,
        meta: dict[str, object],
        step: TargetCompressionStep,
        grayscale: bool = False,
    ) -> tuple[bytes | None, int, int]:
        """Escala y codifica una imagen para un escalón dado; opcionalmente convierte a escala de grises."""
        orig_w = qimg.width()
        orig_h = qimg.height()
        raw_len = int(meta["raw_len"])
        bpc = int(meta["bpc"])
        max_eff_dpi = float(meta["max_eff_dpi"])

        if bpc == 1 and not grayscale and (step.index < 4 or max_eff_dpi <= 250.0):
            return None, orig_w, orig_h

        target_w, target_h = orig_w, orig_h
        if max_eff_dpi > step.dpi_threshold and max_eff_dpi > 1.0:
            ratio = step.dpi_target / max_eff_dpi
            if ratio < 0.98:
                target_w = max(16, int(round(orig_w * ratio)))
                target_h = max(16, int(round(orig_h * ratio)))

        max_dim = max(target_w, target_h)
        if max_dim > step.max_side_px:
            cap_ratio = step.max_side_px / float(max_dim)
            target_w = max(16, int(round(target_w * cap_ratio)))
            target_h = max(16, int(round(target_h * cap_ratio)))

        if not grayscale:
            work_img = (
                qimg.scaled(
                    target_w,
                    target_h,
                    Qt.AspectRatioMode.IgnoreAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )
                if (target_w != orig_w or target_h != orig_h)
                else qimg
            )
            buf = QBuffer()
            buf.open(QIODevice.OpenModeFlag.WriteOnly)
            if not work_img.save(buf, "JPG", step.jpeg_quality):
                return None, orig_w, orig_h
            jpg_bytes = bytes(buf.data())
            if len(jpg_bytes) < raw_len - 64:
                return jpg_bytes, work_img.width(), work_img.height()
            return None, orig_w, orig_h

        rgb_img = qimg.convertToFormat(QImage.Format.Format_RGB888)
        pil_img = None
        gray_img = None
        enhanced_img = None
        resized_img = None
        try:
            pil_img = Image.frombytes(
                "RGB",
                (rgb_img.width(), rgb_img.height()),
                bytes(rgb_img.constBits()),
                "raw",
                "RGB",
                rgb_img.bytesPerLine(),
                1,
            )
            gray_img = ImageOps.grayscale(pil_img)
            enhanced_img = ImageOps.autocontrast(gray_img, cutoff=1)
            if target_w != orig_w or target_h != orig_h:
                resized_img = enhanced_img.resize(
                    (target_w, target_h), Image.Resampling.LANCZOS
                )
            else:
                resized_img = enhanced_img

            out_buf = io.BytesIO()
            resized_img.save(
                out_buf,
                format="JPEG",
                quality=step.jpeg_quality,
                optimize=True,
            )
            jpg_bytes = out_buf.getvalue()
            if len(jpg_bytes) < raw_len - 64:
                return jpg_bytes, target_w, target_h
            return None, orig_w, orig_h
        finally:
            if resized_img is not None and resized_img is not enhanced_img:
                resized_img.close()
            if enhanced_img is not None:
                enhanced_img.close()
            if gray_img is not None:
                gray_img.close()
            if pil_img is not None:
                pil_img.close()

    @staticmethod
    def _estimate_starting_step(
        doc: fitz.Document,
        xref_map: dict[int, dict[str, object]],
        anatomy: WeightAnatomy,
        target_bytes: int,
        grayscale: bool = False,
        is_cancelled: CancelCheckCallback | None = None,
    ) -> int:
        """Estima el escalón inicial usando anatomía o una muestra de hasta 5 páginas en RAM."""
        if anatomy.is_text_heavy and not grayscale:
            return 0
        if anatomy.is_single_large_image:
            return 3 if target_bytes < int(anatomy.original_bytes * 0.35) else 2
        if anatomy.page_count < SAMPLE_ESTIMATION_MIN_PAGES:
            return 3 if target_bytes < int(anatomy.original_bytes * 0.40) else 2

        sample_pages = PDFEngine._select_sample_pages(
            anatomy, max_pages=SAMPLE_ESTIMATION_MAX_PAGES
        )
        sample_xrefs: list[int] = []
        seen: set[int] = set()
        for p_idx in sample_pages:
            _check_cancel(is_cancelled)
            for item in doc.get_page_images(p_idx):
                xr = int(item[0])
                if xr in xref_map and xr not in seen:
                    seen.add(xr)
                    sample_xrefs.append(xr)

        sample_orig_raw = sum(int(xref_map[xr]["raw_len"]) for xr in sample_xrefs)
        if sample_orig_raw <= 0 or anatomy.image_bytes <= 0:
            return 0

        pivot_step = TARGET_COMPRESSION_LADDER[SAMPLE_PIVOT_STEP_INDEX]
        sample_new_bytes = 0
        for xr in sample_xrefs:
            _check_cancel(is_cancelled)
            meta = xref_map[xr]
            qimg = PDFEngine._decode_xref_to_qimage(doc, meta)
            if qimg is None:
                sample_new_bytes += int(meta["raw_len"])
                continue
            try:
                jpg_bytes, _, _ = PDFEngine._encode_image_for_target_step(
                    qimg, meta, pivot_step, grayscale=grayscale
                )
            finally:
                qimg = None
            sample_new_bytes += (
                len(jpg_bytes) if jpg_bytes is not None else int(meta["raw_len"])
            )

        ratio = sample_new_bytes / float(sample_orig_raw)
        extrapolated_img = int(round(anatomy.image_bytes * ratio))
        extrapolated_total = int(anatomy.non_image_bytes * 0.90) + extrapolated_img

        if extrapolated_total <= int(target_bytes * 0.55):
            return 1
        if extrapolated_total <= int(target_bytes * 0.85):
            return 2
        if extrapolated_total <= int(target_bytes * 1.15):
            return 3
        if extrapolated_total <= int(target_bytes * 1.65):
            return 4
        return 5

    @staticmethod
    def _compress_step_to_bytes(
        source: Path | bytes,
        step: TargetCompressionStep,
        password: str | None = None,
        grayscale: bool = False,
        xref_map: dict[int, dict[str, object]] | None = None,
        is_cancelled: CancelCheckCallback | None = None,
    ) -> bytes:
        """Ejecuta un escalón completo en RAM mediante doc.tobytes() sin archivos temporales en disco."""
        doc = (
            fitz.open(source)
            if isinstance(source, (Path, str))
            else fitz.open("pdf", source)
        )
        try:
            if doc.needs_pass and password:
                doc.authenticate(password)
            _check_cancel(is_cancelled)

            if not step.structural_only:
                active_xrefs = (
                    xref_map
                    if xref_map is not None
                    else PDFEngine._collect_document_image_xrefs(
                        doc, is_cancelled=is_cancelled
                    )
                )
                for xref, meta in active_xrefs.items():
                    _check_cancel(is_cancelled)
                    qimg = PDFEngine._decode_xref_to_qimage(doc, meta)
                    if qimg is None:
                        continue
                    try:
                        jpg_bytes, new_w, new_h = (
                            PDFEngine._encode_image_for_target_step(
                                qimg, meta, step, grayscale=grayscale
                            )
                        )
                    finally:
                        qimg = None
                    if jpg_bytes is None:
                        continue

                    first_page_idx = int(meta["first_page"])
                    smask_xref = int(meta["smask"])
                    doc.load_page(first_page_idx).replace_image(
                        xref, stream=jpg_bytes
                    )
                    if smask_xref > 0:
                        PDFEngine._scale_smask_if_needed(
                            doc, smask_xref, new_w, new_h
                        )
                        try:
                            doc.xref_set_key(xref, "SMask", f"{smask_xref} 0 R")
                        except Exception:
                            pass

            _check_cancel(is_cancelled)
            if step.strip_metadata:
                try:
                    doc.set_metadata({})
                except Exception:
                    pass
            if step.strip_xml_metadata:
                try:
                    doc.del_xml_metadata()
                except Exception:
                    pass

            return bytes(
                doc.tobytes(
                    garbage=step.garbage,
                    deflate=True,
                    clean=True,
                    deflate_images=True,
                    deflate_fonts=True,
                    use_objstms=step.use_objstms,
                )
            )
        finally:
            doc.close()

    @staticmethod
    def _write_pdf_bytes_atomically(
        pdf_bytes: bytes,
        destination: Path,
        orig_meta: dict[str, object] | None = None,
        is_cancelled: CancelCheckCallback | None = None,
    ) -> Path:
        """Escribe bytes PDF al destino de forma atómica y valida integridad opcionalmente."""
        destination.parent.mkdir(parents=True, exist_ok=True)
        try:
            fd, tmp_name = tempfile.mkstemp(
                prefix=".tmp_target_", suffix=".pdf", dir=str(destination.parent)
            )
            os.close(fd)
        except OSError as exc:
            raise PDFStudioError(
                f"No se pudo crear archivo temporal en '{destination.parent}': verifica permisos y espacio en disco."
            ) from exc

        tmp_path = Path(tmp_name)
        try:
            _check_cancel(is_cancelled)
            tmp_path.write_bytes(pdf_bytes)
            _check_cancel(is_cancelled)
            if orig_meta is not None:
                PDFEngine._verify_compressed_pdf_integrity(tmp_path, orig_meta)
            _check_cancel(is_cancelled)
            try:
                shutil.move(str(tmp_path), str(destination))
            except PermissionError as exc:
                raise PDFStudioError(
                    f"El archivo de destino '{destination.name}' está bloqueado por otro programa."
                ) from exc
            except OSError as exc:
                raise PDFStudioError(
                    f"No se pudo guardar '{destination.name}': espacio insuficiente en disco o error de escritura."
                ) from exc
            return destination
        except Exception:
            tmp_path.unlink(missing_ok=True)
            raise

    @staticmethod
    def compress_pdf_to_target_size(
        input_file: Path,
        output_path: Path,
        target_mb: float,
        password: str | None = None,
        grayscale: bool = False,
        on_progress: ProgressCallback | None = None,
        is_cancelled: CancelCheckCallback | None = None,
    ) -> TargetCompressionResult:
        """Comprime un PDF al límite objetivo (95% decimal) con muestra + búsqueda binaria en RAM."""
        target_bytes = compute_target_bytes(target_mb)
        path = Path(input_file)
        info = inspect_pdf_file(path, password=password)
        if info.is_encrypted and not password:
            raise PDFEncryptedError(
                f"El archivo '{path.name}' está protegido con contraseña."
            )

        original_bytes = info.original_size_bytes
        _emit_progress(on_progress, 5, "Analizando peso y anatomía del documento...")
        _check_cancel(is_cancelled)

        anatomy = PDFEngine.analyze_pdf_weight_anatomy(
            path, password=password, is_cancelled=is_cancelled
        )

        # Si el archivo ya cumple el 95% del límite (y no estamos en rescate B/N), avisar sin duplicar
        if original_bytes <= target_bytes and not grayscale:
            _emit_progress(
                on_progress,
                100,
                f"El documento ya cumple el límite ({format_decimal_mb(original_bytes)}).",
            )
            return TargetCompressionResult(
                met_target=True,
                already_within_limit=True,
                target_mb=target_mb,
                target_bytes=target_bytes,
                original_size_bytes=original_bytes,
                best_size_bytes=original_bytes,
                best_step_index=0,
                quality_label=TargetQualityLabel.VERY_GOOD.value,
                passes_executed=0,
                anatomy=anatomy,
                message=(
                    f"El archivo ya pesa {format_decimal_mb(original_bytes)} y cumple el límite "
                    f"({format_decimal_mb(target_bytes)}). No se creó copia innecesaria."
                ),
                comparison_text=f"{format_decimal_mb(original_bytes)} → {format_decimal_mb(original_bytes)}",
                best_pdf_bytes=None,
                operation_result=None,
                grayscale_applied=False,
            )

        has_sig = PDFEngine.has_digital_signature(path, password=password)
        doc = fitz.open(path)
        try:
            if doc.needs_pass and password:
                doc.authenticate(password)
            orig_meta = PDFEngine._capture_pdf_integrity_meta(doc)
            xref_map = PDFEngine._collect_document_image_xrefs(
                doc, is_cancelled=is_cancelled
            )
            _emit_progress(
                on_progress,
                15,
                "Estimando escalón óptimo mediante muestra representativa...",
            )
            start_idx = PDFEngine._estimate_starting_step(
                doc,
                xref_map,
                anatomy,
                target_bytes,
                grayscale=grayscale,
                is_cancelled=is_cancelled,
            )
        finally:
            doc.close()

        max_passes = 3
        low = 0
        high = len(TARGET_COMPRESSION_LADDER) - 1
        probe = start_idx
        tried: dict[int, bytes] = {}
        best_passing_idx: int | None = None
        best_overall_idx = start_idx
        best_overall_bytes: bytes | None = None
        passes = 0

        while passes < max_passes and low <= high:
            if probe in tried:
                break
            _check_cancel(is_cancelled)
            step = TARGET_COMPRESSION_LADDER[probe]
            passes += 1
            pct = 20 + int((passes / max_passes) * 65)
            _emit_progress(
                on_progress,
                pct,
                f"Pasada {passes}/{max_passes} — Nivel '{step.quality_label.value}' (escalón {probe + 1}/6)...",
            )
            candidate_bytes = PDFEngine._compress_step_to_bytes(
                path,
                step,
                password=password,
                grayscale=grayscale,
                xref_map=xref_map,
                is_cancelled=is_cancelled,
            )
            tried[probe] = candidate_bytes

            if best_overall_bytes is None or len(candidate_bytes) < len(
                best_overall_bytes
            ):
                best_overall_bytes = candidate_bytes
                best_overall_idx = probe

            if len(candidate_bytes) <= target_bytes:
                if best_passing_idx is None or probe < best_passing_idx:
                    best_passing_idx = probe
                high = probe - 1
            else:
                low = probe + 1

            if low > high:
                break

            # Garantizar evaluar el piso mínimo legible (5) en el último intento si nada cumplió aún
            if (
                passes == max_passes - 1
                and best_passing_idx is None
                and 5 not in tried
                and low <= 5 <= high
            ):
                probe = 5
            else:
                probe = (low + high) // 2

        if best_passing_idx is not None:
            winning_bytes = tried[best_passing_idx]
            winning_step = TARGET_COMPRESSION_LADDER[best_passing_idx]
            tried.clear()

            safe_dest = ensure_safe_output_path(
                path, output_path, default_suffix="_comprimido"
            )
            _emit_progress(on_progress, 92, "Guardando PDF optimizado en disco...")
            PDFEngine._write_pdf_bytes_atomically(
                winning_bytes,
                safe_dest,
                orig_meta=orig_meta,
                is_cancelled=is_cancelled,
            )
            final_bytes = safe_dest.stat().st_size
            saved_pct = (
                max(0.0, ((original_bytes - final_bytes) / original_bytes) * 100.0)
                if original_bytes > 0
                else 0.0
            )
            comparison = (
                f"{format_decimal_mb(original_bytes)} → {format_decimal_mb(final_bytes)}"
            )
            sig_notice = (
                " (Nota: la firma digital previa quedó invalidada)"
                if has_sig
                else ""
            )
            op_res = OperationResult(
                tool=ToolType.COMPRESS,
                output_files=[safe_dest],
                original_size_bytes=original_bytes,
                final_size_bytes=final_bytes,
                saved_percentage=round(saved_pct, 2),
                message=(
                    f"{comparison} · Calidad {winning_step.quality_label.value}"
                    f"{sig_notice}"
                ),
            )
            _emit_progress(on_progress, 100, "Compresión a tamaño objetivo completada.")
            return TargetCompressionResult(
                met_target=True,
                already_within_limit=False,
                target_mb=target_mb,
                target_bytes=target_bytes,
                original_size_bytes=original_bytes,
                best_size_bytes=final_bytes,
                best_step_index=best_passing_idx,
                quality_label=winning_step.quality_label.value,
                passes_executed=passes,
                anatomy=anatomy,
                message=op_res.message,
                comparison_text=comparison,
                best_pdf_bytes=None,
                operation_result=op_res,
                grayscale_applied=grayscale,
            )

        assert best_overall_bytes is not None
        best_size = len(best_overall_bytes)
        tried.clear()
        missing_bytes = max(1, best_size - target_bytes)
        best_step = TARGET_COMPRESSION_LADDER[best_overall_idx]
        msg = (
            f"Mejor intento: {format_decimal_mb(best_size)} — "
            f"faltan {format_decimal_mb(missing_bytes)} para el límite"
        )
        _emit_progress(
            on_progress,
            100,
            "Se alcanzó el piso de legibilidad sin llegar al límite.",
        )
        return TargetCompressionResult(
            met_target=False,
            already_within_limit=False,
            target_mb=target_mb,
            target_bytes=target_bytes,
            original_size_bytes=original_bytes,
            best_size_bytes=best_size,
            best_step_index=best_overall_idx,
            quality_label=best_step.quality_label.value,
            passes_executed=passes,
            anatomy=anatomy,
            message=msg,
            comparison_text=f"{format_decimal_mb(original_bytes)} → {format_decimal_mb(best_size)}",
            best_pdf_bytes=best_overall_bytes,
            operation_result=None,
            grayscale_applied=grayscale,
        )

    @staticmethod
    def save_pdf_bytes_safely(
        pdf_bytes: bytes,
        input_file: Path,
        output_path: Path,
        original_size_bytes: int,
        quality_label: str = "",
        is_cancelled: CancelCheckCallback | None = None,
    ) -> OperationResult:
        """Guarda en disco un intento previo en RAM sin sobrescribir el original."""
        if not pdf_bytes:
            raise PDFStudioError("No hay contenido PDF generado para guardar.")
        path = Path(input_file)
        safe_dest = ensure_safe_output_path(
            path, output_path, default_suffix="_comprimido"
        )
        PDFEngine._write_pdf_bytes_atomically(
            pdf_bytes, safe_dest, orig_meta=None, is_cancelled=is_cancelled
        )
        final_bytes = safe_dest.stat().st_size
        saved_pct = (
            max(0.0, ((original_size_bytes - final_bytes) / original_size_bytes) * 100.0)
            if original_size_bytes > 0
            else 0.0
        )
        comparison = (
            f"{format_decimal_mb(original_size_bytes)} → {format_decimal_mb(final_bytes)}"
        )
        q_suffix = f" · Calidad {quality_label}" if quality_label else ""
        return OperationResult(
            tool=ToolType.COMPRESS,
            output_files=[safe_dest],
            original_size_bytes=original_size_bytes,
            final_size_bytes=final_bytes,
            saved_percentage=round(saved_pct, 2),
            message=f"{comparison}{q_suffix}",
        )

    @staticmethod
    def compress_pdf_grayscale_rescue(
        input_file: Path,
        output_path: Path,
        target_mb: float,
        password: str | None = None,
        on_progress: ProgressCallback | None = None,
        is_cancelled: CancelCheckCallback | None = None,
    ) -> TargetCompressionResult:
        """Re-procesa imágenes a escala de grises y alto contraste (Pillow) y re-evalúa contra el límite."""
        return PDFEngine.compress_pdf_to_target_size(
            input_file=input_file,
            output_path=output_path,
            target_mb=target_mb,
            password=password,
            grayscale=True,
            on_progress=on_progress,
            is_cancelled=is_cancelled,
        )

    @staticmethod
    def detect_blank_pages(
        file_path: Path,
        password: str | None = None,
        dpi: int = BLANK_PAGE_RENDER_DPI,
        non_white_threshold: int = BLANK_PAGE_NON_WHITE_THRESHOLD,
        max_ink_ratio: float = BLANK_PAGE_MAX_INK_RATIO,
        is_cancelled: CancelCheckCallback | None = None,
    ) -> list[int]:
        """Detecta páginas vacías renderizando a 36 DPI y midiendo densidad de píxeles no blancos."""
        path = Path(file_path)
        info = inspect_pdf_file(path, password=password)
        if info.is_encrypted and not password:
            raise PDFEncryptedError(
                f"El archivo '{path.name}' está protegido con contraseña."
            )

        zoom = max(0.25, dpi / 72.0)
        matrix = fitz.Matrix(zoom, zoom)
        blank_indices: list[int] = []
        doc = fitz.open(path)
        try:
            if doc.needs_pass and password:
                doc.authenticate(password)
            for p_idx in range(doc.page_count):
                _check_cancel(is_cancelled)
                page = None
                pix = None
                gray_pix = None
                pil_img = None
                try:
                    page = doc.load_page(p_idx)
                    pix = page.get_pixmap(matrix=matrix, alpha=False)
                    gray_pix = (
                        pix if pix.n == 1 else fitz.Pixmap(fitz.csGRAY, pix)
                    )
                    pil_img = Image.frombytes(
                        "L",
                        (gray_pix.width, gray_pix.height),
                        bytes(gray_pix.samples),
                    )
                    hist = pil_img.histogram()
                    total_px = max(1, gray_pix.width * gray_pix.height)
                    non_white_px = sum(hist[:non_white_threshold])
                    if (non_white_px / float(total_px)) <= max_ink_ratio:
                        blank_indices.append(p_idx)
                finally:
                    if pil_img is not None:
                        pil_img.close()
                    del gray_pix
                    del pix
                    del page
            return blank_indices
        finally:
            doc.close()

    @staticmethod
    def remove_blank_pages_and_compress(
        input_file: Path,
        output_path: Path,
        target_mb: float,
        password: str | None = None,
        on_progress: ProgressCallback | None = None,
        is_cancelled: CancelCheckCallback | None = None,
    ) -> TargetCompressionResult:
        """Descarta páginas en blanco detectadas a 36 DPI y recalcula compresión al límite objetivo."""
        path = Path(input_file)
        _emit_progress(on_progress, 10, "Buscando páginas en blanco a 36 DPI...")
        blank_indices = PDFEngine.detect_blank_pages(
            path, password=password, is_cancelled=is_cancelled
        )
        if not blank_indices:
            raise PDFStudioError(
                "No se detectaron páginas en blanco en este documento."
            )

        doc = fitz.open(path)
        try:
            if doc.needs_pass and password:
                doc.authenticate(password)
            total_pages = doc.page_count
            if len(blank_indices) >= total_pages:
                raise PDFStudioError(
                    "Todas las páginas del documento están en blanco; no se generó un PDF vacío."
                )
            keep_indices = [
                idx for idx in range(total_pages) if idx not in set(blank_indices)
            ]

            with tempfile.TemporaryDirectory(prefix="coquette_noblanks_") as tmp_dir:
                cleaned_pdf = Path(tmp_dir) / f"{path.stem}_sin_blancos.pdf"
                cleaned_doc = fitz.open()
                try:
                    for k_idx in keep_indices:
                        _check_cancel(is_cancelled)
                        cleaned_doc.insert_pdf(doc, from_page=k_idx, to_page=k_idx)
                    cleaned_doc.save(str(cleaned_pdf), deflate=True)
                finally:
                    cleaned_doc.close()

                res = PDFEngine.compress_pdf_to_target_size(
                    input_file=cleaned_pdf,
                    output_path=output_path,
                    target_mb=target_mb,
                    password=None,
                    on_progress=on_progress,
                    is_cancelled=is_cancelled,
                )
                res.removed_blank_pages = len(blank_indices)
                # Conservar el peso original real del archivo fuente para la comparativa
                res.original_size_bytes = path.stat().st_size
                res.comparison_text = (
                    f"{format_decimal_mb(res.original_size_bytes)} → "
                    f"{format_decimal_mb(res.best_size_bytes)}"
                )
                if res.operation_result is not None:
                    orig_b = res.original_size_bytes
                    final_b = res.operation_result.final_size_bytes
                    res.operation_result.original_size_bytes = orig_b
                    res.operation_result.saved_percentage = round(
                        max(0.0, ((orig_b - final_b) / orig_b) * 100.0)
                        if orig_b > 0
                        else 0.0,
                        2,
                    )
                    res.operation_result.message = (
                        f"{res.comparison_text} · Calidad {res.quality_label} "
                        f"({len(blank_indices)} pág. en blanco quitadas)"
                    )
                    res.message = res.operation_result.message
                return res
        finally:
            doc.close()

    @staticmethod
    def split_pdf_to_target_size(
        input_file: Path,
        output_path: Path,
        target_mb: float,
        password: str | None = None,
        source_pdf_bytes: bytes | None = None,
        on_progress: ProgressCallback | None = None,
        is_cancelled: CancelCheckCallback | None = None,
    ) -> OperationResult:
        """Divide un PDF en volúmenes consecutivos (_parte1.pdf, _parte2.pdf...) bajo target_bytes."""
        target_bytes = compute_target_bytes(target_mb)
        path = Path(input_file)
        info = inspect_pdf_file(path, password=password)
        if info.is_encrypted and not password:
            raise PDFEncryptedError(
                f"El archivo '{path.name}' está protegido con contraseña."
            )

        base_dest = ensure_safe_output_path(
            path, output_path, default_suffix="_parte"
        )
        base_stem = base_dest.stem
        if base_stem.endswith("_parte"):
            base_stem = base_stem[: -len("_parte")] or path.stem

        src_doc = (
            fitz.open("pdf", source_pdf_bytes)
            if source_pdf_bytes is not None
            else fitz.open(path)
        )
        created_files: list[Path] = []
        oversized_single_pages: list[int] = []

        def _build_slice_bytes(start_idx: int, end_idx: int) -> bytes:
            part_doc = fitz.open()
            try:
                part_doc.insert_pdf(src_doc, from_page=start_idx, to_page=end_idx)
                return bytes(
                    part_doc.tobytes(garbage=4, deflate=True, use_objstms=1)
                )
            finally:
                part_doc.close()

        try:
            if source_pdf_bytes is None and src_doc.needs_pass and password:
                src_doc.authenticate(password)

            total_pages = src_doc.page_count
            if total_pages < 1:
                raise PDFCorruptedError(f"El PDF '{path.name}' no tiene páginas.")

            start_idx = 0
            part_num = 1
            while start_idx < total_pages:
                _check_cancel(is_cancelled)
                # Probar el tramo restante completo primero para evitar búsquedas si ya cabe
                full_rem_bytes = _build_slice_bytes(start_idx, total_pages - 1)
                if len(full_rem_bytes) <= target_bytes:
                    chosen_end = total_pages - 1
                    chosen_bytes = full_rem_bytes
                else:
                    # Búsqueda binaria del mayor end_idx en [start_idx, total_pages - 2] que quepa
                    low = start_idx
                    high = total_pages - 2
                    chosen_end = start_idx
                    chosen_bytes = _build_slice_bytes(start_idx, start_idx)
                    if len(chosen_bytes) > target_bytes:
                        oversized_single_pages.append(start_idx + 1)
                    else:
                        low = start_idx + 1
                        while low <= high:
                            _check_cancel(is_cancelled)
                            mid = (low + high) // 2
                            cand_bytes = _build_slice_bytes(start_idx, mid)
                            if len(cand_bytes) <= target_bytes:
                                chosen_end = mid
                                chosen_bytes = cand_bytes
                                low = mid + 1
                            else:
                                high = mid - 1

                part_dest = ensure_safe_output_path(
                    path,
                    base_dest.with_name(f"{base_stem}_parte{part_num}.pdf"),
                    default_suffix=f"_parte{part_num}",
                )
                PDFEngine._write_pdf_bytes_atomically(
                    chosen_bytes, part_dest, orig_meta=None, is_cancelled=is_cancelled
                )
                created_files.append(part_dest)

                pct = int(((chosen_end + 1) / total_pages) * 95)
                _emit_progress(
                    on_progress,
                    pct,
                    f"Creada parte {part_num} (págs. {start_idx + 1}-{chosen_end + 1})...",
                )
                start_idx = chosen_end + 1
                part_num += 1

            _emit_progress(on_progress, 100, "División en partes completada.")
            final_total = sum(f.stat().st_size for f in created_files if f.exists())
            warn_note = (
                f" (Nota: pág. {', '.join(map(str, oversized_single_pages))} excede por sí sola el límite)"
                if oversized_single_pages
                else ""
            )
            return OperationResult(
                tool=ToolType.COMPRESS,
                output_files=created_files,
                original_size_bytes=info.original_size_bytes,
                final_size_bytes=final_total,
                saved_percentage=0.0,
                message=(
                    f"Se dividió en {len(created_files)} parte(s) bajo "
                    f"{format_decimal_mb(target_bytes)}{warn_note}."
                ),
            )
        except Exception:
            for partial in created_files:
                partial.unlink(missing_ok=True)
            raise
        finally:
            src_doc.close()

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

        _, PdfWriterCls, _, _ = _get_pypdf()
        writer = PdfWriterCls()
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

        _, PdfWriterCls, _, _ = _get_pypdf()
        writer = PdfWriterCls()
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
                page = None
                pix = None
                try:
                    page = doc.load_page(page_idx)
                    pix = page.get_pixmap(matrix=matrix, alpha=False)
                    img_path = out_folder / f"{path.stem}_pag_{page_idx + 1:03d}.{ext}"
                    pix.save(str(img_path))
                    created_files.append(img_path)
                finally:
                    del pix
                    del page

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
    def _filter_stroke_points(
        stroke: list[tuple[float, float]],
        page_width_pt: float,
        page_height_pt: float,
        min_dist_pt: float = 1.2,
    ) -> list[tuple[float, float]]:
        """Descarta puntos intermedios a menos de ~1.5 px/pt para suavizar el trazo."""
        if len(stroke) <= 2:
            return list(stroke)
        filtered: list[tuple[float, float]] = [stroke[0]]
        for pt in stroke[1:-1]:
            last = filtered[-1]
            dx = (pt[0] - last[0]) * page_width_pt
            dy = (pt[1] - last[1]) * page_height_pt
            if math.hypot(dx, dy) >= min_dist_pt:
                filtered.append(pt)
        filtered.append(stroke[-1])
        return filtered

    @staticmethod
    def _visual_point_to_shape(page: fitz.Page, nx: float, ny: float) -> fitz.Point:
        """Mapea un punto normalizado (0..1) visual al espacio de page.new_shape() respetando /Rotate y CropBox."""
        r = page.rect
        vx = r.x0 + nx * r.width
        vy = r.y0 + ny * r.height
        pt = fitz.Point(vx, vy) * page.derotation_matrix
        if page.rotation % 360 != 0:
            cb = page.cropbox
            mb = page.mediabox
            pt = fitz.Point(pt.x + cb.x0, pt.y - (mb.y1 - cb.y1))
        return pt

    @staticmethod
    def _visual_rect_to_unrotated(
        page: fitz.Page, norm_rect: tuple[float, float, float, float]
    ) -> fitz.Rect:
        """Mapea un rectángulo normalizado (0..1) visual a fitz.Rect no rotado respetando /Rotate y CropBox."""
        r = page.rect
        nx0, ny0, nx1, ny1 = norm_rect
        vis_rect = fitz.Rect(
            r.x0 + nx0 * r.width,
            r.y0 + ny0 * r.height,
            r.x0 + nx1 * r.width,
            r.y0 + ny1 * r.height,
        )
        unrot_rect = (vis_rect * page.derotation_matrix).normalize()
        if page.rotation % 360 != 0:
            cb = page.cropbox
            mb = page.mediabox
            dx = cb.x0
            dy = -(mb.y1 - cb.y1)
            unrot_rect = fitz.Rect(
                unrot_rect.x0 + dx,
                unrot_rect.y0 + dy,
                unrot_rect.x1 + dx,
                unrot_rect.y1 + dy,
            )
        return unrot_rect

    @staticmethod
    def _draw_vector_strokes_on_page(
        page: fitz.Page, overlay: SignatureOverlay
    ) -> None:
        """Escribe los trazos libres en el PDF como curvas vectoriales Bézier reales con extremos redondeados."""
        if not overlay.freehand_strokes:
            return
        vis_w = max(1.0, page.rect.width)
        vis_h = max(1.0, page.rect.height)

        for idx, raw_stroke in enumerate(overlay.freehand_strokes):
            pts = PDFEngine._filter_stroke_points(raw_stroke, vis_w, vis_h)
            if len(pts) < 2:
                continue

            shape_pts = [
                PDFEngine._visual_point_to_shape(page, p[0], p[1]) for p in pts
            ]
            shape = page.new_shape()
            if len(shape_pts) == 2:
                shape.draw_line(shape_pts[0], shape_pts[1])
            else:
                mid_first = fitz.Point(
                    (shape_pts[0].x + shape_pts[1].x) * 0.5,
                    (shape_pts[0].y + shape_pts[1].y) * 0.5,
                )
                shape.draw_line(shape_pts[0], mid_first)
                cur = mid_first
                for i in range(1, len(shape_pts) - 1):
                    ctrl = shape_pts[i]
                    nxt = shape_pts[i + 1]
                    mid = fitz.Point((ctrl.x + nxt.x) * 0.5, (ctrl.y + nxt.y) * 0.5)
                    # Elevación exacta de grado cuadrático (cur, ctrl, mid) a cúbico (cur, cp1, cp2, mid)
                    cp1 = fitz.Point(
                        cur.x + (2.0 / 3.0) * (ctrl.x - cur.x),
                        cur.y + (2.0 / 3.0) * (ctrl.y - cur.y),
                    )
                    cp2 = fitz.Point(
                        mid.x + (2.0 / 3.0) * (ctrl.x - mid.x),
                        mid.y + (2.0 / 3.0) * (ctrl.y - mid.y),
                    )
                    shape.draw_bezier(cur, cp1, cp2, mid)
                    cur = mid
                shape.draw_line(cur, shape_pts[-1])

            base_pt = (
                overlay.stroke_widths_pt[idx]
                if idx < len(overlay.stroke_widths_pt)
                else overlay.default_stroke_width_pt
            )
            width_pt = max(1.4, float(base_pt) * (vis_w / 595.0))
            shape.finish(
                color=(0.0, 0.0, 0.0),
                width=width_pt,
                lineCap=1,
                lineJoin=1,
            )
            shape.commit(overlay=True)

    @staticmethod
    def _insert_signature_png_on_page(
        page: fitz.Page, overlay: SignatureOverlay
    ) -> None:
        """Incrusta la firma PNG con canal alfa transparente en el rectángulo normalizado exacto."""
        if overlay.image_path is None or not Path(overlay.image_path).exists():
            return
        ext_img = QImage(str(overlay.image_path))
        if ext_img.isNull():
            return

        ext_img = ext_img.convertToFormat(QImage.Format.Format_ARGB32)
        max_dim = max(ext_img.width(), ext_img.height())
        if max_dim > 2400:
            ext_img = ext_img.scaled(
                2400,
                2400,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )

        buf = QBuffer()
        buf.open(QIODevice.OpenModeFlag.WriteOnly)
        ext_img.save(buf, "PNG")
        png_stream = bytes(buf.data())

        target_norm = (
            overlay.image_normalized_rect
            if overlay.image_normalized_rect is not None
            else overlay.normalized_rect
        )
        unrot_rect = PDFEngine._visual_rect_to_unrotated(page, target_norm)
        page.insert_image(
            unrot_rect,
            stream=png_stream,
            rotate=page.rotation,
            keep_proportion=True,
            overlay=True,
        )

    @staticmethod
    def render_signature_overlay_png(
        overlay: SignatureOverlay,
        page_width_pt: float,
        page_height_pt: float,
        scale: float = 2.0,
    ) -> bytes:
        """Genera una imagen PNG RGBA 100% transparente (alpha=0) con trazos negros (#000000) y sello opcional."""
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
                ix0, iy0, ix1, iy1 = (
                    overlay.image_normalized_rect
                    if overlay.image_normalized_rect is not None
                    else overlay.normalized_rect
                )
                irx = ix0 * w_px
                iry = iy0 * h_px
                irw = max(16.0, (ix1 - ix0) * w_px)
                irh = max(16.0, (iy1 - iy0) * h_px)
                scaled_ext = ext_img.scaled(
                    int(irw),
                    int(irh),
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )
                dx = irx + (irw - scaled_ext.width()) / 2.0
                dy = iry + (irh - scaled_ext.height()) / 2.0
                painter.drawImage(QPointF(dx, dy), scaled_ext)

        # 2. Sello opcional con texto libre (sin fondo rosado opaco ni borde rectangular que recorte)
        if overlay.stamp_label and overlay.stamp_label.strip():
            stamp_text = overlay.stamp_label.strip()
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

        # 3. Trazos libres de firma manuscrita en negro puro (#000000) con curvas cuadráticas Bézier
        if overlay.freehand_strokes:
            painter.setBrush(Qt.BrushStyle.NoBrush)
            for idx, raw_stroke in enumerate(overlay.freehand_strokes):
                pts = PDFEngine._filter_stroke_points(
                    raw_stroke, page_width_pt, page_height_pt
                )
                if len(pts) < 2:
                    continue
                base_pt = (
                    overlay.stroke_widths_pt[idx]
                    if idx < len(overlay.stroke_widths_pt)
                    else overlay.default_stroke_width_pt
                )
                pen = QPen(QColor(0, 0, 0, 255))
                pen.setWidthF(max(2.4 * scale, (float(base_pt) / 595.0) * w_px))
                pen.setCapStyle(Qt.PenCapStyle.RoundCap)
                pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
                painter.setPen(pen)

                path = QPainterPath()
                p0x, p0y = pts[0][0] * w_px, pts[0][1] * h_px
                path.moveTo(p0x, p0y)
                if len(pts) == 2:
                    path.lineTo(pts[1][0] * w_px, pts[1][1] * h_px)
                else:
                    p1x, p1y = pts[1][0] * w_px, pts[1][1] * h_px
                    path.lineTo((p0x + p1x) * 0.5, (p0y + p1y) * 0.5)
                    for i in range(1, len(pts) - 1):
                        cx, cy = pts[i][0] * w_px, pts[i][1] * h_px
                        nx, ny = pts[i + 1][0] * w_px, pts[i + 1][1] * h_px
                        path.quadTo(cx, cy, (cx + nx) * 0.5, (cy + ny) * 0.5)
                    path.lineTo(pts[-1][0] * w_px, pts[-1][1] * h_px)
                painter.drawPath(path)

        painter.end()

        buf = QBuffer()
        buf.open(QIODevice.OpenModeFlag.WriteOnly)
        qimg.save(buf, "PNG")
        return bytes(buf.data())

    @staticmethod
    def _verify_saved_signatures_in_pdf(
        original_path: Path,
        saved_path: Path,
        overlays: list[SignatureOverlay],
        password: str | None = None,
    ) -> None:
        """Reabre el PDF guardado, renderiza cada página modificada y confirma que la firma/trazo aparece donde se esperaba."""
        orig_doc = fitz.open(original_path)
        saved_doc = fitz.open(saved_path)
        try:
            if orig_doc.needs_pass and password:
                orig_doc.authenticate(password)
            if saved_doc.needs_pass and password:
                saved_doc.authenticate(password)

            for ov in overlays:
                has_strokes = any(len(s) >= 2 for s in ov.freehand_strokes)
                has_stamp = bool(ov.stamp_label and ov.stamp_label.strip())
                has_image = bool(
                    ov.image_path is not None and Path(ov.image_path).exists()
                )
                if not (has_strokes or has_stamp or has_image):
                    continue

                p_orig = None
                p_saved = None
                pix_orig = None
                pix_saved = None
                try:
                    p_orig = orig_doc.load_page(ov.page_index)
                    p_saved = saved_doc.load_page(ov.page_index)
                    pix_orig = p_orig.get_pixmap(dpi=96, alpha=False)
                    pix_saved = p_saved.get_pixmap(dpi=96, alpha=False)
                    if pix_orig.samples == pix_saved.samples:
                        raise PDFStudioError(
                            f"La verificación post-guardado detectó que la página {ov.page_index + 1} no reflejó la firma."
                        )
                finally:
                    del pix_orig
                    del pix_saved
                    del p_orig
                    del p_saved
        finally:
            orig_doc.close()
            saved_doc.close()

    @staticmethod
    def apply_signature_or_stamp(
        input_file: Path,
        output_path: Path,
        overlay: SignatureOverlay | list[SignatureOverlay],
        password: str | None = None,
        on_progress: ProgressCallback | None = None,
        is_cancelled: CancelCheckCallback | None = None,
    ) -> OperationResult:
        """Estampa trazos libres vectoriales (#000000), firma PNG con transparencia y/o sello en una o varias páginas."""
        path = Path(input_file)
        info = inspect_pdf_file(path, password=password)
        if info.is_encrypted and not password:
            raise PDFEncryptedError(
                f"El archivo '{path.name}' está protegido con contraseña."
            )

        overlays: list[SignatureOverlay] = (
            list(overlay) if isinstance(overlay, list) else [overlay]
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

            for ov in overlays:
                if ov.page_index < 0 or ov.page_index >= doc.page_count:
                    raise PDFStudioError(
                        f"Índice de página inválido para firma: {ov.page_index}"
                    )

            _check_cancel(is_cancelled)
            _emit_progress(
                on_progress, 45, "Superponiendo firma vectorial y elementos en página..."
            )

            for ov in overlays:
                _check_cancel(is_cancelled)
                page = doc.load_page(ov.page_index)
                # Aislar el estado gráfico CTM existente (evita inversión vertical de streams no envueltos)
                page.wrap_contents()
                visual_rect = page.rect

                has_strokes = any(len(s) >= 2 for s in ov.freehand_strokes)
                has_stamp = bool(ov.stamp_label and ov.stamp_label.strip())
                has_image = bool(
                    ov.image_path is not None and Path(ov.image_path).exists()
                )

                # 1. Sello predefinido opcional (transparente a alta resolución >= 216 DPI)
                if has_stamp:
                    stamp_only = SignatureOverlay(
                        page_index=ov.page_index,
                        stamp_label=ov.stamp_label,
                        image_path=None,
                        freehand_strokes=[],
                        normalized_rect=ov.normalized_rect,
                    )
                    stamp_png = PDFEngine.render_signature_overlay_png(
                        overlay=stamp_only,
                        page_width_pt=visual_rect.width,
                        page_height_pt=visual_rect.height,
                        scale=3.0,
                    )
                    unrot_full = PDFEngine._visual_rect_to_unrotated(
                        page, (0.0, 0.0, 1.0, 1.0)
                    )
                    page.insert_image(
                        unrot_full,
                        stream=stamp_png,
                        rotate=page.rotation,
                        keep_proportion=False,
                        overlay=True,
                    )

                # 2. Imagen PNG de firma en su posición y proporción elegidas
                if has_image:
                    PDFEngine._insert_signature_png_on_page(page, ov)

                # 3. Trazos libres escritos como vectores reales en el PDF
                if has_strokes:
                    PDFEngine._draw_vector_strokes_on_page(page, ov)

            doc.save(str(tmp_path), deflate=True)
            doc.close()
            _check_cancel(is_cancelled)
            shutil.move(str(tmp_path), str(safe_dest))
            PDFEngine._verify_saved_signatures_in_pdf(
                path, safe_dest, overlays, password=password
            )
        except Exception:
            if not doc.is_closed:
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
