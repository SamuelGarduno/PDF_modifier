"""Pruebas unitarias para la detección y conversión de Word (.docx/.doc) a PDF."""

from __future__ import annotations

from pathlib import Path
import subprocess
from unittest.mock import MagicMock, patch

import pymupdf as fitz
import pytest

from core.exceptions import PDFStudioError
from core.models import ToolType
from core.word_converter import (
    MOCK_WORD_ENV_VAR,
    build_word_to_pdf_ps_script,
    convert_word_batch,
    convert_word_to_pdf,
    escape_powershell_single_quoted,
    is_word_installed,
)


def test_escape_powershell_single_quoted_and_special_paths(tmp_path: Path) -> None:
    """Verifica el escape seguro de rutas con espacios, comillas simples, paréntesis y acentos."""
    raw = r"D:\Tareas\Documentación\Ensayo 'Final' (1).docx"
    escaped = escape_powershell_single_quoted(raw)
    assert escaped == r"D:\Tareas\Documentación\Ensayo ''Final'' (1).docx"

    doc_dir = tmp_path / "Carpetá (Prueba)"
    doc_dir.mkdir(parents=True, exist_ok=True)
    word_file = doc_dir / "Ensayo 'Final' (1) café.docx"
    word_file.write_bytes(b"fake docx content")
    out_pdf = doc_dir / "Ensayo 'Final' (1) café.pdf"

    script = build_word_to_pdf_ps_script(word_file, out_pdf)
    assert "''Final''" in script
    assert "café" in script
    assert "$word.Visible = $false" in script
    assert "ExportAsFixedFormat($outPath, 17)" in script
    assert "finally {" in script
    assert "$word.Quit" in script


@patch("core.word_converter.winreg")
def test_is_word_installed_via_winreg(mock_winreg: MagicMock, monkeypatch: pytest.MonkeyPatch) -> None:
    """Verifica la detección de Microsoft Word consultando el Registro de Windows."""
    monkeypatch.setattr("core.word_converter.sys.platform", "win32")
    mock_ctx = MagicMock()
    mock_winreg.OpenKey.return_value = mock_ctx
    mock_winreg.HKEY_CLASSES_ROOT = 123

    assert is_word_installed() is True
    mock_winreg.OpenKey.assert_called_once()

    mock_winreg.OpenKey.side_effect = FileNotFoundError("No registry key")
    assert is_word_installed() is False


@patch("core.word_converter.is_word_installed", return_value=False)
def test_convert_word_without_word_installed_raises_friendly_error(
    _mock_installed: MagicMock, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Si Word no está instalado y no hay modo mock, debe lanzar PDFStudioError amigable."""
    monkeypatch.delenv(MOCK_WORD_ENV_VAR, raising=False)
    src_docx = tmp_path / "carta.docx"
    src_docx.write_bytes(b"dummy docx")
    out_pdf = tmp_path / "carta.pdf"

    with pytest.raises(PDFStudioError) as exc_info:
        convert_word_to_pdf(src_docx, out_pdf)

    assert "Microsoft Word no está instalado" in str(exc_info.value)


@patch("core.word_converter.subprocess.Popen")
@patch("core.word_converter.is_word_installed", return_value=True)
def test_convert_word_success_mocked_powershell(
    _mock_installed: MagicMock,
    mock_popen: MagicMock,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Valida la invocación oculta de PowerShell COM y generación exitosa simulada por mock."""
    monkeypatch.delenv(MOCK_WORD_ENV_VAR, raising=False)
    src_docx = tmp_path / "Informe 'Anual' (2).docx"
    src_docx.write_bytes(b"PK\x03\x04dummy")
    out_pdf = tmp_path / "Informe 'Anual' (2).pdf"

    def _fake_popen(cmd: list[str], **kwargs: object) -> MagicMock:
        # Simular que PowerShell generó el PDF correctamente
        doc = fitz.open()
        doc.new_page()
        doc.save(str(out_pdf))
        doc.close()

        proc = MagicMock()
        proc.poll.return_value = 0
        proc.returncode = 0
        proc.communicate.return_value = ("", "")
        return proc

    mock_popen.side_effect = _fake_popen

    result = convert_word_to_pdf(src_docx, out_pdf)

    assert result.tool == ToolType.WORD_TO_PDF
    assert result.output_files == [out_pdf]
    assert out_pdf.exists()

    call_args, call_kwargs = mock_popen.call_args
    cmd_list = call_args[0]
    assert cmd_list[0] == "powershell"
    assert "-Command" in cmd_list
    assert "''Anual''" in cmd_list[-1]
    assert call_kwargs["creationflags"] == getattr(subprocess, "CREATE_NO_WINDOW", 0)


def test_convert_word_mock_mode_generates_valid_pdf(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Con FLORAL_MOCK_WORD=1 genera un PDF válido indicando el nombre del archivo origen."""
    monkeypatch.setenv(MOCK_WORD_ENV_VAR, "1")
    src_doc = tmp_path / "Minuta Reunión (1).doc"
    src_doc.write_bytes(b"doc-bytes")
    out_pdf = tmp_path / "Minuta Reunión (1).pdf"

    result = convert_word_to_pdf(src_doc, out_pdf)

    assert result.tool == ToolType.WORD_TO_PDF
    assert out_pdf.exists()
    with fitz.open(out_pdf) as pdf:
        assert len(pdf) == 1
        text = pdf[0].get_text()
        assert "Minuta Reunión (1).doc" in text


def test_convert_word_batch_mock_mode(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Valida la conversión en lote de varios documentos Word en modo simulado."""
    monkeypatch.setenv(MOCK_WORD_ENV_VAR, "1")
    w1 = tmp_path / "uno.docx"
    w2 = tmp_path / "dos.doc"
    w1.write_bytes(b"1")
    w2.write_bytes(b"2")
    out_dir = tmp_path / "salida"

    res = convert_word_batch([w1, w2], out_dir, custom_base_name="acta")
    assert len(res.output_files) == 2
    assert [p.name for p in res.output_files] == ["acta_1.pdf", "acta_2.pdf"]
    assert all(p.exists() for p in res.output_files)
