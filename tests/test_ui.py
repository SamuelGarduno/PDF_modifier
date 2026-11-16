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
    MIN_WINDOW_HEIGHT,
    MIN_WINDOW_WIDTH,
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
    assert INITIAL_WINDOW_WIDTH == 900
    assert INITIAL_WINDOW_HEIGHT == 640
    assert MIN_WINDOW_WIDTH == 880
    assert MIN_WINDOW_HEIGHT == 520
    assert SIDEBAR_FIXED_WIDTH == 260

    qss = generate_stationery_qss()
    for token in (SURFACE_LIGHT, BACKGROUND_DARK, PRIMARY, SECONDARY, ACCENT):
        assert token in qss


def test_qtquick_window_frameless_full_width_without_sidebar(
    tmp_path: Path, qtbot
) -> None:
    """Verifica que la ventana QtQuick inicie sin barra lateral izquierda, con 900x640 y límites responsivos."""
    store = OperationHistoryStore(storage_path=tmp_path / "ui_hist.json")
    app_wrapper = CoquetteQuickApp(history_store=store)
    window = app_wrapper.load_main_qml()
    assert isinstance(window, QQuickWindow)

    # Verificar FramelessWindowHint y dimensiones iniciales y mínimas (900x640, min <= 880x520)
    flags = window.flags()
    assert bool(flags & Qt.WindowType.FramelessWindowHint)
    assert window.width() == 900
    assert window.height() == 640
    assert window.minimumWidth() <= 880
    assert window.minimumHeight() <= 520

    # Verificar que NO exista leftSidebar ni quickSearchInput (Ctrl+K)
    sidebar = window.findChild(QQuickItem, "leftSidebar")
    assert sidebar is None
    search_input = window.findChild(QQuickItem, "quickSearchInput")
    assert search_input is None

    # Verificar que el Lienzo Central (Mesa de Trabajo) ocupe el 100% del ancho de la ventana
    workspace = window.findChild(QQuickItem, "mainWorkspace")
    assert workspace is not None
    assert int(workspace.width()) == 900
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


def test_bloque1_window_900_and_responsive_screens(
    sample_pdf_5p: Path, tmp_path: Path, qtbot
) -> None:
    """Verifica Bloque 1: tamaño inicial 900x640, min 880x520 y adaptabilidad en las 4 pantallas."""
    store = OperationHistoryStore(storage_path=tmp_path / "b1_hist.json")
    app_wrapper = CoquetteQuickApp(history_store=store)
    window = app_wrapper.load_main_qml()
    bridge = app_wrapper.studio_bridge
    qtbot.waitExposed(window)

    # 1. Dimensiones iniciales y mínimas
    assert window.width() == 900
    assert window.height() == 640
    assert window.minimumWidth() <= 880
    assert window.minimumHeight() <= 520

    # 2. Pantalla 1: Mesa vacía
    empty_container = window.findChild(QQuickItem, "emptyStateContainer")
    assert empty_container is not None and empty_container.isVisible() is True
    assert empty_container.width() <= window.width()

    # 3. Pantalla 2: Mesa con archivos (a 900 px y a 880 px)
    bridge.addSingleFilePath(str(sample_pdf_5p))
    qtbot.wait(QUEUE_EXIT_SETTLE_MS)
    queued_container = window.findChild(QQuickItem, "queuedStateContainer")
    assert queued_container is not None and queued_container.isVisible() is True
    assert queued_container.width() <= window.width()

    footer_bar = window.findChild(QQuickItem, "footerBar")
    assert footer_bar is not None and footer_bar.width() <= window.width()

    # Probar ancho mínimo 880 px
    window.setWidth(880)
    window.setHeight(520)
    qtbot.wait(50)
    assert queued_container.width() <= window.width()
    assert footer_bar.width() <= window.width()

    # 4. Pantalla 3: Organizar Páginas
    bridge.selectTool("organize")
    qtbot.wait(50)
    organizer_view = window.findChild(QQuickItem, "pageOrganizerView")
    assert organizer_view is not None and organizer_view.isVisible() is True
    assert organizer_view.width() <= window.width()

    # 5. Pantalla 4: Visor y Firma
    bridge.selectTool("sign")
    qtbot.wait(50)
    viewer_view = window.findChild(QQuickItem, "pdfViewerSignView")
    assert viewer_view is not None and viewer_view.isVisible() is True
    assert viewer_view.width() <= window.width()

    # 6. Pantallas de configuración de herramientas (compress, watermark, split)
    for tool_id in ("compress", "watermark", "split"):
        bridge.selectTool(tool_id)
        qtbot.wait(50)
        config_panel = window.findChild(QQuickItem, "configPanels")
        assert config_panel is not None and config_panel.isVisible() is True
        assert config_panel.width() <= window.width()

    window.close()


def test_bloque2_paper_background_continuity_across_screens(
    sample_pdf_5p: Path, tmp_path: Path, qtbot
) -> None:
    """Verifica Bloque 2: PaperBackground continuo y marcos transparentes en todas las pantallas."""
    store = OperationHistoryStore(storage_path=tmp_path / "b2_hist.json")
    app_wrapper = CoquetteQuickApp(history_store=store)
    window = app_wrapper.load_main_qml()
    bridge = app_wrapper.studio_bridge
    qtbot.waitExposed(window)

    paper_bg = window.findChild(QQuickItem, "mainPaperBackground")
    assert paper_bg is not None
    assert paper_bg.property("lineSpacing") == 28
    assert paper_bg.property("showMarginLine") is True
    assert paper_bg.property("marginX") == 72

    line_color = paper_bg.property("lineColor")
    assert 0.05 <= line_color.alphaF() <= 0.09

    outer_frame = window.findChild(QQuickItem, "outerPaperFrame")
    assert outer_frame is not None
    assert outer_frame.property("color").alphaF() == 0.0

    # Estado 1: Mesa vacía -> transparente
    assert bridge.fileCount == 0
    assert outer_frame.property("color").alphaF() == 0.0

    # Estado 2: Mesa con archivos -> transparente
    bridge.addSingleFilePath(str(sample_pdf_5p))
    qtbot.wait(QUEUE_EXIT_SETTLE_MS)
    assert bridge.fileCount == 1
    assert outer_frame.property("color").alphaF() == 0.0

    # Estado 3: Organizar páginas -> transparente
    bridge.selectTool("organize")
    qtbot.wait(50)
    assert bridge.isToolSelected is True
    assert outer_frame.property("color").alphaF() == 0.0

    # Estado 4: Visor y firma -> transparente
    bridge.selectTool("sign")
    qtbot.wait(50)
    assert outer_frame.property("color").alphaF() == 0.0

    # Estado 5: Herramientas de configuración -> transparente
    for tool_id in ("compress", "watermark", "split"):
        bridge.selectTool(tool_id)
        qtbot.wait(50)
        assert outer_frame.property("color").alphaF() == 0.0

    window.close()


def test_bloque3_queue_entry_exit_and_clear_animations(
    sample_pdf_5p: Path, sample_pdf_3p: Path, tmp_path: Path, qtbot
) -> None:
    """Verifica Bloque 3: entrada (fade+slide 20px+scale 0.96->1.0 en 220ms, stagger 50ms), salida 160ms y vaciado."""
    import pymupdf as fitz

    pdf_extra = tmp_path / "extra_b3.pdf"
    doc = fitz.open()
    doc.new_page().insert_text((72, 100), "Extra B3")
    doc.save(pdf_extra)
    doc.close()

    store = OperationHistoryStore(storage_path=tmp_path / "b3_hist.json")
    app_wrapper = CoquetteQuickApp(history_store=store)
    window = app_wrapper.load_main_qml()
    bridge = app_wrapper.studio_bridge
    qtbot.waitExposed(window)

    dropzone = window.findChild(QQuickItem, "dropzoneView")
    assert dropzone is not None

    # 1. Agregar 3 archivos a la vez -> stagger 0, 50, 100 ms; dur 220 ms; offset 20 px; scaleFrom 0.96
    bridge.addFileUrls([str(sample_pdf_5p), str(sample_pdf_3p), str(pdf_extra)])
    qtbot.wait(25)

    cards = _collect_items_by_prefix(window.contentItem(), "queuedFileCard_")
    assert len(cards) == 3
    for idx, card in enumerate(sorted(cards, key=lambda c: c.property("rowIndex"))):
        entry = card.property("fileEntry")
        assert int(entry.property("enterDuration")) == 220
        assert int(entry.property("enterOffset")) == 20
        assert abs(float(entry.property("enterScaleFrom")) - 0.96) < 1e-4
        assert int(entry.property("enterDelay")) == idx * 50

    # La tercera tarjeta (delay=100ms) sigue en estado inicial de entrada a los 25ms
    card_2 = [c for c in cards if c.property("rowIndex") == 2][0]
    assert card_2.opacity() < 1.0
    assert card_2.scale() < 1.0

    # Al terminar la entrada (220ms + 100ms stagger), todas quedan en reposo (opacity=1, scale=1)
    qtbot.wait(380)
    for card in _collect_items_by_prefix(window.contentItem(), "queuedFileCard_"):
        assert abs(card.opacity() - 1.0) < 1e-3
        assert abs(card.scale() - 1.0) < 1e-3

    # 2. Quitar el primer archivo -> salida de 160ms y reacomodo de las inferiores en 180ms
    bridge.removeFileAt(0)
    qtbot.wait(240)
    remaining_cards = [
        c for c in _collect_items_by_prefix(window.contentItem(), "queuedFileCard_")
        if c.property("rowIndex") >= 0
    ]
    assert len(remaining_cards) == 2

    # 3. Vaciar cola -> activa queueExitInProgress durante 160ms y luego pasa al estado vacío
    bridge.clearFiles()
    assert dropzone.property("queueExitInProgress") is True
    assert dropzone.property("showQueuedState") is True
    qtbot.wait(220)
    assert dropzone.property("queueExitInProgress") is False
    assert dropzone.property("showQueuedState") is False

    # 4. Lote masivo (>10 archivos) -> fade grupal de 120ms sin escalonado ni slide ni escala
    bulk_paths = []
    for i in range(12):
        p = tmp_path / f"bulk_{i}.pdf"
        p.write_bytes(pdf_extra.read_bytes())
        bulk_paths.append(str(p))
    bridge.addFileUrls(bulk_paths)
    qtbot.wait(200)
    bulk_cards = _collect_items_by_prefix(window.contentItem(), "queuedFileCard_")
    assert len(bulk_cards) > 0
    first_bulk_entry = bulk_cards[0].property("fileEntry")
    assert int(first_bulk_entry.property("enterDuration")) == 120
    assert int(first_bulk_entry.property("enterOffset")) == 0
    assert int(first_bulk_entry.property("enterDelay")) == 0
    assert abs(float(first_bulk_entry.property("enterScaleFrom")) - 1.0) < 1e-4

    window.close()


def test_bloque4_viewer_zoom_stroke_widths_and_png_signature_edge_cases(
    sample_pdf_5p: Path, tmp_path: Path, qtbot
) -> None:
    """Verifica el Bloque 4 completo (4a y 4b): zoom 50/100/200%, 3 grosores, Firma PNG con casos borde, persistencia por página y guardado."""
    import pymupdf as fitz
    from PySide6.QtCore import Qt, QUrl
    from PySide6.QtGui import QColor, QImage, QPainter, QPen

    store = OperationHistoryStore(storage_path=tmp_path / "b4_hist.json")
    app_wrapper = CoquetteQuickApp(history_store=store)
    window = app_wrapper.load_main_qml()
    bridge = app_wrapper.studio_bridge
    qtbot.waitExposed(window)

    bridge.addSingleFilePath(str(sample_pdf_5p))
    bridge.setOutputDirectory(str(tmp_path))
    bridge.selectTool("sign")
    qtbot.wait(60)

    viewer_view = window.findChild(QQuickItem, "pdfViewerSignView")
    sig_canvas = window.findChild(QQuickItem, "signatureCanvas")
    png_box = window.findChild(QQuickItem, "pngSignatureBox")
    assert viewer_view is not None and sig_canvas is not None and png_box is not None

    # 1. Antialiasing y smooth activados en el Canvas
    assert sig_canvas.antialiasing() is True
    assert sig_canvas.smooth() is True

    # 2. Probar el visor a 50%, 100% y 200% de zoom con DPI dinámico (zoom * devicePixelRatio)
    bridge.setViewerDevicePixelRatio(1.25)
    for zoom_val in (0.5, 1.0, 2.0):
        bridge.setViewerZoom(zoom_val)
        qtbot.wait(30)
        expected_dpi = max(72, min(360, int(round(144.0 * zoom_val * 1.25))))
        assert f"dpi={expected_dpi}" in bridge.currentViewerPageUrl
    bridge.setViewerZoom(1.0)

    # 3. 3 grosores de trazo (Fino predeterminado, Medio, Grueso)
    assert bridge.signatureStrokeWidthKey == "fine"
    assert abs(bridge.signatureStrokeWidthPt - 1.75) < 1e-4

    stroke_btns = _collect_items_by_prefix(window.contentItem(), "strokeWidthOption_")
    assert len(stroke_btns) == 3

    bridge.setSignatureStrokeWidthKey("medium")
    assert bridge.signatureStrokeWidthKey == "medium"
    assert abs(bridge.signatureStrokeWidthPt - 3.0) < 1e-4
    bridge.setSignatureStrokeWidthKey("bold")
    assert bridge.signatureStrokeWidthKey == "bold"
    assert abs(bridge.signatureStrokeWidthPt - 4.5) < 1e-4
    bridge.setSignatureStrokeWidthKey("fine")

    # 4. Casos borde de Firma PNG:
    # 4.1 Cancelar el diálogo ("") -> no da error ni cambia estado
    bridge.clearNoticeMessage()
    bridge.setSignatureImagePath("")
    assert bridge.lastNoticeMessage == ""
    assert bridge.signatureImagePath == ""

    # 4.2 Extensión no soportada (.webp)
    webp_file = tmp_path / "sello.webp"
    webp_file.write_bytes(b"RIFFxxxxWEBPVP8 ")
    bridge.setSignatureImagePath(str(webp_file))
    assert bridge.lastNoticeIsError is True
    assert "PNG" in bridge.lastNoticeMessage
    assert bridge.signatureImagePath == ""

    # 4.3 PNG de 0 bytes
    zero_png = tmp_path / "vacio.png"
    zero_png.write_bytes(b"")
    bridge.setSignatureImagePath(str(zero_png))
    assert bridge.lastNoticeIsError is True
    assert "vacío" in bridge.lastNoticeMessage

    # 4.4 PNG corrupto
    corrupt_png = tmp_path / "corrupto.png"
    corrupt_png.write_bytes(b"\x89PNG\r\n\x1a\ndatos_corruptos_invalidos")
    bridge.setSignatureImagePath(str(corrupt_png))
    assert bridge.lastNoticeIsError is True
    assert "dañado" in bridge.lastNoticeMessage or "válida" in bridge.lastNoticeMessage

    # 4.5 PNG 100% transparente
    trans_png = tmp_path / "transparente_100.png"
    t_img = QImage(160, 80, QImage.Format.Format_ARGB32)
    t_img.fill(Qt.GlobalColor.transparent)
    t_img.save(str(trans_png), "PNG")
    bridge.setSignatureImagePath(str(trans_png))
    assert bridge.lastNoticeIsError is True
    assert "transparente" in bridge.lastNoticeMessage

    # 4.6 PNG válido con fondo transparente y ruta con espacios, tildes y eñes (vía URL file:///)
    special_dir = tmp_path / "Rincón de María Ñañez — Papelería 2026"
    special_dir.mkdir(parents=True, exist_ok=True)
    valid_png = special_dir / "rúbrica oficial niña áéíóú.png"
    v_img = QImage(300, 120, QImage.Format.Format_ARGB32)
    v_img.fill(Qt.GlobalColor.transparent)
    painter = QPainter(v_img)
    pen = QPen(QColor(10, 10, 20, 255))
    pen.setWidth(10)
    painter.setPen(pen)
    painter.drawLine(25, 60, 275, 60)
    painter.end()
    v_img.save(str(valid_png), "PNG")

    file_url = QUrl.fromLocalFile(str(valid_png)).toString()
    bridge.setSignatureImagePath(file_url)
    qtbot.wait(40)

    assert Path(bridge.signatureImagePath) == valid_png
    assert png_box.isVisible() is True
    # Ancho inicial ~25% del ancho de página, centrado y respetando proporción (300/120 = 2.5)
    rect_p0 = bridge.signatureImageRect
    assert abs(rect_p0["width"] - 0.25) < 0.02
    assert abs(rect_p0["x"] - 0.375) < 0.02
    assert abs(rect_p0["aspect"] - 2.5) < 0.05

    # Mover y redimensionar la firma PNG en la página 1 (índice 0) y añadir trazo vectorial
    bridge.setSignatureImageRect(0.52, 0.62, 0.30, 0.12)
    bridge.addFreehandStroke(
        [{"x": 0.15, "y": 0.22}, {"x": 0.25, "y": 0.18}, {"x": 0.35, "y": 0.24}]
    )
    assert bridge.freehandStrokeCount == 1

    # 5. Cambiar a la página 2 (índice 1), añadir un trazo grueso y una imagen enorme (>4000 px)
    bridge.setViewerPageIndex(1)
    qtbot.wait(30)
    assert bridge.viewerPageIndex == 1
    assert bridge.freehandStrokeCount == 0
    assert bridge.signatureImagePath == ""

    bridge.setSignatureStrokeWidthKey("bold")
    bridge.addFreehandStroke(
        [{"x": 0.20, "y": 0.50}, {"x": 0.40, "y": 0.52}, {"x": 0.60, "y": 0.48}]
    )
    assert bridge.freehandStrokeCount == 1

    huge_png = tmp_path / "firma_gigante_4200px.png"
    h_img = QImage(4200, 1000, QImage.Format.Format_ARGB32)
    h_img.fill(Qt.GlobalColor.transparent)
    hp = QPainter(h_img)
    hpen = QPen(QColor(0, 0, 0, 255))
    hpen.setWidth(24)
    hp.setPen(hpen)
    hp.drawLine(200, 500, 4000, 500)
    hp.end()
    h_img.save(str(huge_png), "PNG")

    bridge.setSignatureImagePath(str(huge_png))
    qtbot.wait(40)
    assert bridge.signatureImagePath != ""
    scaled_loaded = QImage(bridge.signatureImagePath)
    assert not scaled_loaded.isNull()
    assert scaled_loaded.width() <= 2400

    # Quitar la firma PNG de la página 2 con el botón ✕ (clearSignatureImage)
    bridge.clearSignatureImage()
    assert bridge.signatureImagePath == ""

    # Volver a la página 1 (índice 0) y comprobar que tanto la firma PNG como el trazo siguen en su sitio exacto
    bridge.setViewerPageIndex(0)
    qtbot.wait(30)
    assert Path(bridge.signatureImagePath) == valid_png
    assert bridge.freehandStrokeCount == 1
    assert abs(bridge.signatureImageRect["x"] - 0.52) < 1e-3
    assert abs(bridge.signatureImageRect["y"] - 0.62) < 1e-3

    # 6. Guardar el PDF firmado y verificar que ambas páginas editadas (pág 1 y pág 2) cambiaron sus píxeles
    orig_bytes = sample_pdf_5p.read_bytes()
    with qtbot.waitSignal(bridge.operationCompleted, timeout=10000) as sig_blocker:
        bridge.executeActiveOperation()

    signed_out = Path(sig_blocker.args[1])
    assert signed_out.exists()
    assert signed_out != sample_pdf_5p
    assert sample_pdf_5p.read_bytes() == orig_bytes

    with fitz.open(sample_pdf_5p) as orig_doc, fitz.open(signed_out) as new_doc:
        for p_idx in (0, 1):
            p_before = orig_doc[p_idx].get_pixmap(dpi=110, alpha=False)
            p_after = new_doc[p_idx].get_pixmap(dpi=110, alpha=False)
            assert bytes(p_before.samples) != bytes(p_after.samples)

    window.close()


def test_bloque5_ui_dynamic_compression_estimates_and_cache(
    tmp_path: Path, qtbot
) -> None:
    """Verifica en la UI (Bloque 5): porcentajes dinámicos en los botones, caché por archivo, aviso de pliego ligero (<5%) y resultado final 'De X a Y (-Z%)'."""
    import io
    import random
    import pymupdf as fitz
    from PIL import Image

    # Crear un PDF con imágenes comprimibles y otro de solo texto ligero
    rng = random.Random(505)
    raw = bytearray(240 * 320 * 3)
    for idx in range(0, len(raw), 3):
        raw[idx] = rng.randint(50, 230)
        raw[idx + 1] = rng.randint(60, 220)
        raw[idx + 2] = rng.randint(70, 210)
    base_img = Image.frombytes("RGB", (240, 320), bytes(raw)).resize(
        (1400, 1800), Image.Resampling.BICUBIC
    )
    jpg_buf = io.BytesIO()
    base_img.save(jpg_buf, format="JPEG", quality=95)

    img_pdf = tmp_path / "pliego_con_fotos.pdf"
    doc = fitz.open()
    for _ in range(3):
        p = doc.new_page(width=595, height=842)
        p.insert_image(fitz.Rect(24, 24, 571, 818), stream=jpg_buf.getvalue())
    doc.save(str(img_pdf), deflate=True)
    doc.close()

    light_pdf = tmp_path / "pliego_ligero_texto.pdf"
    doc2 = fitz.open()
    p2 = doc2.new_page(width=595, height=842)
    p2.insert_text((72, 100), "Pliego ligero de solo texto.", fontsize=12)
    doc2.save(str(light_pdf), garbage=4, deflate=True)
    doc2.close()

    store = OperationHistoryStore(storage_path=tmp_path / "b5_hist.json")
    app_wrapper = CoquetteQuickApp(history_store=store)
    window = app_wrapper.load_main_qml()
    bridge = app_wrapper.studio_bridge
    qtbot.waitExposed(window)

    bridge.setOutputDirectory(str(tmp_path))
    bridge.addSingleFilePath(str(img_pdf))
    bridge.selectTool("compress")

    # Esperar a que termine la estimación asíncrona en segundo plano
    qtbot.waitUntil(lambda: not bridge.isEstimatingCompression, timeout=8000)
    qtbot.wait(40)

    # Verificar que los botones de nivel en QML muestran los porcentajes dinámicos reales (y no los fijos ~62%, ~38%, ~16%)
    level_btns = _collect_items_by_prefix(window.contentItem(), "compressLevelBtn_")
    est_txt = window.findChild(QQuickItem, "compressionEstimateText")
    assert len(level_btns) == 3 and est_txt is not None

    opts = {opt["key"]: opt["label"] for opt in bridge.compressionLevelOptions}
    assert "~" in opts["extreme"] and "%" in opts["extreme"]
    assert "Reducción estimada ~" in bridge.estimatedCompressionSummary

    # Verificar que el resultado quedó guardado en caché por (ruta, mtime, tamaño)
    assert len(bridge._compression_estimate_cache) == 1

    # Ejecutar la compresión y verificar el mensaje real "De X a Y (-Z%)"
    with qtbot.waitSignal(bridge.operationCompleted, timeout=10000) as blocker:
        bridge.executeActiveOperation()
    out_compressed = Path(blocker.args[1])
    assert out_compressed.exists()
    assert "De " in bridge.statusMessage and "(-" in bridge.statusMessage

    # Cambiar a un PDF de solo texto (<5% de reducción) y verificar el mensaje honesto
    bridge.clearFiles()
    bridge.addSingleFilePath(str(light_pdf))
    bridge.selectTool("compress")
    qtbot.waitUntil(lambda: not bridge.isEstimatingCompression, timeout=5000)
    qtbot.wait(40)
    assert "Este pliego ya está muy ligero" in bridge.estimatedCompressionSummary

    window.close()


def test_footer_bar_no_overlap_on_completion_at_900_and_880(
    sample_pdf_5p: Path, tmp_path: Path, qtbot
) -> None:
    """Verifica que al completar una acción ('Original intacto ✓', 'Abrir archivo', 'Mostrar en carpeta'), ningún elemento del footer se solape ni desborde a 900 px y 880 px."""
    from PySide6.QtCore import QPointF

    out_dir = tmp_path / "descargas"
    out_dir.mkdir(parents=True, exist_ok=True)

    store = OperationHistoryStore(storage_path=tmp_path / "footer_hist.json")
    app_wrapper = CoquetteQuickApp(history_store=store)
    window = app_wrapper.load_main_qml()
    bridge = app_wrapper.studio_bridge
    qtbot.waitExposed(window)

    bridge.setOutputDirectory(str(out_dir))
    bridge.addSingleFilePath(str(sample_pdf_5p))
    bridge.selectTool("compress")
    qtbot.waitUntil(lambda: not bridge.isEstimatingCompression, timeout=5000)

    with qtbot.waitSignal(bridge.operationCompleted, timeout=10000):
        bridge.executeActiveOperation()
    qtbot.wait(50)

    footer_bar = window.findChild(QQuickItem, "footerBar")
    folder_section = window.findChild(QQuickItem, "folderPickerSection")
    folder_box = window.findChild(QQuickItem, "outputFolderDisplayBox")
    choose_btn = window.findChild(QQuickItem, "chooseOutputFolderButton")
    center_box = window.findChild(QQuickItem, "centerStatusContainer")
    quick_row = window.findChild(QQuickItem, "quickActionsRow")
    intact_badge = window.findChild(QQuickItem, "originalIntactBadge")
    open_btn = window.findChild(QQuickItem, "footerOpenFileBtn")
    show_btn = window.findChild(QQuickItem, "footerShowFolderBtn")
    cta_btn = window.findChild(QQuickItem, "mainCtaButton")

    assert all(
        item is not None
        for item in (
            footer_bar,
            folder_section,
            folder_box,
            choose_btn,
            center_box,
            quick_row,
            intact_badge,
            open_btn,
            show_btn,
            cta_btn,
        )
    )
    assert quick_row.isVisible() is True

    def _x_span(item: QQuickItem) -> tuple[float, float]:
        tl = item.mapToItem(footer_bar, QPointF(0.0, 0.0))
        return tl.x(), tl.x() + item.width()

    for win_w, win_h in ((900, 640), (880, 520)):
        window.setWidth(win_w)
        window.setHeight(win_h)
        qtbot.wait(60)

        fw = footer_bar.width()
        fs_l, fs_r = _x_span(folder_section)
        ch_l, ch_r = _x_span(choose_btn)
        cb_l, cb_r = _x_span(center_box)
        qr_l, qr_r = _x_span(quick_row)
        cta_l, cta_r = _x_span(cta_btn)

        # Ningún hijo desborda su sección ni el footerBar
        assert fs_l >= 0.0
        assert ch_r <= fs_r + 1.0, f"'Elegir...' desborda folderPickerSection a {win_w}px: {ch_r} > {fs_r}"
        assert qr_l >= cb_l - 1.0 and qr_r <= cb_r + 1.0, (
            f"quickActionsRow desborda centerStatusContainer a {win_w}px: "
            f"[{qr_l:.1f}, {qr_r:.1f}] vs [{cb_l:.1f}, {cb_r:.1f}]"
        )
        assert cta_r <= fw + 1.0

        # Sin solapamientos horizontales entre sección izquierda, fila central y CTA derecho
        assert ch_r <= qr_l + 0.5, f"'Elegir...' solapa quickActionsRow a {win_w}px: {ch_r} > {qr_l}"
        assert qr_r <= cta_l + 0.5, f"quickActionsRow solapa CTA a {win_w}px: {qr_r} > {cta_l}"

        # Hijos internos de quickActionsRow tampoco se solapan entre sí
        in_l, in_r = _x_span(intact_badge)
        op_l, op_r = _x_span(open_btn)
        sh_l, sh_r = _x_span(show_btn)
        assert in_r <= op_l + 0.5
        assert op_r <= sh_l + 0.5

    window.close()








