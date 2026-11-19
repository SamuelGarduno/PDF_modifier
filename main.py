"""Punto de entrada principal de Coquette PDF Studio (Python 3.14 + PySide6 QtQuick)."""

from __future__ import annotations

import os
import sys

from PySide6.QtCore import QTimer
from PySide6.QtGui import QGuiApplication, QIcon
from PySide6.QtQuickControls2 import QQuickStyle

from ui.main_window import CoquetteQuickApp
from ui.theme import resolve_resource_path


def main(argv: list[str] | None = None) -> int:
    """Inicia la aplicación de escritorio QtQuick."""
    args = argv if argv is not None else sys.argv
    if sys.platform == "win32":
        try:
            import ctypes

            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(
                "AtelierCoquette.MesaDeTrabajoFloral.1"
            )
        except Exception:
            pass

    QQuickStyle.setStyle("Basic")

    app = QGuiApplication.instance() or QGuiApplication(args)
    app.setApplicationName("Coquette PDF Studio")
    app.setOrganizationName("AtelierCoquette")

    icon_path = resolve_resource_path("assets", "app_icon.ico")
    if icon_path.exists():
        app.setWindowIcon(QIcon(str(icon_path)))

    quick_app = CoquetteQuickApp()
    window = quick_app.load_main_qml()

    # Modo de verificación rápida sin bloqueo (--smoke-test)
    if "--smoke-test" in args or os.environ.get("COQUETTE_SMOKE_TEST") == "1":
        QTimer.singleShot(150, window.close)

    return app.exec()

if __name__ == "__main__":
    raise SystemExit(main())
