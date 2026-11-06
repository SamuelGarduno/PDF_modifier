"""Sistema de Diseño 'Floral Stationery & Coquette': Tokens de color, tipografía y carga de fuentes."""

from __future__ import annotations

from pathlib import Path
from PySide6.QtCore import Property, QObject, Signal
from PySide6.QtGui import QFontDatabase

# Tokens de color obligatorios de la paleta "Floral Stationery & Coquette"
SURFACE_LIGHT = "#FBF0F0"     # Rosa blush ultra pálido
BACKGROUND_DARK = "#1E0F16"   # Café ciruela casi negro
PRIMARY = "#DF8293"           # Rosa cálido empolvado
SECONDARY = "#681D3A"         # Burdeos profundo / Vino
ACCENT = "#F8B8B0"            # Durazno suave / Coral pastel

# Tokens específicos de refinamiento "Atelier Coquette"
SEARCH_BG_DARK = "#3A1822"
SEARCH_BORDER_DARK = "#6E3B49"
SEARCH_BADGE_SALMON = "#F5B8A8"
SIDEBAR_CARD_INACTIVE_BG = "#2D121A"
SIDEBAR_CARD_INACTIVE_BORDER = "#5A2D3A"
SIDEBAR_CARD_ACTIVE_BG = "#F6BCA8"
WINE_DEEP = "#521928"
STATIONERY_FRAME_BG = "#FBF4F0"
WASHI_LEFT_ROSE = "#D98A94"
WASHI_RIGHT_PEACH = "#F2B6A6"
BUTTON_PRIMARY_ROSE = "#DA7B88"
QUEUE_CARD_BG = "#FFFDFB"

# Dimensiones arquitectónicas obligatorias
INITIAL_WINDOW_WIDTH = 1280
INITIAL_WINDOW_HEIGHT = 720
SIDEBAR_FIXED_WIDTH = 260

# Familias tipográficas con fallbacks seguros
SERIF_FAMILIES = ["Playfair Display", "Cormorant Garamond", "Lora", "Georgia"]
SCRIPT_FAMILIES = ["Cormorant Garamond", "Playfair Display", "Georgia"]
SANS_FAMILIES = ["Quicksand", "Nunito", "Inter", "Segoe UI"]


def load_custom_fonts(fonts_dir: Path | None = None) -> list[str]:
    """Carga automáticamente archivos .ttf y .otf desde assets/fonts/ mediante QFontDatabase."""
    if fonts_dir is None:
        fonts_dir = Path(__file__).resolve().parent.parent / "assets" / "fonts"
    loaded_families: list[str] = []
    if not fonts_dir.exists():
        return loaded_families

    for font_path in sorted(fonts_dir.glob("*")):
        if font_path.suffix.lower() in {".ttf", ".otf"}:
            font_id = QFontDatabase.addApplicationFont(str(font_path))
            if font_id != -1:
                families = QFontDatabase.applicationFontFamilies(font_id)
                loaded_families.extend(families)
    return loaded_families


def resolve_available_font(candidates: list[str], default: str) -> str:
    """Devuelve la primera fuente disponible en el sistema o el fallback indicado."""
    available = set(QFontDatabase.families())
    for family in candidates:
        if family in available:
            return family
    return default


class ThemePalette(QObject):
    """Objeto QObject expuesto a QtQuick/QML con los tokens y tipografías del sistema de diseño."""

    paletteChanged = Signal()

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._serif_font = resolve_available_font(SERIF_FAMILIES, "Georgia")
        self._script_font = resolve_available_font(SCRIPT_FAMILIES, "Georgia")
        self._sans_font = resolve_available_font(SANS_FAMILIES, "Segoe UI")

    @Property(str, notify=paletteChanged)
    def surfaceLight(self) -> str:
        return SURFACE_LIGHT

    @Property(str, notify=paletteChanged)
    def backgroundDark(self) -> str:
        return BACKGROUND_DARK

    @Property(str, notify=paletteChanged)
    def primary(self) -> str:
        return PRIMARY

    @Property(str, notify=paletteChanged)
    def secondary(self) -> str:
        return SECONDARY

    @Property(str, notify=paletteChanged)
    def accent(self) -> str:
        return ACCENT

    @Property(str, notify=paletteChanged)
    def searchBgDark(self) -> str:
        return SEARCH_BG_DARK

    @Property(str, notify=paletteChanged)
    def searchBorderDark(self) -> str:
        return SEARCH_BORDER_DARK

    @Property(str, notify=paletteChanged)
    def searchBadgeSalmon(self) -> str:
        return SEARCH_BADGE_SALMON

    @Property(str, notify=paletteChanged)
    def sidebarCardInactiveBg(self) -> str:
        return SIDEBAR_CARD_INACTIVE_BG

    @Property(str, notify=paletteChanged)
    def sidebarCardInactiveBorder(self) -> str:
        return SIDEBAR_CARD_INACTIVE_BORDER

    @Property(str, notify=paletteChanged)
    def sidebarCardActiveBg(self) -> str:
        return SIDEBAR_CARD_ACTIVE_BG

    @Property(str, notify=paletteChanged)
    def wineDeep(self) -> str:
        return WINE_DEEP

    @Property(str, notify=paletteChanged)
    def stationeryFrameBg(self) -> str:
        return STATIONERY_FRAME_BG

    @Property(str, notify=paletteChanged)
    def washiLeftRose(self) -> str:
        return WASHI_LEFT_ROSE

    @Property(str, notify=paletteChanged)
    def washiRightPeach(self) -> str:
        return WASHI_RIGHT_PEACH

    @Property(str, notify=paletteChanged)
    def buttonPrimaryRose(self) -> str:
        return BUTTON_PRIMARY_ROSE

    @Property(str, notify=paletteChanged)
    def queueCardBg(self) -> str:
        return QUEUE_CARD_BG

    @Property(int, notify=paletteChanged)
    def initialWidth(self) -> int:
        return INITIAL_WINDOW_WIDTH

    @Property(int, notify=paletteChanged)
    def initialHeight(self) -> int:
        return INITIAL_WINDOW_HEIGHT

    @Property(int, notify=paletteChanged)
    def sidebarWidth(self) -> int:
        return SIDEBAR_FIXED_WIDTH

    @Property(str, notify=paletteChanged)
    def serifFont(self) -> str:
        return self._serif_font

    @Property(str, notify=paletteChanged)
    def scriptFont(self) -> str:
        return self._script_font

    @Property(str, notify=paletteChanged)
    def sansFont(self) -> str:
        return self._sans_font


def generate_stationery_qss() -> str:
    """Genera una hoja de estilos QSS complementaria con los 5 tokens oficiales."""
    return f"""
    QWidget {{
        background-color: {SURFACE_LIGHT};
        color: {BACKGROUND_DARK};
        font-family: "Quicksand", "Nunito", "Segoe UI";
    }}
    QPushButton {{
        background-color: {PRIMARY};
        color: {BACKGROUND_DARK};
        border: 1px solid {SECONDARY};
        border-radius: 20px;
        padding: 8px 18px;
    }}
    QPushButton:hover {{
        background-color: {SECONDARY};
        color: {SURFACE_LIGHT};
    }}
    QLineEdit {{
        background-color: {SURFACE_LIGHT};
        color: {BACKGROUND_DARK};
        border: 1px solid {SECONDARY};
        border-radius: 8px;
        padding: 6px;
        selection-background-color: {ACCENT};
    }}
    """

