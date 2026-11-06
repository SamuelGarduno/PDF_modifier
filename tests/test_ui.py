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

# Margen holgado sobre las animaciones de la cola (salida 120 ms, entrada ≤ 160 ms + escalonado)
QUEUE_EXIT_SETTLE_MS = 300


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


def test_qtquick_window_frameless_full_width_without_sidebar(
    tmp_path: Path, qtbot
) -> None:
    """Verifica que la ventana QtQuick inicie sin barra lateral izquierda y que la Mesa de Trabajo ocupe todo el ancho."""
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

    # Verificar que NO exista leftSidebar ni quickSearchInput (Ctrl+K)
    sidebar = window.findChild(QQuickItem, "leftSidebar")
    assert sidebar is None
    search_input = window.findChild(QQuickItem, "quickSearchInput")
    assert search_input is None

    # Verificar que el Lienzo Central (Mesa de Trabajo) ocupe el 100% del ancho de la ventana
    workspace = window.findChild(QQuickItem, "mainWorkspace")
    assert workspace is not None
    assert int(workspace.width()) == 1280
    assert workspace.property("color").name().upper() == SURFACE_LIGHT

    # Verificar que el detalle gráfico de la espiral del cuaderno se conserve en el borde izquierdo
    spiral = window.findChild(QQuickItem, "spiralBindingCanvas")
    assert spiral is not None
    assert int(spiral.width()) == 24

    window.close()


def test_password_tools_removed_and_contextual_suggestions_all_cases(
    sample_pdf_5p: Path,
    sample_pdf_3p: Path,
    sample_images: list[Path],
    tmp_path: Path,
    qtbot,
) -> None:
    """Verifica la eliminación de Proteger/Desbloquear y el motor contextual para los 4 casos y casos borde."""
    from PIL import Image

    store = OperationHistoryStore(storage_path=tmp_path / "ctx_hist.json")
    app_wrapper = CoquetteQuickApp(history_store=store)
    bridge = app_wrapper.studio_bridge

    # 1. Las herramientas "protect" y "unlock" no existen en el catálogo ni pueden seleccionarse
    catalog_ids = {item["id"] for item in bridge.filteredTools}
    assert "protect" not in catalog_ids
    assert "unlock" not in catalog_ids
    assert len(catalog_ids) == 8

    # Estado inicial: Mesa de Trabajo Vacía
    assert bridge.fileCount == 0
    assert bridge.inputContextState == "empty"
    assert bridge.isToolSelected is False
    assert bridge.suggestedTools == []

    # 2. Caso 1: Soltar 1 archivo PDF -> muestra exclusivamente las 6 herramientas individuales
    bridge.addSingleFilePath(str(sample_pdf_5p))
    assert bridge.fileCount == 1
    assert bridge.inputContextState == "single_pdf"
    assert bridge.isToolSelected is False
    single_ids = [t["id"] for t in bridge.suggestedTools]
    assert set(single_ids) == {
        "organize",
        "split",
        "compress",
        "pdf_to_images",
        "watermark",
        "sign",
    }
    assert "merge" not in single_ids
    assert "images_to_pdf" not in single_ids

    # 3. Caso 2 (y Caso Borde): Agregar un segundo PDF estando en la vista de 1 PDF recalcula y destaca "Unir PDF"
    bridge.addSingleFilePath(str(sample_pdf_3p))
    assert bridge.fileCount == 2
    assert bridge.inputContextState == "multi_pdf"
    multi_suggestions = bridge.suggestedTools
    assert multi_suggestions[0]["id"] == "merge"
    assert multi_suggestions[0]["isPrimary"] is True
    assert {t["id"] for t in multi_suggestions} == {
        "merge",
        "compress",
        "pdf_to_images",
        "watermark",
    }

    # Si se quita el segundo PDF, regresa dinámicamente al Caso 1 (1 PDF)
    bridge.removeFileAt(1)
    assert bridge.fileCount == 1
    assert bridge.inputContextState == "single_pdf"

    # Si se eliminan todos los archivos, regresa a "Mesa de Trabajo Vacía"
    bridge.removeFileAt(0)
    assert bridge.fileCount == 0
    assert bridge.inputContextState == "empty"
    assert bridge.isToolSelected is False

    # 4. Caso 3: Imágenes (.png, .jpg, .webp) -> destaca "Imágenes a PDF"
    webp_path = tmp_path / "postal_floral.webp"
    Image.new("RGB", (320, 440), color=(248, 184, 176)).save(webp_path, "WEBP")

    bridge.addFileUrls([str(sample_images[0]), str(webp_path)])
    assert bridge.fileCount == 2
    assert bridge.inputContextState == "images_only"
    img_suggestions = bridge.suggestedTools
    assert len(img_suggestions) == 1
    assert img_suggestions[0]["id"] == "images_to_pdf"
    assert img_suggestions[0]["isPrimary"] is True
    assert "Encuadernar postales en un PDF" in img_suggestions[0]["subtitle"]

    # 5. Caso 4: Mezcla de PDFs e imágenes -> ofrece unir todo o filtrar por tipo
    bridge.addSingleFilePath(str(sample_pdf_3p))
    assert bridge.fileCount == 3
    assert bridge.inputContextState == "mixed"
    assert bridge.pdfCount == 1
    assert bridge.imageCount == 2
    mixed_suggestions = bridge.suggestedTools
    assert mixed_suggestions[0]["id"] == "merge"
    assert mixed_suggestions[0]["isPrimary"] is True

    # Filtrar conservando solo imágenes regresa al Caso 3
    bridge.keepOnlyImages()
    assert bridge.fileCount == 2
    assert bridge.inputContextState == "images_only"


def test_edge_cases_unsupported_formats_and_zero_byte_files(
    sample_pdf_5p: Path, tmp_path: Path, qtbot
) -> None:
    """Verifica aviso amigable e ignorado de formatos no soportados (.docx, .exe, .zip) y archivos de 0 bytes."""
    store = OperationHistoryStore(storage_path=tmp_path / "edge_hist.json")
    app_wrapper = CoquetteQuickApp(history_store=store)
    window = app_wrapper.load_main_qml()
    bridge = app_wrapper.studio_bridge
    qtbot.waitExposed(window)

    docx_file = tmp_path / "carta.docx"
    docx_file.write_text("contenido word", encoding="utf-8")
    zip_file = tmp_path / "archivo.zip"
    zip_file.write_bytes(b"PK\x03\x04")
    exe_file = tmp_path / "instalador.exe"
    exe_file.write_bytes(b"MZ")
    empty_pdf = tmp_path / "vacio.pdf"
    empty_pdf.write_bytes(b"")

    errors_received: list[str] = []
    bridge.errorOccurred.connect(errors_received.append)

    # Soltar archivos inválidos junto con 1 PDF válido: ignora los inválidos, muestra aviso y carga el válido
    bridge.addFileUrls(
        [str(docx_file), str(zip_file), str(exe_file), str(empty_pdf), str(sample_pdf_5p)]
    )
    assert bridge.fileCount == 1
    assert bridge.queuedFiles[0]["name"] == sample_pdf_5p.name
    assert len(errors_received) >= 2
    assert any("Formato no compatible" in msg for msg in errors_received)

    banner = window.findChild(QQuickItem, "friendlyNoticeBanner")
    assert banner is not None
    assert banner.isVisible() is True

    window.close()


def test_bridge_file_ingestion_organizer_and_encrypted_pdf_unlock_on_load(
    sample_pdf_5p: Path, encrypted_pdf: tuple[Path, str], tmp_path: Path, qtbot
) -> None:
    """Verifica ingesta, Page Organizer (rotar, duplicar, eliminar, reordenar) y apertura de PDF cifrado."""
    store = OperationHistoryStore(storage_path=tmp_path / "bridge_hist.json")
    app_wrapper = CoquetteQuickApp(history_store=store)
    bridge = app_wrapper.studio_bridge

    # Ingesta de PDF de 5 páginas y poblamiento del Page Organizer
    bridge.addSingleFilePath(str(sample_pdf_5p))
    assert bridge.fileCount == 1
    assert bridge.organizerPageCount == 5

    # Transicionar a la herramienta "organize"
    bridge.selectTool("organize")
    assert bridge.isToolSelected is True
    assert bridge.workspaceMode == "organizer"

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

    # Volver a la mesa de trabajo conserva el archivo cargado
    bridge.returnToWorkbench()
    assert bridge.isToolSelected is False
    assert bridge.workspaceMode == "dropzone"
    assert bridge.fileCount == 1

    # Ingesta de PDF cifrado emite señal passwordRequired y luego se desbloquea en memoria
    locked_path, pwd = encrypted_pdf
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


def test_qml_layout_contextual_cards_footer_cta_organizer_reindexing_and_viewer_modes(
    sample_pdf_5p: Path, tmp_path: Path, qtbot
) -> None:
    """Verifica tarjetas contextuales en QML, ausencia de recortes en Footer, reindexación en Organizador y modos/sello en Visor."""
    import pymupdf as fitz

    store = OperationHistoryStore(storage_path=tmp_path / "layout_hist.json")
    app_wrapper = CoquetteQuickApp(history_store=store)
    window = app_wrapper.load_main_qml()
    bridge = app_wrapper.studio_bridge
    qtbot.waitExposed(window)

    # 1. Al soltar 1 PDF en la Mesa de Trabajo, se despliega el panel contextual con 6 tarjetas sugeridas
    bridge.addSingleFilePath(str(sample_pdf_5p))
    bridge.setOutputDirectory(str(tmp_path))
    qtbot.wait(50)

    ctx_panel = window.findChild(QQuickItem, "contextualToolsPanel")
    assert ctx_panel is not None and ctx_panel.isVisible() is True
    suggested_cards = _collect_items_by_prefix(window.contentItem(), "suggestedToolCard_")
    assert len(suggested_cards) == 6
    assert {c.property("toolId") for c in suggested_cards} == {
        "organize",
        "split",
        "compress",
        "pdf_to_images",
        "watermark",
        "sign",
    }

    # 2. Al elegir "organize", transiciona a PageOrganizerView y muestra el botón "Volver a la mesa de trabajo"
    footer_bar = window.findChild(QQuickItem, "footerBar")
    cta_btn = window.findChild(QQuickItem, "mainCtaButton")
    assert footer_bar is not None and cta_btn is not None
    # En la Mesa de Trabajo con 1 PDF ("organize" sugerido), el botón indica que abre la pantalla del organizador
    assert cta_btn.property("text") == "Abrir organizador →"

    bridge.selectTool("organize")
    qtbot.wait(50)
    back_btn = window.findChild(QQuickItem, "backToWorkbenchButton")
    assert back_btn is not None and back_btn.isVisible() is True
    assert cta_btn.property("text") == "Guardar pliego organizado"
    assert cta_btn.width() >= cta_btn.implicitWidth()
    assert cta_btn.x() + cta_btn.width() <= footer_bar.width()

    # 3. En "Organizar Páginas": mover última página al inicio, duplicar y verificar etiquetas correlativas 1..N
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
    bridge.selectTool("sign")
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
    """Verifica el flujo contextual en estado vacío y con 3 archivos en cola destacando 'Unir PDF'."""
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

    # 1. Verificar Estado 1 (Mesa de Trabajo Vacía)
    assert bridge.fileCount == 0
    assert bridge.totalQueuedPages == 0
    assert bridge.isToolSelected is False
    assert bridge.statusMessage == "Listo para trabajar en tu escritorio de papelería."

    empty_container = window.findChild(QQuickItem, "emptyStateContainer")
    queued_container = window.findChild(QQuickItem, "queuedStateContainer")
    cta_btn = window.findChild(QQuickItem, "mainCtaButton")
    left_washi = (_collect_items_by_prefix(window.contentItem(), "leftWashiTape") or [None])[0]
    right_washi = (_collect_items_by_prefix(window.contentItem(), "rightWashiTape") or [None])[0]
    header_sub = window.findChild(QQuickItem, "headerSubtitleText")

    assert empty_container is not None and queued_container is not None
    assert empty_container.isVisible() is True
    assert queued_container.isVisible() is False
    assert cta_btn is not None and cta_btn.property("enabledButton") is False
    assert left_washi is not None and right_washi is not None
    assert left_washi.isVisible() is True and right_washi.isVisible() is True
    assert header_sub is not None and "Suelta primero" in header_sub.property("text")

    # 2. Cargar 3 archivos PDF en la cola y verificar detección automática de "Unir PDF" como principal
    bridge.addFileUrls([str(sample_pdf_5p), str(sample_pdf_3p), str(long_name_pdf)])
    qtbot.wait(50)

    assert bridge.fileCount == 3
    assert bridge.totalQueuedPages == 9
    assert bridge.inputContextState == "multi_pdf"
    assert bridge.activeTool == "merge"
    assert bridge.workbenchSubtitle == "3 pliegos listos"
    assert empty_container.isVisible() is False
    assert queued_container.isVisible() is True
    assert cta_btn.property("enabledButton") is True
    assert cta_btn.property("text") == "Unir 3 pliegos"
    # Las cintas washi y ramitas de esquina se ocultan mientras haya archivos
    assert left_washi.isVisible() is False and right_washi.isVisible() is False

    primary_title = window.findChild(QQuickItem, "primarySuggestedTitle")
    assert primary_title is not None and primary_title.property("text") == "Unir PDF"

    queue_header_count = window.findChild(QQuickItem, "queueHeaderCountText")
    assert queue_header_count is not None
    assert "3 pliegos · 9 páginas ·" in queue_header_count.property("text")

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

    # 4. Probar "Vaciar cola" y retorno limpio al Estado 1 (Mesa de Trabajo Vacía)
    bridge.clearFiles()
    # Espera a que termine el fundido de salida de las tarjetas (Theme.animExit = 120 ms)
    qtbot.wait(QUEUE_EXIT_SETTLE_MS)
    assert bridge.fileCount == 0
    assert bridge.totalQueuedPages == 0
    assert bridge.isToolSelected is False
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
    """Los SVG decorativos y de herramientas deben renderizar en QSvgRenderer y no usar CSS ni clases."""
    from PySide6.QtSvg import QSvgRenderer

    expected_svgs = (
        "botanical_corner.svg",
        "washi_tape.svg",
        "tool_merge.svg",
        "tool_split.svg",
        "tool_organize.svg",
        "tool_compress.svg",
        "tool_protect.svg",
        "tool_unlock.svg",
        "tool_pdf_to_images.svg",
        "tool_images_to_pdf.svg",
        "tool_watermark.svg",
        "tool_sign.svg",
    )
    for name in expected_svgs:
        text = (ICONS_DIR / name).read_text(encoding="utf-8")
        assert "<style" not in text and "class=" not in text, name
        assert 'baseProfile="tiny"' in text, name
        assert QSvgRenderer(text.encode("utf-8")).isValid(), name


def test_workbench_redesign_13_states_and_hierarchy(
    sample_pdf_5p: Path,
    sample_pdf_3p: Path,
    sample_images: list[Path],
    encrypted_pdf: tuple[Path, str],
    tmp_path: Path,
    qtbot,
) -> None:
    """Verifica los estados obligatorios de la nueva Mesa de Trabajo: duplicados, PDF corrupto, carpeta inválida y textos de CTA."""
    store = OperationHistoryStore(storage_path=tmp_path / "wb_redesign.json")
    app_wrapper = CoquetteQuickApp(history_store=store)
    window = app_wrapper.load_main_qml()
    bridge = app_wrapper.studio_bridge
    qtbot.waitExposed(window)

    # 1. Nombre real con ñ, tildes y extensión en mayúsculas: "WB-9-SamuelGarduñoGamboa.PDF"
    special_pdf = tmp_path / "WB-9-SamuelGarduñoGamboa.PDF"
    special_pdf.write_bytes(sample_pdf_5p.read_bytes())
    bridge.addSingleFilePath(str(special_pdf))
    qtbot.wait(40)
    assert bridge.fileCount == 1
    assert bridge.workbenchSubtitle == "1 pliego en la mesa"
    assert bridge.primaryCtaText == "Abrir organizador →"

    # Con 1 solo archivo, el círculo numerado (#1) debe estar oculto
    badge_0 = (_collect_items_by_prefix(window.contentItem(), "orderNumberBadge_0") or [None])[0]
    assert badge_0 is not None and badge_0.isVisible() is False

    # Cambiar herramienta en la mesa actualiza el texto del botón principal hacia su pantalla de configuración
    bridge.chooseWorkbenchTool("split")
    assert bridge.primaryCtaText == "Elegir páginas →"
    bridge.chooseWorkbenchTool("sign")
    assert bridge.primaryCtaText == "Abrir visor →"
    bridge.chooseWorkbenchTool("compress")
    assert bridge.primaryCtaText == "Configurar compresión →"
    bridge.chooseWorkbenchTool("pdf_to_images")
    assert bridge.primaryCtaText == "Configurar láminas →"
    bridge.chooseWorkbenchTool("watermark")
    assert bridge.primaryCtaText == "Configurar filigrana →"

    # En herramientas con opciones, triggerPrimaryAction desde la mesa abre la configuración (NO ejecuta directo)
    bridge.triggerPrimaryAction()
    qtbot.wait(40)
    assert bridge.isToolSelected is True
    assert bridge.primaryCtaText == "Estampar filigrana"

    # Regresar a la mesa de trabajo restaura el estado y la herramienta principal
    bridge.returnToWorkbench()
    qtbot.wait(40)
    assert bridge.isToolSelected is False
    assert bridge.primaryCtaText == "Abrir organizador →"

    # 2. Detección de duplicados: agregar el mismo archivo lo ignora con aviso breve "Ya está en la mesa"
    bridge.addSingleFilePath(str(special_pdf))
    assert bridge.fileCount == 1
    assert "Ya está en la mesa" in bridge.lastNoticeMessage

    # 3. PDF dañado (>0 bytes): se agrega como tarjeta de error ("No se pudo leer") y se excluye de validFileCount
    corrupted_pdf = tmp_path / "pliego_danado.pdf"
    corrupted_pdf.write_bytes(b"%PDF-1.4 DATOS CORRUPTOS INVALIDOS")
    bridge.addSingleFilePath(str(corrupted_pdf))
    qtbot.wait(40)
    assert bridge.fileCount == 2
    assert bridge.validFileCount == 1
    assert bridge.hasCorruptedFiles is True
    assert bridge.queuedFiles[1]["isCorrupted"] is True
    assert bridge.queuedFiles[1]["status"] == "No se pudo leer"
    # Con 2 tarjetas en la cola, el círculo numerado ahora es visible
    badge_0_after = (_collect_items_by_prefix(window.contentItem(), "orderNumberBadge_0") or [None])[0]
    assert badge_0_after is not None and badge_0_after.isVisible() is True

    # Quitar el archivo dañado
    bridge.removeFileAt(1)
    assert bridge.fileCount == 1
    assert bridge.hasCorruptedFiles is False

    # 4. Carpeta de guardado inválida: bloquea ejecución y muestra error claro sin perder la cola
    fake_file_as_dir = tmp_path / "no_es_carpeta.txt"
    fake_file_as_dir.write_text("archivo", encoding="utf-8")
    bridge.setOutputDirectory(str(fake_file_as_dir))
    assert bridge.isOutputDirectoryValid is False
    assert "no es una carpeta válida" in bridge.outputDirectoryError
    assert bridge.fileCount == 1

    # Restaurar carpeta válida
    bridge.setOutputDirectory(str(tmp_path))
    assert bridge.isOutputDirectoryValid is True

    # 5. PDF protegido con clave: sugiere "Abrir sello" y muestra miniatura con candado sin crash
    bridge.clearFiles()
    locked_path, pwd = encrypted_pdf
    bridge.addSingleFilePath(str(locked_path))
    qtbot.wait(40)
    assert bridge.hasLockedFiles is True
    assert bridge.primaryCtaText == "Abrir sello"
    locked_thumb = app_wrapper.image_provider.requestImage(
        f"0?path={locked_path}&dpi=72&locked=1", QSize(), QSize(112, 144)
    )
    assert not locked_thumb.isNull()

    window.close()


def test_header_title_botanical_corners_washi_and_cta_hint(
    tmp_path: Path, qtbot
) -> None:
    """Título editorial visible, 4 esquinas botánicas íntegras, washi SVG, margen de cabecera y tooltip del CTA."""
    store = OperationHistoryStore(storage_path=tmp_path / "visual_hist.json")
    app_wrapper = CoquetteQuickApp(history_store=store)
    window = app_wrapper.load_main_qml()
    qtbot.waitExposed(window)
    root = window.contentItem()

    # 1. Título principal de la cabecera visible y sin truncar
    title = window.findChild(QQuickItem, "headerPrimaryTitle")
    assert title is not None
    assert title.property("truncated") is False
    assert title.property("text") == "Mesa de Trabajo Floral"

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


def test_all_tools_with_options_navigate_to_config_screen_and_do_not_execute_directly(
    sample_pdf_5p: Path,
    tmp_path: Path,
    qtbot,
) -> None:
    """Verifica que todos los botones de herramientas con opciones naveguen a su pantalla y nunca ejecuten directo."""
    from ui.bridge import TOOLS_WITH_OPTIONS

    store = OperationHistoryStore(storage_path=tmp_path / "wb_nav_test.json")
    app_wrapper = CoquetteQuickApp(history_store=store)
    window = app_wrapper.load_main_qml()
    bridge = app_wrapper.studio_bridge
    qtbot.waitExposed(window)

    bridge.addSingleFilePath(str(sample_pdf_5p))
    qtbot.wait(40)
    assert bridge.fileCount == 1

    expected_nav_labels = {
        "organize": "Abrir organizador →",
        "split": "Elegir páginas →",
        "sign": "Abrir visor →",
        "compress": "Configurar compresión →",
        "pdf_to_images": "Configurar láminas →",
        "watermark": "Configurar filigrana →",
    }
    expected_exec_labels = {
        "organize": "Guardar pliego organizado",
        "split": "Extraer páginas",
        "sign": "Firmar y guardar",
        "compress": "Comprimir 1 pliego",
        "pdf_to_images": "Revelar páginas",
        "watermark": "Estampar filigrana",
    }

    # Probar que cada herramienta con opciones muestra el texto de navegación en la mesa
    # y que al activar la acción principal transiciona a su pantalla sin lanzar ejecución de fondo
    for tool_id in TOOLS_WITH_OPTIONS:
        bridge.chooseWorkbenchTool(tool_id)
        assert bridge.isToolSelected is False
        assert bridge.primaryCtaText == expected_nav_labels[tool_id]

        # Al pulsar la acción principal desde la mesa, debe entrar a la pantalla (isToolSelected = True)
        bridge.triggerPrimaryAction()
        qtbot.wait(20)
        assert bridge.isToolSelected is True
        assert bridge.isBusy is False
        assert bridge.primaryCtaText == expected_exec_labels[tool_id]

        # Volver a la mesa de trabajo
        bridge.returnToWorkbench()
        qtbot.wait(20)
        assert bridge.isToolSelected is False

    # Probar navegación directa mediante selección (como al hacer clic en chips secundarios)
    bridge.selectTool("watermark")
    qtbot.wait(20)
    assert bridge.isToolSelected is True
    assert bridge.activeTool == "watermark"
    assert bridge.isBusy is False
    assert bridge.primaryCtaText == "Estampar filigrana"

    config_panel = window.findChild(QQuickItem, "configPanels")
    assert config_panel is not None and config_panel.isVisible() is True

    window.close()


