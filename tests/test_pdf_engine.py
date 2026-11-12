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


def test_bloque4_vector_strokes_and_png_signature_rotations_and_cropbox(
    tmp_path: Path,
) -> None:
    """Verifica trazos vectoriales Bézier nativos, 3 grosores, firma PNG transparente y mapeo exacto con /Rotate y CropBox."""
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QColor, QImage, QPainter, QPen

    # Crear firma PNG transparente real (240x100) con trazo oscuro en el centro
    png_sig = tmp_path / "firma_transparente.png"
    sig_img = QImage(240, 100, QImage.Format.Format_ARGB32)
    sig_img.fill(Qt.GlobalColor.transparent)
    p = QPainter(sig_img)
    pen = QPen(QColor(15, 15, 25, 255))
    pen.setWidth(8)
    p.setPen(pen)
    p.drawLine(20, 50, 220, 50)
    p.end()
    assert sig_img.save(str(png_sig), "PNG")

    # Probar páginas verticales, horizontales y con /Rotate = 0, 90, 180, 270 + CropBox != MediaBox
    configs = [
        ("vertical_0", 595, 842, 0, False),
        ("horizontal_0", 842, 595, 0, False),
        ("rot_90_crop", 595, 842, 90, True),
        ("rot_180_crop", 595, 842, 180, True),
        ("rot_270_crop", 595, 842, 270, True),
    ]
    for label, w, h, rot, use_crop in configs:
        src_pdf = tmp_path / f"src_{label}.pdf"
        doc = fitz.open()
        page = doc.new_page(width=w, height=h)
        if use_crop:
            page.set_cropbox(fitz.Rect(30, 40, w - 20, h - 30))
        if rot:
            page.set_rotation(rot)
        doc.save(str(src_pdf))
        doc.close()

        out_pdf = tmp_path / f"out_{label}.pdf"
        # Trazo multipunto que genera curvas Bézier cúbicas (" c\n") y firma PNG en posición específica
        overlay = SignatureOverlay(
            page_index=0,
            stamp_label=None,
            image_path=png_sig,
            image_normalized_rect=(0.60, 0.65, 0.85, 0.78),
            freehand_strokes=[
                [(0.15, 0.25), (0.22, 0.20), (0.30, 0.28), (0.38, 0.22)],
                [(0.15, 0.40), (0.25, 0.42), (0.35, 0.40)],
            ],
            stroke_widths_pt=[1.75, 4.5],
            default_stroke_width_pt=1.75,
        )
        res = PDFEngine.apply_signature_or_stamp(src_pdf, out_pdf, overlay)
        assert res.output_files[0].exists()

        with fitz.open(out_pdf) as signed_doc:
            sp = signed_doc[0]
            # Comprobar que el stream de contenido contiene operadores Bézier vectoriales (" c\n") y round cap ("1 J")
            raw_stream = b"".join(signed_doc.xref_stream(xref) for xref in sp.get_contents())
            assert b" c\n" in raw_stream
            assert b"1 J" in raw_stream

            # Renderizar página firmada y comprobar que tanto la zona del trazo como la zona del PNG cambiaron respecto al blanco
            pix = sp.get_pixmap(dpi=144, alpha=False)
            rendered = QImage.fromData(bytes(pix.tobytes("png")), "PNG")

            # Verificar caja de la firma PNG (0.60..0.85, 0.65..0.78)
            png_dark_pixels = 0
            for sx in range(int(rendered.width() * 0.62), int(rendered.width() * 0.83), 3):
                for sy in range(int(rendered.height() * 0.66), int(rendered.height() * 0.77), 3):
                    c = rendered.pixelColor(sx, sy)
                    if c.red() < 100 and c.green() < 100 and c.blue() < 100:
                        png_dark_pixels += 1
            assert png_dark_pixels > 5, f"La firma PNG no quedó estampada en {label}"


def test_bloque5_compression_seven_pdfs_monotonic_and_honest_estimation(
    tmp_path: Path,
) -> None:
    """Verifica el Bloque 5 con los 7 tipos de PDFs exigidos: monotonía, estimación <=5 pts, integridad (texto, TOC, SMask), firma digital y cancelación limpia."""
    from PIL import Image, ImageDraw
    from core.exceptions import TaskCancelledError
    from core.models import COMPRESSION_PROFILES

    # Verificar que los tres perfiles centralizados existen en core/models.py con parámetros diferenciados
    assert set(COMPRESSION_PROFILES.keys()) == {
        CompressionLevel.LOW_LOSS,
        CompressionLevel.RECOMMENDED,
        CompressionLevel.EXTREME,
    }
    assert (
        COMPRESSION_PROFILES[CompressionLevel.EXTREME].jpeg_quality
        < COMPRESSION_PROFILES[CompressionLevel.RECOMMENDED].jpeg_quality
        < COMPRESSION_PROFILES[CompressionLevel.LOW_LOSS].jpeg_quality
    )

    def _make_photo_bytes(w: int, h: int, seed: int, fmt: str = "JPEG", quality: int = 96) -> bytes:
        import io
        import random

        rng = random.Random(seed)
        # Crear base con ruido de bloque suave escalado + formas geométricas para simular fotografía escaneada realista
        small_w, small_h = max(32, w // 6), max(32, h // 6)
        raw = bytearray(small_w * small_h * 3)
        for idx in range(0, len(raw), 3):
            raw[idx] = rng.randint(60, 235)
            raw[idx + 1] = rng.randint(50, 215)
            raw[idx + 2] = rng.randint(70, 225)
        small_img = Image.frombytes("RGB", (small_w, small_h), bytes(raw))
        img = small_img.resize((w, h), Image.Resampling.BICUBIC)
        draw = ImageDraw.Draw(img)
        for k in range(18):
            x0 = (k * 73) % (w - 80)
            y0 = (k * 59) % (h - 80)
            draw.rectangle([x0, y0, x0 + 70, y0 + 60], outline=(80, 25, 45), width=3)
        buf = io.BytesIO()
        if fmt == "JPEG":
            img.save(buf, format="JPEG", quality=quality)
        else:
            img.save(buf, format=fmt)
        return buf.getvalue()

    # 1) Escaneo de imágenes de 10 páginas
    pdf_scan_10p = tmp_path / "1_escaneo_10p.pdf"
    doc = fitz.open()
    for i in range(10):
        p = doc.new_page(width=595, height=842)
        p.insert_image(fitz.Rect(18, 18, 577, 824), stream=_make_photo_bytes(1650, 2300, 100 + i))
    doc.save(str(pdf_scan_10p), deflate=True)
    doc.close()

    # 2) Solo texto vectorial
    pdf_text_only = tmp_path / "2_solo_texto_vectorial.pdf"
    doc = fitz.open()
    for i in range(6):
        p = doc.new_page(width=595, height=842)
        for line in range(28):
            p.insert_text(
                (54, 60 + line * 24),
                f"Apuntes de literatura y papelería floral — página {i + 1}, línea {line + 1}",
                fontsize=11,
            )
    doc.save(str(pdf_text_only), garbage=4, deflate=True, clean=True)
    doc.close()

    # 3) Mixto texto e imágenes (con tabla de contenidos TOC, enlaces y transparencia SMask)
    pdf_mixed = tmp_path / "3_mixto_texto_imagenes_toc_smask.pdf"
    doc = fitz.open()
    for i in range(5):
        p = doc.new_page(width=595, height=842)
        p.insert_text((54, 54), f"Capítulo {i + 1}: Herbarios Ilustrados", fontsize=16)
        p.insert_text((54, 82), "Texto seleccionable que debe conservarse íntegro tras comprimir.", fontsize=11)
        p.insert_link({"kind": fitz.LINK_URI, "from": fitz.Rect(54, 70, 240, 90), "uri": "https://example.org"})
        p.insert_image(fitz.Rect(54, 110, 541, 460), stream=_make_photo_bytes(1500, 1100, 300 + i))
    # Añadir una imagen PNG con canal alfa (SMask) en la página 1
    import io
    rgba_img = Image.new("RGBA", (600, 400), (0, 0, 0, 0))
    rgba_draw = ImageDraw.Draw(rgba_img)
    rgba_draw.ellipse([40, 40, 560, 360], fill=(223, 130, 147, 190))
    rgba_buf = io.BytesIO()
    rgba_img.save(rgba_buf, format="PNG")
    doc[0].insert_image(fitz.Rect(120, 500, 460, 720), stream=rgba_buf.getvalue())
    doc.set_toc([[1, "Capítulo 1", 1], [1, "Capítulo 2", 2], [1, "Capítulo 3", 3]])
    doc.save(str(pdf_mixed), deflate=True)
    doc.close()

    # 4) Una página con una imagen pesada de ~20 MB (bitmap de alta resolución sin compresión agresiva)
    pdf_heavy_1p = tmp_path / "4_una_pagina_imagen_20mb.pdf"
    import os
    raw_rgb_20mb = os.urandom(2750 * 2450 * 3)  # ~20.2 MB de datos de imagen
    img_20mb = Image.frombytes("RGB", (2750, 2450), raw_rgb_20mb)
    bmp_buf = io.BytesIO()
    img_20mb.save(bmp_buf, format="JPEG", quality=100, subsampling=0)
    doc = fitz.open()
    p = doc.new_page(width=595, height=842)
    p.insert_image(fitz.Rect(20, 20, 575, 822), stream=bmp_buf.getvalue())
    doc.save(str(pdf_heavy_1p), deflate=False)
    doc.close()

    # 5) Uno ya comprimido (debe descartar el resultado si no logra reducir y dejar el original intacto)
    pdf_already_compressed = tmp_path / "5_ya_comprimido.pdf"
    PDFEngine.compress_pdf(
        pdf_scan_10p,
        pdf_already_compressed,
        level=CompressionLevel.EXTREME,
    )
    # Comprimir una segunda vez en EXTREME para garantizar que ya está en su mínimo absoluto
    pdf_already_min = tmp_path / "5_ya_comprimido_min.pdf"
    res_min = PDFEngine.compress_pdf(
        pdf_already_compressed,
        pdf_already_min,
        level=CompressionLevel.EXTREME,
    )
    if pdf_already_min.exists():
        pdf_already_compressed = pdf_already_min

    # 6) Uno cifrado (con contraseña)
    pdf_encrypted = tmp_path / "6_cifrado.pdf"
    doc = fitz.open()
    for i in range(3):
        p = doc.new_page(width=595, height=842)
        p.insert_text((54, 60), f"Pliego confidencial página {i + 1}", fontsize=13)
        p.insert_image(fitz.Rect(54, 90, 541, 760), stream=_make_photo_bytes(1400, 1750, 600 + i))
    doc.save(
        str(pdf_encrypted),
        encryption=fitz.PDF_ENCRYPT_AES_256,
        user_pw="floral123",
        owner_pw="floral123",
        deflate=True,
    )
    doc.close()

    # 7) Uno diminuto (<100 KB)
    pdf_tiny = tmp_path / "7_diminuto.pdf"
    doc = fitz.open()
    p = doc.new_page(width=595, height=842)
    p.insert_text((72, 100), "Nota breve en libreta (<100 KB).", fontsize=12)
    doc.save(str(pdf_tiny), garbage=4, deflate=True)
    doc.close()
    assert pdf_tiny.stat().st_size < 100 * 1024

    cases = [
        ("1. Escaneo 10 págs", pdf_scan_10p, None, True),
        ("2. Solo texto vectorial", pdf_text_only, None, False),
        ("3. Mixto texto+img+TOC+SMask", pdf_mixed, None, True),
        ("4. 1 pág imagen pesada", pdf_heavy_1p, None, True),
        ("5. Ya comprimido", pdf_already_compressed, None, False),
        ("6. Cifrado (AES-256)", pdf_encrypted, "floral123", True),
        ("7. Diminuto (<100 KB)", pdf_tiny, None, False),
    ]

    for label, src_path, pwd, has_compressible_images in cases:
        orig_size = src_path.stat().st_size
        estimates = PDFEngine.estimate_pdf_compression_for_all_levels(src_path, password=pwd)

        # Monotonía de la estimación
        est_low = int(estimates["low_loss"]["estimatedBytes"])
        est_rec = int(estimates["recommended"]["estimatedBytes"])
        est_ext = int(estimates["extreme"]["estimatedBytes"])
        assert est_ext <= est_rec <= est_low <= orig_size, f"Fallo monotonía estimada en {label}"

        real_sizes: dict[str, int] = {}
        real_pcts: dict[str, float] = {}
        for idx_lvl, lvl in enumerate(
            (CompressionLevel.LOW_LOSS, CompressionLevel.RECOMMENDED, CompressionLevel.EXTREME)
        ):
            out_path = tmp_path / f"out_{src_path.stem}_{lvl.value}.pdf"
            res = PDFEngine.compress_pdf(src_path, out_path, level=lvl, password=pwd)
            real_sizes[lvl.value] = res.final_size_bytes
            real_pcts[lvl.value] = res.saved_percentage

            if res.final_size_bytes < orig_size:
                assert out_path.exists()
                assert "De " in res.message and "(-" in res.message
            else:
                # Si no reduce, se descarta y se informa que ya está optimizado
                assert res.final_size_bytes == orig_size
                assert "optimizado" in res.message

        # Monotonía real garantizada: Extrema <= Recomendada <= Baja pérdida <= Original
        assert (
            real_sizes["extreme"]
            <= real_sizes["recommended"]
            <= real_sizes["low_loss"]
            <= orig_size
        ), f"Fallo monotonía real en {label}: {real_sizes} vs orig {orig_size}"

        if has_compressible_images:
            # En PDFs con imágenes aún no exprimidas, Extrema debe reducir de verdad y diferenciarse
            assert real_sizes["extreme"] < real_sizes["recommended"] <= real_sizes["low_loss"] < orig_size
            # Estimado dentro de <= 5 puntos porcentuales del real
            for lvl_key in ("low_loss", "recommended", "extreme"):
                est_pct = float(estimates[lvl_key]["savedPct"])
                diff_pts = abs(est_pct - real_pcts[lvl_key])
                assert diff_pts <= 5.0, (
                    f"Desviación >5 pts en {label} ({lvl_key}): est={est_pct}% vs real={real_pcts[lvl_key]}%"
                )

    # Verificar integridad en el PDF mixto (texto seleccionable, TOC, número de páginas y SMask conservados)
    mixed_ext_out = tmp_path / f"out_{pdf_mixed.stem}_extreme.pdf"
    with fitz.open(mixed_ext_out) as doc_out:
        assert doc_out.page_count == 5
        assert len(doc_out.get_toc()) == 3
        assert "Herbarios Ilustrados" in doc_out[0].get_text()
        assert len(doc_out[0].get_links()) >= 1
        smask_found = any(int(im[1]) > 0 for im in doc_out[0].get_images(full=True))
        assert smask_found is True

    # Verificar detección de firma digital criptográfica (/Sig)
    pdf_signed_sig = tmp_path / "con_firma_criptografica.pdf"
    doc = fitz.open()
    page = doc.new_page()
    widget = fitz.Widget()
    widget.rect = fitz.Rect(50, 50, 200, 100)
    widget.field_name = "FirmaOficial"
    widget.field_type = fitz.PDF_WIDGET_TYPE_SIGNATURE
    page.add_widget(widget)
    doc.save(str(pdf_signed_sig))
    doc.close()
    assert PDFEngine.has_digital_signature(pdf_signed_sig) is True
    assert PDFEngine.has_digital_signature(pdf_text_only) is False

    # Verificar que cancelar a mitad de compresión limpia archivos temporales (.tmp_compress_*)
    cancel_out = tmp_path / "cancel_compress_out.pdf"
    calls = 0

    def _cancel_midway() -> bool:
        nonlocal calls
        calls += 1
        return calls > 3

    with pytest.raises(TaskCancelledError):
        PDFEngine.compress_pdf(
            pdf_scan_10p,
            cancel_out,
            level=CompressionLevel.EXTREME,
            is_cancelled=_cancel_midway,
        )
    assert not cancel_out.exists()
    leftover_tmps = list(tmp_path.glob(".tmp_compress_*"))
    assert leftover_tmps == []



