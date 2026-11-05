"""Pruebas automatizadas de la interfaz QtQuick (QML) y del puente reactivo StudioBridge con pytest-qt."""

from __future__ import annotations

from pathlib import Path
from PySide6.QtCore import QSize, Qt
from PySide6.QtQuick import QQuickItem, QQuickWindow

from core.history import OperationHistoryStore
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
    generate_stationery_qss,
)


def test_design_tokens_and_qss_constants() -> None:
    """Verifica que los 5 tokens de color exactos y las constantes arquitectónicas estén presentes."""
    assert SURFACE_LIGHT == "#FBF0F0"
    assert BACKGROUND_DARK == "#1E0F16"
    assert PRIMARY == "#DF8293"
    assert SECONDARY == "#681D3A"
    assert ACCENT == "#F8B8B0"
    assert INITIAL_WINDOW_WIDTH == 1280
    assert INITIAL_WINDOW_HEIGHT == 720
    assert SIDEBAR_FIXED_WIDTH == 260

    qss = generate_stationery_qss()
    for token in (SURFACE_LIGHT, BACKGROUND_DARK, PRIMARY, SECONDARY, ACCENT):
        assert token in qss


def test_qtquick_window_frameless_aspect_ratio_and_sidebar(
    tmp_path: Path, qtbot
) -> None:
    """Verifica que la ventana QtQuick sea sin bordes (FramelessWindowHint), 16:9 (1280x720) y con sidebar fijo de 260px."""
    store = OperationHistoryStore(storage_path=tmp_path / "ui_hist.json")
    app_wrapper = CoquetteQuickApp(history_store=store)
    window = app_wrapper.load_main_qml()
    assert isinstance(window, QQuickWindow)

    # Verificar FramelessWindowHint y proporción 16:9 (1280x720)
    flags = window.flags()
    assert bool(flags & Qt.WindowType.FramelessWindowHint)
    assert window.width() == 1280
    assert window.height() == 720
    assert round(window.width() / window.height(), 2) == round(16 / 9, 2)

    # Verificar el Sidebar fijo de 260px con color #1E0F16
    sidebar = window.findChild(QQuickItem, "leftSidebar")
    assert sidebar is not None
    assert int(sidebar.width()) == 260
    assert sidebar.property("color").name().upper() == BACKGROUND_DARK

    # Verificar el Lienzo Central en #FBF0F0
    workspace = window.findChild(QQuickItem, "mainWorkspace")
    assert workspace is not None
    assert workspace.property("color").name().upper() == SURFACE_LIGHT

    window.close()


def test_bridge_file_ingestion_organizer_and_search(
    sample_pdf_5p: Path, encrypted_pdf: tuple[Path, str], tmp_path: Path, qtbot
) -> None:
    """Verifica ingesta, buscador Ctrl+K, Page Organizer (rotar, duplicar, eliminar, reordenar) y PDF cifrado."""
    store = OperationHistoryStore(storage_path=tmp_path / "bridge_hist.json")
    app_wrapper = CoquetteQuickApp(history_store=store)
    bridge = app_wrapper.studio_bridge

    # 1. Filtrado rápido de herramientas
    assert len(bridge.filteredTools) == 10
    bridge.setSearchQuery("marca")
    assert len(bridge.filteredTools) == 1
    assert bridge.filteredTools[0]["id"] == "watermark"
    bridge.setSearchQuery("")
    assert len(bridge.filteredTools) == 10

    # 2. Ingesta de PDF de 5 páginas y poblamiento del Page Organizer
    bridge.addSingleFilePath(str(sample_pdf_5p))
    assert bridge.fileCount == 1
    assert bridge.organizerPageCount == 5

    # Rotar primera página 90 grados
    bridge.rotatePageAt(0)
    assert bridge.organizerPages[0]["rotation"] == 90

    # Duplicar primera página -> ahora son 6 páginas
    bridge.duplicatePageAt(0)
    assert bridge.organizerPageCount == 6

    # Eliminar segunda página -> vuelve a 5 páginas
    bridge.deletePageAt(1)
    assert bridge.organizerPageCount == 5

    # Reordenar mediante Drag & Drop (mover índice 0 al índice 3)
    first_source = bridge.organizerPages[0]["sourcePageIndex"]
    bridge.moveOrganizerPage(0, 3)
    assert bridge.organizerPages[3]["sourcePageIndex"] == first_source

    # Selección múltiple (Shift + clic) y rotación en lote
    bridge.selectOrganizerPage(0, False, False)
    bridge.selectOrganizerPage(2, False, True)
    assert bridge.organizerPages[0]["selected"] is True
    assert bridge.organizerPages[1]["selected"] is True
    assert bridge.organizerPages[2]["selected"] is True

    # 3. Ingesta de PDF cifrado emite señal passwordRequired y luego se desbloquea
    locked_path, pwd = encrypted_pdf
    bridge.setActiveTool("split")
    with qtbot.waitSignal(bridge.passwordRequired, timeout=3000) as sig_blocker:
        bridge.addSingleFilePath(str(locked_path))
    assert Path(sig_blocker.args[0]) == locked_path

    unlocked_ok = bridge.supplyFilePassword(str(locked_path), pwd)
    assert unlocked_ok is True


def test_image_provider_and_end_to_end_async_execution(
    sample_pdf_5p: Path, tmp_path: Path, qtbot
) -> None:
    """Verifica el QQuickImageProvider y la ejecución asíncrona de extremo a extremo desde StudioBridge."""
    store = OperationHistoryStore(storage_path=tmp_path / "e2e_hist.json")
    app_wrapper = CoquetteQuickApp(history_store=store)
    bridge = app_wrapper.studio_bridge

    bridge.addSingleFilePath(str(sample_pdf_5p))
    bridge.setOutputDirectory(str(tmp_path))

    # Solicitar imagen al QQuickImageProvider como lo hace QML
    img = app_wrapper.image_provider.requestImage(
        f"0?path={sample_pdf_5p}&dpi=72", QSize(), QSize(120, 160)
    )
    assert not img.isNull()
    assert img.width() <= 120

    # Ejecutar extracción de páginas de forma asíncrona desde la interfaz
    bridge.setActiveTool("split")
    bridge.setRangeExpr("1-3")
    assert bridge.isRangeValid is True

    with qtbot.waitSignal(bridge.operationCompleted, timeout=10000) as blocker:
        bridge.executeActiveOperation()

    out_file_path = Path(blocker.args[1])
    assert out_file_path.exists()
    assert len(bridge.recentHistory) == 1
    assert bridge.progressPercent == 100
    assert bridge.lastOutputFile != ""

    # Al cambiar de herramienta en el Sidebar, el Footer debe reiniciar su progreso y mensaje
    bridge.setActiveTool("organize")
    assert bridge.progressPercent == 0
    assert bridge.lastOutputFile == ""
    assert "Listo" in bridge.statusMessage


def test_qml_layout_sidebar_footer_cta_organizer_reindexing_and_viewer_modes(
    sample_pdf_5p: Path, tmp_path: Path, qtbot
) -> None:
    """Verifica ausencia de recortes en Sidebar/Footer, reindexación en Organizador y modos/sello en Visor."""
    import pymupdf as fitz

    store = OperationHistoryStore(storage_path=tmp_path / "layout_hist.json")
    app_wrapper = CoquetteQuickApp(history_store=store)
    window = app_wrapper.load_main_qml()
    bridge = app_wrapper.studio_bridge
    qtbot.waitExposed(window)

    # 1. Sidebar con clip: true y última tarjeta ("Visor y Firma") dentro del área visible sin recortes
    sidebar_list = window.findChild(QQuickItem, "sidebarToolsList")
    cards_column = window.findChild(QQuickItem, "sidebarCardsColumn")
    assert sidebar_list is not None and cards_column is not None
    assert sidebar_list.clip() is True
    card_items = [
        item
        for item in cards_column.childItems()
        if item.objectName().startswith("sidebarCard_")
    ]
    assert len(card_items) == 10
    sign_cards = [c for c in card_items if c.objectName() == "sidebarCard_sign"]
    assert len(sign_cards) == 1
    last_card = sign_cards[0]
    assert last_card.y() + last_card.height() <= sidebar_list.height()

    # 2. Botón CTA con texto largo ("Procesar Organizar Páginas") completo y dentro del Footer
    bridge.setActiveTool("organize")
    footer_bar = window.findChild(QQuickItem, "footerBar")
    cta_btn = window.findChild(QQuickItem, "mainCtaButton")
    assert footer_bar is not None and cta_btn is not None
    assert cta_btn.property("text") == "Procesar Organizar Páginas"
    assert cta_btn.width() >= cta_btn.implicitWidth()
    assert cta_btn.x() + cta_btn.width() <= footer_bar.width()

    # 3. En "Organizar Páginas": mover última página al inicio, duplicar y verificar etiquetas correlativas 1..N
    bridge.addSingleFilePath(str(sample_pdf_5p))
    bridge.setOutputDirectory(str(tmp_path))
    assert bridge.organizerPageCount == 5

    # Mover la última página (índice 4, sourcePageIndex=4) a la primera posición (índice 0)
    bridge.move_page(4, 0)
    assert [p["sourcePageIndex"] for p in bridge.organizerPages] == [4, 0, 1, 2, 3]
    assert [p["displayPageNumber"] for p in bridge.organizerPages] == [1, 2, 3, 4, 5]

    # Duplicar la página en índice 3 -> no debe haber números repetidos en displayPageNumber
    bridge.duplicatePageAt(3)
    assert bridge.organizerPageCount == 6
    assert [p["displayPageNumber"] for p in bridge.organizerPages] == [1, 2, 3, 4, 5, 6]

    # Exportar el PDF organizado y comprobar que la primera página corresponde a la página 5 original
    with qtbot.waitSignal(bridge.operationCompleted, timeout=10000) as org_blocker:
        bridge.executeActiveOperation()
    organized_out = Path(org_blocker.args[1])
    assert organized_out.exists()
    with fitz.open(organized_out) as doc:
        assert doc.page_count == 6
        assert "Page 5 of 5" in doc[0].get_text()

    # 4. En "Visor y Firma": bloqueo de Flickable al dibujar, trazo negro (#000000) y opción "Sin Sello"
    bridge.setActiveTool("sign")
    viewer_view = window.findChild(QQuickItem, "pdfViewerSignView")
    viewer_flickable = window.findChild(QQuickItem, "viewerFlickable")
    stamp_preview = window.findChild(QQuickItem, "stampPreviewBox")
    assert viewer_view is not None and viewer_flickable is not None and stamp_preview is not None

    # Color de firma negro puro (#000000)
    assert viewer_view.property("strokeHexColor") == "#000000"

    # En modo dibujo (viewerDrawMode == True), el Flickable está bloqueado (interactive == False)
    assert bridge.viewerDrawMode is True
    assert viewer_flickable.property("interactive") is False

    # Cambiar a "Modo Mover Hoja" habilita el desplazamiento del Flickable
    bridge.setViewerDrawMode(False)
    assert viewer_flickable.property("interactive") is True
    bridge.setViewerDrawMode(True)

    # Opción para quitar/ocultar el sello ("Sin Sello")
    assert bridge.signatureStamp == "APROBADO"
    assert stamp_preview.isVisible() is True
    bridge.clearSignatureStamp()
    assert bridge.signatureStamp == ""
    assert stamp_preview.isVisible() is False

    window.close()


def test_merge_pdf_empty_and_queued_states_atelier_coquette(
    sample_pdf_5p: Path, sample_pdf_3p: Path, tmp_path: Path, qtbot
) -> None:
    """Verifica el refinamiento visual de 'Unir PDF' en estado vacío y con 3 archivos en cola."""
    import pymupdf as fitz

    # Crear un tercer PDF de 1 página con un nombre de archivo muy largo para probar elipsis y conteo
    long_name_pdf = (
        tmp_path
        / "Contrato_marco_corporativo_extraordinariamente_largo_anexo_tecnico_2026_final_v3.pdf"
    )
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)
    page.insert_text((72, 100), "Anexo de 1 página")
    doc.save(long_name_pdf)
    doc.close()

    store = OperationHistoryStore(storage_path=tmp_path / "coquette_merge_hist.json")
    app_wrapper = CoquetteQuickApp(history_store=store)
    window = app_wrapper.load_main_qml()
    bridge = app_wrapper.studio_bridge
    qtbot.waitExposed(window)

    # 1. Verificar Estado 1 (Vacío) en "Unir PDF"
    assert bridge.activeTool == "merge"
    assert bridge.fileCount == 0
    assert bridge.totalQueuedPages == 0
    assert bridge.statusMessage == "Listo para trabajar en tu escritorio de papelería."

    empty_container = window.findChild(QQuickItem, "emptyStateContainer")
    queued_container = window.findChild(QQuickItem, "queuedStateContainer")
    cta_btn = window.findChild(QQuickItem, "mainCtaButton")
    left_washi = (_collect_items_by_prefix(window.contentItem(), "leftWashiTape") or [None])[0]
    right_washi = (_collect_items_by_prefix(window.contentItem(), "rightWashiTape") or [None])[0]
    mode_header = window.findChild(QQuickItem, "activeModeHeaderLabel")
    mode_title = window.findChild(QQuickItem, "activeModeToolTitle")

    assert empty_container is not None and queued_container is not None
    assert empty_container.isVisible() is True
    assert queued_container.isVisible() is False
    assert cta_btn is not None and cta_btn.property("enabledButton") is False
    assert left_washi is not None and right_washi is not None
    assert mode_header is not None and mode_header.property("text") == "MODO ACTIVO"
    assert mode_title is not None and mode_title.property("text") == "Unir PDF"

    # 2. Cargar 3 archivos PDF en la cola y verificar transición al Estado 2 (Con cola)
    bridge.addFileUrls([str(sample_pdf_5p), str(sample_pdf_3p), str(long_name_pdf)])
    qtbot.wait(50)

    assert bridge.fileCount == 3
    assert bridge.totalQueuedPages == 9
    assert bridge.statusMessage == "Listo para encuadernar 3 pliegos (9 páginas)."
    assert empty_container.isVisible() is False
    assert queued_container.isVisible() is True
    assert cta_btn.property("enabledButton") is True

    queue_header_count = window.findChild(QQuickItem, "queueHeaderCountText")
    assert queue_header_count is not None
    assert queue_header_count.property("text") == "· 3 documentos"

    # Verificar estados habilitado/deshabilitado de botones subir (^) y bajar (v) en bordes
    def _find_visual_item(item: QQuickItem, target_name: str) -> QQuickItem | None:
        if item.objectName() == target_name:
            return item
        for child in item.childItems():
            found = _find_visual_item(child, target_name)
            if found is not None:
                return found
        return None

    queue_list = window.findChild(QQuickItem, "queueListView")
    assert queue_list is not None
    up_0 = _find_visual_item(queue_list, "moveUpBtn_0")
    down_0 = _find_visual_item(queue_list, "moveDownBtn_0")
    up_2 = _find_visual_item(queue_list, "moveUpBtn_2")
    down_2 = _find_visual_item(queue_list, "moveDownBtn_2")
    assert up_0 is not None and up_0.property("canMoveUp") is False
    assert down_0 is not None and down_0.property("canMoveDown") is True
    assert up_2 is not None and up_2.property("canMoveUp") is True
    assert down_2 is not None and down_2.property("canMoveDown") is False

    # 3. Probar reordenamiento arriba/abajo y eliminación individual
    first_name = bridge.queuedFiles[0]["name"]
    second_name = bridge.queuedFiles[1]["name"]
    bridge.moveFileDown(0)
    assert bridge.queuedFiles[0]["name"] == second_name
    assert bridge.queuedFiles[1]["name"] == first_name

    bridge.moveFileUp(1)
    assert bridge.queuedFiles[0]["name"] == first_name

    bridge.removeFileAt(2)
    assert bridge.fileCount == 2
    assert bridge.totalQueuedPages == 8
    assert bridge.statusMessage == "Listo para encuadernar 2 pliegos (8 páginas)."

    # 4. Probar "Vaciar cola" y retorno limpio al Estado 1 (Vacío)
    bridge.clearFiles()
    qtbot.wait(50)
    assert bridge.fileCount == 0
    assert bridge.totalQueuedPages == 0
    assert bridge.statusMessage == "Listo para trabajar en tu escritorio de papelería."
    assert empty_container.isVisible() is True
    assert queued_container.isVisible() is False
    assert cta_btn.property("enabledButton") is False

    window.close()




ICONS_DIR = Path(__file__).resolve().parent.parent / "assets" / "icons"
MIN_HEADER_TOP_MARGIN_PX = 18
CORNER_OPACITY_RANGE = (0.20, 0.25)


def _collect_items_by_prefix(root: QQuickItem, prefix: str) -> list[QQuickItem]:
    """Recorre el árbol visual (incluye delegados de Repeater, que findChild no encuentra)."""
    found: list[QQuickItem] = []
    if root.objectName().startswith(prefix):
        found.append(root)
    for child in root.childItems():
        found.extend(_collect_items_by_prefix(child, prefix))
    return found


def test_svg_assets_are_svg_tiny_compatible() -> None:
    """Los SVG decorativos deben renderizar en QSvgRenderer y no usar CSS ni clases."""
    from PySide6.QtSvg import QSvgRenderer

    for name in ("botanical_corner.svg", "washi_tape.svg"):
        text = (ICONS_DIR / name).read_text(encoding="utf-8")
        assert "<style" not in text and "class=" not in text, name
        assert 'baseProfile="tiny"' in text, name
        assert QSvgRenderer(text.encode("utf-8")).isValid(), name


def test_sidebar_title_header_botanical_corners_washi_and_cta_hint(
    tmp_path: Path, qtbot
) -> None:
    """Título sin truncar, 4 esquinas botánicas íntegras, washi SVG, margen de cabecera y tooltip del CTA."""
    store = OperationHistoryStore(storage_path=tmp_path / "visual_hist.json")
    app_wrapper = CoquetteQuickApp(history_store=store)
    window = app_wrapper.load_main_qml()
    qtbot.waitExposed(window)
    root = window.contentItem()

    # 1. Título del sidebar: ≤ 2 líneas, sin elisión y dentro de los 260 px del panel
    title = window.findChild(QQuickItem, "sidebarTitleText")
    assert title is not None
    assert title.property("truncated") is False
    assert title.property("lineCount") <= 2
    assert title.width() <= 260

    # 2. Cuatro esquinas botánicas completas, tenues y dentro de su contenedor
    corners = _collect_items_by_prefix(root, "botanicalCorner")
    assert len(corners) == 4
    for corner in corners:
        assert corner.property("paintedWidth") > 0  # imagen SVG cargada y dibujada
        assert CORNER_OPACITY_RANGE[0] <= corner.opacity() <= CORNER_OPACITY_RANGE[1]
        parent = corner.parentItem()
        assert corner.x() >= 12 and corner.y() >= 12
        assert corner.x() + corner.width() <= parent.width() - 12
        assert corner.y() + corner.height() <= parent.height() - 12

    # 3. Washi tape: dos cintas con imagen SVG cargada
    for name in ("leftWashiTape", "rightWashiTape"):
        tapes = _collect_items_by_prefix(root, name)
        assert len(tapes) == 1
        images = [c for c in tapes[0].childItems() if c.property("source") is not None]
        assert images and images[0].property("paintedWidth") > 0

    # 4. Cabecera con margen superior ≥ 18 px
    header_row = window.findChild(QQuickItem, "headerTitleRow")
    assert header_row is not None
    assert header_row.y() >= MIN_HEADER_TOP_MARGIN_PX

    # 5. CTA inactivo (cola vacía) con pista informativa
    cta = window.findChild(QQuickItem, "mainCtaButton")
    assert cta is not None
    assert cta.property("enabledButton") is False
    assert "Agrega archivos" in cta.property("disabledHint")

    window.close()

