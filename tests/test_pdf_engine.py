"""Pruebas integrales del motor de procesamiento PDF (core/pdf_engine.py y core/workers.py)."""

from __future__ import annotations

from pathlib import Path
import pymupdf as fitz
import pytest

from core.exceptions import (
    InvalidPasswordError,
    PDFCorruptedError,
    PDFEncryptedError,
    TaskCancelledError,
)
from core.history import OperationHistoryStore
from core.models import (
    CompressionLevel,
    ImageFormat,
    PageItemInstruction,
    SignatureOverlay,
    WatermarkConfig,
    WatermarkPosition,
)
from core.pdf_engine import PDFEngine, ensure_safe_output_path, inspect_pdf_file
from core.workers import PDFOperationWorker, ThumbnailLRUCache


def test_merge_pdfs_and_prevent_overwrite(
    sample_pdf_5p: Path, sample_pdf_3p: Path, tmp_path: Path
) -> None:
    """Verifica la unión de múltiples PDFs y que nunca sobrescriba el archivo original."""
    # Intentar pasar el mismo path de entrada como salida debe generar sufijo seguro
    res = PDFEngine.merge_pdfs(
        input_files=[sample_pdf_5p, sample_pdf_3p],
        output_path=sample_pdf_5p,
    )
    assert len(res.output_files) == 1
    out_file = res.output_files[0]
    assert out_file != sample_pdf_5p
    assert out_file.exists()

    with fitz.open(out_file) as merged_doc:
        assert merged_doc.page_count == 8

    # El archivo original de 5 páginas sigue intacto
    with fitz.open(sample_pdf_5p) as orig_doc:
        assert orig_doc.page_count == 5


def test_split_pdf_combined_and_separate(sample_pdf_5p: Path, tmp_path: Path) -> None:
    """Verifica extracción por rango ('1-2, 5') tanto en un solo PDF como en archivos separados."""
    out_single = tmp_path / "split_single.pdf"
    res_single = PDFEngine.split_pdf_by_range(
        input_file=sample_pdf_5p,
        output_path=out_single,
        range_expr="1-2, 5",
        split_into_separate_files=False,
    )
    assert len(res_single.output_files) == 1
    with fitz.open(res_single.output_files[0]) as doc:
        assert doc.page_count == 3

    out_multi = tmp_path / "split_part.pdf"
    res_multi = PDFEngine.split_pdf_by_range(
        input_file=sample_pdf_5p,
        output_path=out_multi,
        range_expr="1, 3, 5",
        split_into_separate_files=True,
    )
    assert len(res_multi.output_files) == 3
    for part_file in res_multi.output_files:
        assert part_file.exists()


def test_organize_rotate_duplicate_delete_pages(
    sample_pdf_5p: Path, tmp_path: Path
) -> None:
    """Verifica reordenamiento, rotación de 90/180 grados, duplicación y eliminación de páginas."""
    instructions = [
        PageItemInstruction(source_page_index=4, rotation_degrees=90),
        PageItemInstruction(source_page_index=0, rotation_degrees=180),
        PageItemInstruction(source_page_index=0, rotation_degrees=0),  # Duplicada
    ]
    out_path = tmp_path / "organized.pdf"
    res = PDFEngine.organize_pdf(
        input_file=sample_pdf_5p,
        output_path=out_path,
        instructions=instructions,
    )
    assert res.output_files[0].exists()
    with fitz.open(res.output_files[0]) as doc:
        assert doc.page_count == 3
        assert doc[0].rotation == 90
        assert doc[1].rotation == 180
        assert doc[2].rotation == 0


def test_compress_pdf_levels(sample_pdf_5p: Path, tmp_path: Path) -> None:
    """Verifica los tres niveles de compresión y la estimación de ahorro."""
    est_bytes, est_pct = PDFEngine.estimate_compression_savings(
        100_000, CompressionLevel.RECOMMENDED
    )
    assert est_bytes < 100_000
    assert est_pct > 0

    for level in (
        CompressionLevel.EXTREME,
        CompressionLevel.RECOMMENDED,
        CompressionLevel.LOW_LOSS,
    ):
        out = tmp_path / f"compressed_{level}.pdf"
        res = PDFEngine.compress_pdf(sample_pdf_5p, out, level=level)
        assert res.output_files[0].exists()
        assert res.final_size_bytes > 0


def test_protect_and_unlock_pdf(sample_pdf_5p: Path, tmp_path: Path) -> None:
    """Verifica el cifrado AES-256 con contraseña y el posterior desbloqueo."""
    protected_path = tmp_path / "protected.pdf"
    secret = "RosaCoquette#2026"
    res_protect = PDFEngine.protect_pdf(
        input_file=sample_pdf_5p,
        output_path=protected_path,
        new_password=secret,
    )
    locked_file = res_protect.output_files[0]
    info = inspect_pdf_file(locked_file)
    assert info.is_encrypted is True

    # Intentar usar el archivo bloqueado en otra herramienta sin contraseña debe lanzar PDFEncryptedError
    with pytest.raises(PDFEncryptedError):
        PDFEngine.split_pdf_by_range(locked_file, tmp_path / "fail.pdf", "1-2")

    # Contraseña incorrecta debe lanzar InvalidPasswordError
    with pytest.raises(InvalidPasswordError):
        PDFEngine.unlock_pdf(locked_file, tmp_path / "fail_unlock.pdf", password="wrong")

    # Desbloqueo con contraseña correcta
    unlocked_path = tmp_path / "unlocked.pdf"
    res_unlock = PDFEngine.unlock_pdf(
        input_file=locked_file,
        output_path=unlocked_path,
        password=secret,
    )
    unlocked_file = res_unlock.output_files[0]
    info_after = inspect_pdf_file(unlocked_file)
    assert info_after.is_encrypted is False
    assert info_after.page_count == 5


def test_pdf_to_images_and_images_to_pdf(
    sample_pdf_3p: Path, sample_images: list[Path], tmp_path: Path
) -> None:
    """Verifica la conversión de PDF a imágenes (PNG/JPG) e imágenes de vuelta a PDF."""
    img_out_dir = tmp_path / "exported_images"
    res_export = PDFEngine.pdf_to_images(
        input_file=sample_pdf_3p,
        output_dir=img_out_dir,
        image_format=ImageFormat.PNG,
        dpi=96,
    )
    assert len(res_export.output_files) == 3
    for img_file in res_export.output_files:
        assert img_file.exists() and img_file.stat().st_size > 0

    pdf_from_imgs = tmp_path / "from_images.pdf"
    res_import = PDFEngine.images_to_pdf(
        image_files=sample_images,
        output_path=pdf_from_imgs,
    )
    assert res_import.output_files[0].exists()
    with fitz.open(res_import.output_files[0]) as doc:
        assert doc.page_count == len(sample_images)


def test_apply_watermark_and_signature_stamp(
    sample_pdf_3p: Path, sample_images: list[Path], tmp_path: Path
) -> None:
    """Verifica el estampado de marca de agua 3x3 y la superposición de firma/sello/PNG."""
    wm_out = tmp_path / "watermarked.pdf"
    wm_cfg = WatermarkConfig(
        text="CONFIDENCIAL",
        opacity=0.4,
        angle=45.0,
        position=WatermarkPosition.CENTER,
    )
    res_wm = PDFEngine.apply_watermark(sample_pdf_3p, wm_out, wm_cfg)
    assert res_wm.output_files[0].exists()

    sign_out = tmp_path / "signed.pdf"
    overlay = SignatureOverlay(
        page_index=0,
        stamp_label="APROBADO",
        image_path=sample_images[0],
        freehand_strokes=[[(0.15, 0.80), (0.25, 0.82), (0.35, 0.79)]],
    )
    res_sign = PDFEngine.apply_signature_or_stamp(sample_pdf_3p, sign_out, overlay)
    assert res_sign.output_files[0].exists()


def test_signature_overlay_transparency_black_stroke_and_upright_orientation(
    tmp_path: Path,
) -> None:
    """Verifica canal alfa transparente (alpha=0), trazo negro (#000000), opción sin sello y orientación no invertida."""
    from PySide6.QtGui import QImage

    # 1. Solo firma sin sello: fondo 100% transparente (alpha=0) y trazo negro (#000000)
    overlay_no_stamp = SignatureOverlay(
        page_index=0,
        stamp_label=None,
        image_path=None,
        freehand_strokes=[[(0.20, 0.20), (0.50, 0.20)]],
    )
    png_bytes = PDFEngine.render_signature_overlay_png(
        overlay=overlay_no_stamp,
        page_width_pt=200.0,
        page_height_pt=300.0,
        scale=1.0,
    )
    qimg = QImage.fromData(png_bytes, "PNG")
    assert not qimg.isNull()
    # Esquina y zona de sello deben ser 100% transparentes (alpha == 0)
    assert qimg.pixelColor(10, 10).alpha() == 0
    assert qimg.pixelColor(150, 250).alpha() == 0

    # Píxel sobre el trazo en (x=0.35*200=70, y=0.20*300=60) debe ser negro puro (#000000)
    stroke_px = qimg.pixelColor(70, 60)
    assert stroke_px.alpha() > 200
    assert stroke_px.red() == 0
    assert stroke_px.green() == 0
    assert stroke_px.blue() == 0

    # 2. Verificar en PDF con CTM invertido no envuelto y con rotación (0, 90, 180, 270)
    for rotation in (0, 90, 180, 270):
        raw_pdf = tmp_path / f"unwrapped_rot_{rotation}.pdf"
        doc = fitz.open()
        page = doc.new_page(width=200, height=300)
        page.insert_text((30, 150), "Base")
        xref = page.get_contents()[0]
        # Simular stream CTM con eje Y invertido sin q/Q (causa clásica de inversión vertical)
        doc.update_stream(xref, b"1 0 0 -1 0 300 cm\n")
        page.set_rotation(rotation)
        doc.save(str(raw_pdf))
        doc.close()

        signed_pdf = tmp_path / f"signed_rot_{rotation}.pdf"
        overlay_top = SignatureOverlay(
            page_index=0,
            stamp_label="APROBADO",
            freehand_strokes=[[(0.15, 0.15), (0.45, 0.15)]],
            normalized_rect=(0.55, 0.75, 0.92, 0.90),
        )
        PDFEngine.apply_signature_or_stamp(raw_pdf, signed_pdf, overlay_top)

        with fitz.open(signed_pdf) as out_doc:
            out_page = out_doc[0]
            pix = out_page.get_pixmap(dpi=144, alpha=False)
            rendered = QImage.fromData(bytes(pix.tobytes("png")), "PNG")
            rx = int(rendered.width() * 0.30)
            ry_top = int(rendered.height() * 0.15)
            ry_bottom_mirror = int(rendered.height() * 0.85)

            # El trazo está arriba (y=0.15), en color negro, y NO espejado abajo (y=0.85)
            top_color = rendered.pixelColor(rx, ry_top)
            mirror_color = rendered.pixelColor(rx, ry_bottom_mirror)
            assert top_color.red() < 50 and top_color.green() < 50 and top_color.blue() < 50
            assert mirror_color.red() == 255 and mirror_color.green() == 255 and mirror_color.blue() == 255

            # El fondo dentro del recuadro del sello pero cerca de su esquina sigue siendo blanco (sin caja rosada)
            stamp_corner_bg = rendered.pixelColor(
                int(rendered.width() * 0.56), int(rendered.height() * 0.76)
            )
            assert stamp_corner_bg.red() == 255 and stamp_corner_bg.green() == 255 and stamp_corner_bg.blue() == 255


def test_edge_cases_corrupted_zero_bytes_and_special_paths(
    sample_pdf_3p: Path, tmp_path: Path
) -> None:
    """Verifica detección de PDFs de 0 bytes, extensión falsa y rutas con acentos/espacios."""
    zero_file = tmp_path / "empty.pdf"
    zero_file.write_bytes(b"")
    with pytest.raises(PDFCorruptedError):
        inspect_pdf_file(zero_file)

    fake_pdf = tmp_path / "fake.pdf"
    fake_pdf.write_text("Esto no es un archivo PDF real", encoding="utf-8")
    with pytest.raises(PDFCorruptedError):
        inspect_pdf_file(fake_pdf)

    # Ruta con acentos, eñes y espacios largos
    special_dir = tmp_path / "Carpeta Diseño Papelería & Coquette — Año 2026"
    special_dir.mkdir(parents=True, exist_ok=True)
    special_out = special_dir / "Documento_unión_español_áéíóú.pdf"
    res = PDFEngine.merge_pdfs([sample_pdf_3p], special_out)
    assert res.output_files[0].exists()


def test_cancellation_leaves_no_orphan_temp_files(
    sample_pdf_5p: Path, tmp_path: Path
) -> None:
    """Verifica que cancelar una operación a mitad del proceso no deje temporales huérfanos."""
    out_dir = tmp_path / "cancel_check"
    out_dir.mkdir()
    target = out_dir / "result.pdf"

    call_count = 0

    def cancel_on_second_step() -> bool:
        nonlocal call_count
        call_count += 1
        return call_count >= 2

    with pytest.raises(TaskCancelledError):
        PDFEngine.merge_pdfs(
            [sample_pdf_5p, sample_pdf_5p],
            output_path=target,
            is_cancelled=cancel_on_second_step,
        )

    assert not target.exists()
    leftovers = list(out_dir.glob("*"))
    assert leftovers == []


def test_history_store_limits_to_10_entries(
    sample_pdf_3p: Path, tmp_path: Path
) -> None:
    """Verifica el historial persistente local en JSON acotado a las últimas 10 operaciones."""
    history_file = tmp_path / "history.json"
    store = OperationHistoryStore(storage_path=history_file)
    res = PDFEngine.merge_pdfs([sample_pdf_3p], tmp_path / "hist_out.pdf")

    for i in range(14):
        res.message = f"Operación #{i + 1}"
        store.record_operation(res)

    loaded = store.load_entries()
    assert len(loaded) == 10
    assert loaded[0].message == "Operación #14"
    assert loaded[-1].message == "Operación #5"


def test_worker_and_lru_cache_for_200_plus_pages(tmp_path: Path, qtbot) -> None:
    """Verifica que un PDF de 210 páginas renderice miniaturas con caché LRU y QRunnable sin bloquear."""
    large_pdf = tmp_path / "large_210p.pdf"
    doc = fitz.open()
    for i in range(210):
        p = doc.new_page(width=400, height=550)
        p.insert_text(fitz.Point(40, 80), f"Pág {i + 1}")
    doc.save(str(large_pdf))
    doc.close()

    cache = ThumbnailLRUCache(max_entries=25)
    for page_idx in (0, 50, 120, 209):
        png = PDFEngine.render_page_png_bytes(large_pdf, page_idx, dpi=72)
        assert png.startswith(b"\x89PNG")
        cache.put((str(large_pdf), page_idx, 72), png)

    assert len(cache) == 4

    # Verificar ejecución en QRunnable con señales de progreso
    worker = PDFOperationWorker(
        PDFEngine.split_pdf_by_range,
        large_pdf,
        tmp_path / "extracted_from_210.pdf",
        "1-3, 200, 210",
    )
    progress_events: list[int] = []
    worker.signals.progress.connect(lambda pct, _msg: progress_events.append(pct))

    with qtbot.waitSignal(worker.signals.finished, timeout=10000) as blocker:
        worker.run()

    result = blocker.args[0]
    assert result.output_files[0].exists()
    assert len(progress_events) > 0

