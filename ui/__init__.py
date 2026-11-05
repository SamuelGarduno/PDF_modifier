"""Paquete de interfaz de usuario QtQuick (QML) con diseño Floral Stationery & Coquette."""

from ui.bridge import StudioBridge, TOOLS_CATALOG
from ui.image_provider import PDFPageImageProvider
from ui.main_window import CoquetteQuickApp
from ui.theme import (
    ACCENT,
    BACKGROUND_DARK,
    INITIAL_WINDOW_HEIGHT,
    INITIAL_WINDOW_WIDTH,
    PRIMARY,
    SECONDARY,
    SIDEBAR_FIXED_WIDTH,
    SURFACE_LIGHT,
    ThemePalette,
    generate_stationery_qss,
    load_custom_fonts,
)

__all__ = [
    "ACCENT",
    "BACKGROUND_DARK",
    "CoquetteQuickApp",
    "INITIAL_WINDOW_HEIGHT",
    "INITIAL_WINDOW_WIDTH",
    "PDFPageImageProvider",
    "PRIMARY",
    "SECONDARY",
    "SIDEBAR_FIXED_WIDTH",
    "SURFACE_LIGHT",
    "StudioBridge",
    "TOOLS_CATALOG",
    "ThemePalette",
    "generate_stationery_qss",
    "load_custom_fonts",
]

