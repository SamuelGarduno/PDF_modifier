"""Fixtures compartidos para pruebas del motor PDF y de la interfaz QtQuick."""

from __future__ import annotations

from pathlib import Path
import pymupdf as fitz
from PIL import Image
import pytest


def create_sample_pdf(
    target_path: Path,
    num_pages: int = 5,
    title_prefix: str = "Document",
    password: str | None = None,
) -> Path:
    """Genera un archivo PDF válido con texto y gráficos de prueba."""
    doc = fitz.open()
    try:
        for idx in range(num_pages):
            page = doc.new_page(width=595, height=842)
            page.insert_text(
                fitz.Point(72, 100),
                f"{title_prefix} - Page {idx + 1} of {num_pages}",
                fontsize=20,
                color=(0.12, 0.06, 0.09),
            )
            shape = page.new_shape()
            shape.draw_rect(fitz.Rect(70, 130, 520, 420))
            shape.finish(color=(0.41, 0.11, 0.23), fill=(0.98, 0.94, 0.94), width=2)
            shape.commit()

        if password:
            doc.save(
                str(target_path),
                encryption=fitz.PDF_ENCRYPT_AES_256,
                user_pw=password,
                owner_pw=password,
            )
        else:
            doc.save(str(target_path))
    finally:
        doc.close()
    return target_path


@pytest.fixture
def sample_pdf_5p(tmp_path: Path) -> Path:
    """Fixture de un PDF estándar de 5 páginas."""
    return create_sample_pdf(tmp_path / "sample_5p.pdf", num_pages=5, title_prefix="Sample5")


@pytest.fixture
def sample_pdf_3p(tmp_path: Path) -> Path:
    """Fixture de un PDF secundario de 3 páginas para pruebas de unión."""
    return create_sample_pdf(tmp_path / "sample_3p.pdf", num_pages=3, title_prefix="Sample3")


@pytest.fixture
def encrypted_pdf(tmp_path: Path) -> tuple[Path, str]:
    """Fixture de un PDF cifrado con contraseña conocida."""
    pwd = "coquette_secret_2026"
    pdf_path = create_sample_pdf(
        tmp_path / "locked_doc.pdf", num_pages=4, title_prefix="Locked", password=pwd
    )
    return pdf_path, pwd


@pytest.fixture
def sample_images(tmp_path: Path) -> list[Path]:
    """Genera 3 imágenes PNG/JPG válidas para pruebas de conversión."""
    paths: list[Path] = []
    colors = [(251, 240, 240), (223, 130, 147), (248, 184, 176)]
    for idx, color in enumerate(colors):
        img = Image.new("RGB", (400, 550), color=color)
        ext = "png" if idx % 2 == 0 else "jpg"
        p = tmp_path / f"img_{idx + 1}.{ext}"
        img.save(p)
        paths.append(p)
    return paths

