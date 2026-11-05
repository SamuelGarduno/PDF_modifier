"""Inicializador de la aplicación QtQuick (QQmlApplicationEngine) y ventana principal."""

from __future__ import annotations

from pathlib import Path
from PySide6.QtCore import QUrl
from PySide6.QtQml import QQmlApplicationEngine

from core.history import OperationHistoryStore
from ui.bridge import StudioBridge
from ui.image_provider import PDFPageImageProvider
from ui.theme import ThemePalette, load_custom_fonts


class CoquetteQuickApp:
    """Encapsula el QQmlApplicationEngine, el proveedor de miniaturas y los puentes de datos."""

    def __init__(self, history_store: OperationHistoryStore | None = None) -> None:
        load_custom_fonts()
        self.engine = QQmlApplicationEngine()
        self.theme_palette = ThemePalette()
        self.image_provider = PDFPageImageProvider()
        self.studio_bridge = StudioBridge(
            image_provider=self.image_provider,
            history_store=history_store,
        )

        # Registrar image provider para URLs image://pdfpage/...
        self.engine.addImageProvider("pdfpage", self.image_provider)

        # Exponer objetos globales al contexto QML
        root_ctx = self.engine.rootContext()
        root_ctx.setContextProperty("themePalette", self.theme_palette)
        root_ctx.setContextProperty("studioBridge", self.studio_bridge)

    def load_main_qml(self) -> object:
        """Carga el archivo QML principal y devuelve la QQuickWindow raíz."""
        qml_path = Path(__file__).resolve().parent / "qml" / "Main.qml"
        self.engine.load(QUrl.fromLocalFile(str(qml_path)))
        roots = self.engine.rootObjects()
        if not roots:
            raise RuntimeError("No se pudo cargar ui/qml/Main.qml en QQmlApplicationEngine.")
        return roots[0]

