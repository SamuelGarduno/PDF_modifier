"""Punto de entrada principal de Coquette PDF Studio (Python 3.14 + PySide6 QtQuick)."""

from __future__ import annotations

import os
import sys

from PySide6.QtCore import QTimer
from PySide6.QtGui import QGuiApplication
from PySide6.QtQuickControls2 import QQuickStyle

from ui.main_window import CoquetteQuickApp


def main(argv: list[str] | None = None) -> int:
    """Inicia la aplicación de escritorio QtQuick."""
    args = argv if argv is not None else sys.argv
    QQuickStyle.setStyle("Basic")

    app = QGuiApplication.instance() or QGuiApplication(args)
    app.setApplicationName("Coquette PDF Studio")
    app.setOrganizationName("AtelierCoquette")

    quick_app = CoquetteQuickApp()
    window = quick_app.load_main_qml()

    # Modo de verificación rápida sin bloqueo (--smoke-test)
    if "--smoke-test" in args or os.environ.get("COQUETTE_SMOKE_TEST") == "1":
        QTimer.singleShot(150, window.close)

    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
