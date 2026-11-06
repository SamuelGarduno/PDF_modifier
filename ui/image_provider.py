"""Proveedor de imágenes QtQuick (QQuickImageProvider) para miniaturas PDF y páginas del visor."""

from __future__ import annotations

from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QColor, QImage, QPainter, QPen
from PySide6.QtQuick import QQuickImageProvider

from core.exceptions import PDFCorruptedError, PDFEncryptedError
from core.pdf_engine import DEFAULT_THUMBNAIL_DPI, PDFEngine
from core.workers import ThumbnailLRUCache
from ui.theme import ACCENT, SECONDARY, SURFACE_LIGHT


class PDFPageImageProvider(QQuickImageProvider):
    """Sirve páginas PDF renderizadas a QML mediante URLs image://pdfpage/<page_idx>?path=...&dpi=..."""

    def __init__(
        self,
        cache: ThumbnailLRUCache | None = None,
        password_resolver: object | None = None,
    ) -> None:
        super().__init__(QQuickImageProvider.ImageType.Image)
        self.cache = cache if cache is not None else ThumbnailLRUCache()
        self._passwords: dict[str, str] = {}

    def register_password(self, file_path: Path, password: str) -> None:
        """Asocia la contraseña desbloqueada de un PDF para permitir su renderizado."""
        self._passwords[str(Path(file_path).resolve())] = password

    def invalidate_file(self, file_path: Path) -> None:
        """Limpia entradas de caché asociadas a un archivo eliminado o actualizado."""
        self.cache.remove_for_file(str(Path(file_path).resolve()))

    def requestImage(
        self, id_str: str, size: QSize, requestedSize: QSize
    ) -> QImage:
        """Renderiza o recupera de la caché LRU la página solicitada por QtQuick."""
        try:
            parsed = urlparse(f"scheme://{id_str}")
            page_part = parsed.netloc or parsed.path.lstrip("/")
            if "/" in page_part:
                page_part = page_part.split("/")[0]
            page_index = max(0, int(page_part)) if page_part.isdigit() else 0

            params = parse_qs(parsed.query)
            raw_path = unquote(params.get("path", [""])[0])
            dpi = int(params.get("dpi", [str(DEFAULT_THUMBNAIL_DPI)])[0])
            dpi = max(48, min(220, dpi))

            if not raw_path:
                return self._create_placeholder_image("Sin documento")

            file_path = Path(raw_path)
            if not file_path.exists():
                return self._create_placeholder_image("No encontrado", is_error=True)

            resolved_str = str(file_path.resolve())
            cache_key = (resolved_str, page_index, dpi)
            png_bytes = self.cache.get(cache_key)

            if png_bytes is None:
                pwd = self._passwords.get(resolved_str)
                try:
                    png_bytes = PDFEngine.render_page_png_bytes(
                        file_path=file_path,
                        page_index=page_index,
                        dpi=dpi,
                        password=pwd,
                    )
                    self.cache.put(cache_key, png_bytes)
                except PDFEncryptedError:
                    return self._create_locked_image()
                except PDFCorruptedError:
                    return self._create_placeholder_image("Ilegible", is_error=True)

            image = QImage.fromData(png_bytes, "PNG")
            if image.isNull():
                return self._create_placeholder_image("Error", is_error=True)

            if requestedSize.isValid() and requestedSize.width() > 0 and requestedSize.height() > 0:
                image = image.scaled(
                    requestedSize,
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )
            return image
        except Exception:
            return self._create_placeholder_image("Error", is_error=True)

    @staticmethod
    def _create_locked_image() -> QImage:
        """Genera una miniatura elegante con candado y sello para PDFs protegidos con clave."""
        img = QImage(168, 216, QImage.Format.Format_ARGB32)
        img.fill(QColor("#F7EEF8"))
        painter = QPainter(img)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        pen = QPen(QColor("#681D3A"))
        pen.setWidth(2)
        painter.setPen(pen)
        painter.drawRoundedRect(6, 6, 156, 204, 8, 8)

        # Círculo de lacre central
        painter.setBrush(QColor("#A99BC4"))
        painter.drawEllipse(48, 56, 72, 72)

        # Candado dibujado dentro del sello
        lock_pen = QPen(QColor("#31234A"))
        lock_pen.setWidth(3)
        painter.setPen(lock_pen)
        painter.setBrush(QColor("#FFFDFB"))
        painter.drawRoundedRect(68, 88, 32, 24, 4, 4)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawArc(73, 72, 22, 26, 0, 180 * 16)

        painter.setPen(QColor("#521928"))
        painter.drawText(
            img.rect().adjusted(8, 136, -8, -12),
            Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop,
            "Protegido",
        )
        painter.end()
        return img

    @staticmethod
    def _create_placeholder_image(label: str, is_error: bool = False) -> QImage:
        """Genera una hoja estilo papelería cuando el PDF aún no está disponible o está dañado."""
        img = QImage(220, 300, QImage.Format.Format_ARGB32)
        bg = "#FDF0F2" if is_error else SURFACE_LIGHT
        border = "#9E1B32" if is_error else SECONDARY
        img.fill(QColor(bg))
        painter = QPainter(img)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        pen = QPen(QColor(border))
        pen.setWidth(2)
        painter.setPen(pen)
        painter.drawRect(8, 8, 204, 284)
        painter.setPen(QColor(ACCENT))
        painter.drawRect(14, 14, 192, 272)
        painter.setPen(QColor(border))
        painter.drawText(img.rect(), Qt.AlignmentFlag.AlignCenter, label)
        painter.end()
        return img

