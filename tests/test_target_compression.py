"""Pruebas unitarias y de interfaz para compresión a tamaño objetivo (MB) y acciones de rescate."""

from __future__ import annotations

import io
import os
from pathlib import Path
import random

from PIL import Image, ImageDraw
import pymupdf as fitz
from PySide6.QtQuick import QQuickItem
import pytest

from core.exceptions import PDFStudioError, TaskCancelledError
from core.history import OperationHistoryStore
from core.models import TargetQualityLabel
from core.pdf_engine import PDFEngine, compute_target_bytes
from ui.main_window import CoquetteQuickApp


def _make_noisy_jpeg(
    w: int, h: int, seed: int, quality: int = 96, block_div: int = 6
) -> bytes:
    """Genera un JPEG realista para pruebas de compresión (block_div mayor = más compresible)."""
    rng = random.Random(seed)
    small_w, small_h = max(32, w // block_div), max(32, h // block_div)
    raw = bytearray(small_w * small_h * 3)
    for idx in range(0, len(raw), 3):
        raw[idx] = rng.randint(40, 235)
        raw[idx + 1] = rng.randint(35, 220)
        raw[idx + 2] = rng.randint(55, 230)
    small_img = Image.frombytes("RGB", (small_w, small_h), bytes(raw))
    img = small_img.resize((w, h), Image.Resampling.BICUBIC)
    draw = ImageDraw.Draw(img)
    for k in range(24):
        x0 = (k * 67) % max(10, w - 70)
        y0 = (k * 53) % max(10, h - 70)
        draw.rectangle([x0, y0, x0 + 60, y0 + 50], outline=(90, 20, 45), width=3)
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=quality, subsampling=0)
    small_img.close()
    img.close()
    return buf.getvalue()


def _create_scanned_pdf(
    target_path: Path,
    num_pages: int = 8,
    w: int = 1400,
    h: int = 1800,
    block_div: int = 6,
) -> Path:
    doc = fitz.open()
    try:
        for i in range(num_pages):
            page = doc.new_page(width=595, height=842)
            page.insert_text((48, 42), f"Página escaneada {i + 1}", fontsize=12)
            page.insert_image(
                fitz.Rect(28, 60, 567, 810),
                stream=_make_noisy_jpeg(w, h, 200 + i, block_div=block_div),
            )
        doc.save(str(target_path), deflate=False)
    finally:
        doc.close()
    return target_path


def _find_visual_item(root: QQuickItem, object_name: str) -> QQuickItem | None:
    """Recorre el árbol visual QQuickItem (incluidos delegados de Repeater)."""
    if root.objectName() == object_name:
        return root
    for child in root.childItems():
        found = _find_visual_item(child, object_name)
        if found is not None:
            return found
    return None


def test_compute_target_bytes_strict_decimal_95_percent() -> None:
    """Verifica el cálculo estricto al 95% en base decimal (1 MB = 1,000,000 bytes) y validación."""
    assert compute_target_bytes(5.0) == 4_750_000
    assert compute_target_bytes(1.0) == 950_000
    assert compute_target_bytes(0.2) == 190_000
    assert compute_target_bytes(500.0) == 475_000_000

    for invalid in (0.19, 0.0, -2.0, 500.1, float("nan"), float("inf")):
        with pytest.raises(PDFStudioError):
            compute_target_bytes(invalid)


def test_already_within_limit_does_not_duplicate_or_spend_cpu(
    sample_pdf_5p: Path, tmp_path: Path
) -> None:
    """Si el original ya pesa <= 95% del límite, debe avisar sin generar copias."""
    out_dest = tmp_path / "should_not_exist.pdf"
    res = PDFEngine.compress_pdf_to_target_size(
        input_file=sample_pdf_5p,
        output_path=out_dest,
        target_mb=1.0,
    )
    assert res.met_target is True
    assert res.already_within_limit is True
    assert res.passes_executed == 0
    assert res.operation_result is None
    assert not out_dest.exists()
    assert "cumple el límite" in res.message


def test_weight_anatomy_text_heavy_single_photo_and_sample_selection(
    tmp_path: Path,
) -> None:
    """Verifica análisis Texto vs Imágenes (<15% aviso) y manejo seguro de 1 página gigante o >5 págs."""
    # 1. PDF de texto puro (<15% imágenes)
    text_pdf = tmp_path / "solo_texto.pdf"
    doc = fitz.open()
    for i in range(6):
        p = doc.new_page(width=595, height=842)
        for line in range(30):
            p.insert_text(
                (50, 50 + line * 24),
                f"Apuntes vectoriales página {i + 1} línea {line + 1}",
                fontsize=11,
            )
    doc.save(str(text_pdf), garbage=4, deflate=True)
    doc.close()

    anat_text = PDFEngine.analyze_pdf_weight_anatomy(text_pdf)
    assert anat_text.is_text_heavy is True
    assert anat_text.image_ratio < 0.15
    assert "15%" in anat_text.advisory_message

    # 2. PDF de 1 página con una fotografía gigante (>70% en imágenes)
    single_photo_pdf = tmp_path / "foto_1p.pdf"
    raw_rgb = os.urandom(1400 * 1100 * 3)
    img_big = Image.frombytes("RGB", (1400, 1100), raw_rgb)
    buf = io.BytesIO()
    img_big.save(buf, format="JPEG", quality=98, subsampling=0)
    img_big.close()
    doc = fitz.open()
    p = doc.new_page(width=595, height=842)
    p.insert_image(fitz.Rect(20, 20, 575, 822), stream=buf.getvalue())
    doc.save(str(single_photo_pdf), deflate=False)
    doc.close()

    anat_single = PDFEngine.analyze_pdf_weight_anatomy(single_photo_pdf)
    assert anat_single.page_count == 1
    assert anat_single.unique_image_count == 1
    assert anat_single.is_single_large_image is True
    assert PDFEngine._select_sample_pages(anat_single) == [0]

    # 3. Documento de >5 páginas: prioriza página 0 y las páginas con mayor peso en imágenes
    mixed_pdf = tmp_path / "mixto_8p.pdf"
    doc = fitz.open()
    for idx in range(8):
        p = doc.new_page(width=595, height=842)
        p.insert_text((40, 40), f"Hoja {idx + 1}", fontsize=12)
        if idx in (2, 6):
            p.insert_image(
                fitz.Rect(40, 80, 550, 780),
                stream=_make_noisy_jpeg(1200, 1400, 500 + idx),
            )
    doc.save(str(mixed_pdf), deflate=True)
    doc.close()

    anat_mixed = PDFEngine.analyze_pdf_weight_anatomy(mixed_pdf)
    sample_pages = PDFEngine._select_sample_pages(anat_mixed, max_pages=5)
    assert len(sample_pages) == 5
    assert 0 in sample_pages
    assert 2 in sample_pages and 6 in sample_pages


def test_target_binary_search_meets_limit_with_bounded_passes_and_cancel(
    tmp_path: Path,
) -> None:
    """Verifica búsqueda binaria en escalera (<= 3 pasadas), calidad, integridad y cancelación limpia."""
    scanned = _create_scanned_pdf(
        tmp_path / "escaneo_8p.pdf", num_pages=8, w=1500, h=2000, block_div=16
    )
    orig_size = scanned.stat().st_size
    assert orig_size > 1_200_000

    out_pdf = tmp_path / "escaneo_objetivo.pdf"
    res = PDFEngine.compress_pdf_to_target_size(
        input_file=scanned,
        output_path=out_pdf,
        target_mb=1.0,  # 950,000 bytes objetivo
    )
    assert res.met_target is True
    assert res.already_within_limit is False
    assert 1 <= res.passes_executed <= 3
    assert res.best_size_bytes <= compute_target_bytes(1.0)
    assert res.quality_label in {
        TargetQualityLabel.VERY_GOOD.value,
        TargetQualityLabel.GOOD.value,
        TargetQualityLabel.READABLE.value,
    }
    assert res.best_pdf_bytes is None  # RAM liberada tras escribir a disco
    assert res.operation_result is not None
    saved_file = res.operation_result.output_files[0]
    assert saved_file.exists()
    with fitz.open(saved_file) as out_doc:
        assert out_doc.page_count == 8

    # Verificar manejo de 1 página con foto grande (<= 5 páginas, sin dividir entre cero)
    photo_1p = tmp_path / "single_heavy.pdf"
    doc = fitz.open()
    p = doc.new_page(width=595, height=842)
    p.insert_image(fitz.Rect(20, 20, 575, 822), stream=_make_noisy_jpeg(1800, 2200, 99))
    doc.save(str(photo_1p), deflate=False)
    doc.close()
    res_1p = PDFEngine.compress_pdf_to_target_size(
        input_file=photo_1p,
        output_path=tmp_path / "single_heavy_out.pdf",
        target_mb=0.35,
    )
    assert res_1p.passes_executed <= 3
    assert res_1p.best_size_bytes < photo_1p.stat().st_size

    # Cancelación limpia entre pasadas sin temporales huérfanos
    cancel_dir = tmp_path / "cancel_target"
    cancel_dir.mkdir()
    calls = 0

    def _cancel_after_few() -> bool:
        nonlocal calls
        calls += 1
        return calls > 4

    with pytest.raises(TaskCancelledError):
        PDFEngine.compress_pdf_to_target_size(
            input_file=scanned,
            output_path=cancel_dir / "cancelled.pdf",
            target_mb=0.5,
            is_cancelled=_cancel_after_few,
        )
    assert list(cancel_dir.glob("*")) == []


def test_difficult_case_and_all_four_rescue_actions(tmp_path: Path) -> None:
    """Verifica detención en piso legible y las 4 acciones de rescate (incluido bordes de pág. en blanco)."""
    # Documento de 10 páginas pesadas para que 0.2 MB (190,000 bytes) sea inalcanzable al piso legible
    heavy_10p = _create_scanned_pdf(
        tmp_path / "pesado_10p.pdf", num_pages=10, w=1200, h=1550, block_div=3
    )
    res_fail = PDFEngine.compress_pdf_to_target_size(
        input_file=heavy_10p,
        output_path=tmp_path / "no_alcanza.pdf",
        target_mb=0.2,
    )
    assert res_fail.met_target is False
    assert res_fail.best_pdf_bytes is not None
    assert "Mejor intento:" in res_fail.message
    assert "faltan" in res_fail.message
    assert not (tmp_path / "no_alcanza.pdf").exists()

    # Rescate 1: Guardar el mejor intento de todas formas (sin sobrescribir el original)
    saved_anyway = PDFEngine.save_pdf_bytes_safely(
        pdf_bytes=res_fail.best_pdf_bytes,
        input_file=heavy_10p,
        output_path=heavy_10p,  # intenta sobrescribir: debe generar ruta segura
        original_size_bytes=res_fail.original_size_bytes,
        quality_label=res_fail.quality_label,
    )
    assert saved_anyway.output_files[0] != heavy_10p
    assert saved_anyway.output_files[0].exists()

    # Rescate 2: Escala de grises (Pillow)
    gray_res = PDFEngine.compress_pdf_grayscale_rescue(
        input_file=heavy_10p,
        output_path=tmp_path / "rescate_bn.pdf",
        target_mb=0.55,
    )
    assert gray_res.grayscale_applied is True
    assert gray_res.best_size_bytes < heavy_10p.stat().st_size

    # Rescate 3: Detectar y quitar páginas en blanco + casos borde (0 en blanco y todas en blanco)
    with_blanks = tmp_path / "con_blancos.pdf"
    doc = fitz.open()
    for i in range(5):
        p = doc.new_page(width=595, height=842)
        if i in (1, 3):
            # Página totalmente en blanco
            continue
        p.insert_text((48, 60), f"Contenido útil {i + 1}", fontsize=14)
        p.insert_image(fitz.Rect(48, 90, 540, 760), stream=_make_noisy_jpeg(1100, 1400, 700 + i))
    doc.save(str(with_blanks), deflate=False)
    doc.close()

    detected = PDFEngine.detect_blank_pages(with_blanks)
    assert detected == [1, 3]

    no_blank_res = PDFEngine.remove_blank_pages_and_compress(
        input_file=with_blanks,
        output_path=tmp_path / "sin_blancos.pdf",
        target_mb=0.5,
    )
    assert no_blank_res.removed_blank_pages == 2
    assert no_blank_res.operation_result is not None
    with fitz.open(no_blank_res.operation_result.output_files[0]) as cleaned_doc:
        assert cleaned_doc.page_count == 3

    # Borde: 0 páginas en blanco
    with pytest.raises(PDFStudioError, match="No se detectaron páginas en blanco"):
        PDFEngine.remove_blank_pages_and_compress(
            input_file=heavy_10p,
            output_path=tmp_path / "sin_blancos_fail.pdf",
            target_mb=0.5,
        )

    # Borde: todas las páginas en blanco -> no genera PDF de 0 páginas
    all_blanks = tmp_path / "todas_blancas.pdf"
    doc = fitz.open()
    for _ in range(3):
        doc.new_page(width=595, height=842)
    doc.save(str(all_blanks))
    doc.close()
    with pytest.raises(PDFStudioError, match="Todas las páginas"):
        PDFEngine.remove_blank_pages_and_compress(
            input_file=all_blanks,
            output_path=tmp_path / "todas_blancas_out.pdf",
            target_mb=0.5,
        )
    assert not (tmp_path / "todas_blancas_out.pdf").exists()

    # Rescate 4: Dividir en partes consecutivas bajo el límite
    split_res = PDFEngine.split_pdf_to_target_size(
        input_file=heavy_10p,
        output_path=tmp_path / "dividido.pdf",
        target_mb=0.25,  # 237,500 bytes por parte
        source_pdf_bytes=res_fail.best_pdf_bytes,
    )
    assert len(split_res.output_files) >= 2
    total_pages_split = 0
    limit_b = compute_target_bytes(0.25)
    for idx, part_path in enumerate(split_res.output_files, start=1):
        assert part_path.exists()
        assert f"_parte{idx}" in part_path.name
        assert part_path.stat().st_size <= limit_b
        with fitz.open(part_path) as pdoc:
            total_pages_split += pdoc.page_count
    assert total_pages_split == 10


def test_ui_target_size_mode_preview_and_difficult_rescue_popup(
    tmp_path: Path, qtbot
) -> None:
    """Verifica en QtQuick/QML el panel Tamaño máximo (MB), comparativa + vista previa y popup de rescate."""
    scanned = _create_scanned_pdf(
        tmp_path / "ui_escaneo_8p.pdf", num_pages=8, w=1500, h=2000, block_div=16
    )
    out_dir = tmp_path / "ui_out"
    out_dir.mkdir()

    store = OperationHistoryStore(storage_path=tmp_path / "ui_target_hist.json")
    app_wrapper = CoquetteQuickApp(history_store=store)
    window = app_wrapper.load_main_qml()
    bridge = app_wrapper.studio_bridge
    qtbot.waitExposed(window)

    bridge.setOutputDirectory(str(out_dir))
    bridge.addSingleFilePath(str(scanned))
    bridge.selectTool("compress")
    qtbot.waitUntil(lambda: not bridge.isEstimatingCompression, timeout=8000)
    qtbot.wait(50)

    # Confirmar compatibilidad: siguen existiendo los 3 botones clásicos + el nuevo botón objetivo
    target_mode_btn = window.findChild(QQuickItem, "compressTargetSizeModeBtn")
    assert target_mode_btn is not None and target_mode_btn.isVisible() is True

    bridge.setTargetSizeMode(True)
    qtbot.wait(50)

    target_input = window.findChild(QQuickItem, "targetSizeInput")
    preset_5 = _find_visual_item(window.contentItem(), "targetPresetBtn_5")
    assert target_input is not None and target_input.isVisible() is True
    assert preset_5 is not None and preset_5.isVisible() is True

    # Validación de rango numérico
    bridge.setTargetSizeText("0.05")
    assert bridge.isTargetSizeValid is False
    bridge.setTargetSizeMb(1.0)
    assert bridge.isTargetSizeValid is True
    assert bridge.targetSizeMb == 1.0

    # Ejecutar compresión objetivo alcanzable (1.0 MB)
    with qtbot.waitSignal(bridge.operationCompleted, timeout=20000):
        bridge.executeActiveOperation()
    qtbot.wait(80)

    assert "→" in bridge.lastCompressionComparison
    assert bridge.lastCompressionQualityLabel in {"Muy buena", "Buena", "Legible"}
    assert bridge.lastCompressionPreviewUrl.startswith("image://pdfpage/0?path=")

    comp_popup_text = window.findChild(QQuickItem, "completionComparisonText")
    comp_quality = window.findChild(QQuickItem, "completionQualityBadge")
    open_viewer_btn = window.findChild(QQuickItem, "modalOpenInViewerBtn")
    assert comp_popup_text is not None and comp_quality is not None and open_viewer_btn is not None

    # Probar botón "Ver en Visor y Firma"
    bridge.openResultInViewer()
    qtbot.wait(50)
    assert bridge.activeTool == "sign"
    assert bridge.workspaceMode == "viewer"

    # Ahora probar caso difícil (0.2 MB en documento pesado de 10 págs) -> abre difficultCompressionPopup
    heavy_10p = _create_scanned_pdf(
        tmp_path / "ui_heavy_10p.pdf", num_pages=10, w=1200, h=1550, block_div=3
    )
    bridge.clearFiles()
    bridge.addSingleFilePath(str(heavy_10p))
    bridge.selectTool("compress")
    qtbot.waitUntil(lambda: not bridge.isEstimatingCompression, timeout=8000)
    bridge.setTargetSizeMb(0.2)

    with qtbot.waitSignal(bridge.difficultCompressionOccurred, timeout=20000):
        bridge.executeActiveOperation()
    qtbot.wait(80)

    assert bridge.hasDifficultTargetResult is True
    assert "Mejor intento:" in bridge.difficultTargetSummary

    # Disparar acción de rescate "Dividir en partes bajo el límite"
    with qtbot.waitSignal(bridge.operationCompleted, timeout=15000) as rescue_blocker:
        bridge.rescueSplitIntoParts()
    qtbot.wait(50)
    assert bridge.hasDifficultTargetResult is False
    assert "_parte1" in Path(rescue_blocker.args[1]).name

    window.close()
