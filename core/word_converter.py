"""Conversor de documentos Microsoft Word (.docx/.doc) a PDF usando motor nativo vía PowerShell COM."""

from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys
import time
from typing import Callable

from core.exceptions import PDFStudioError, TaskCancelledError
from core.filename_utils import clean_windows_filename_stem, resolve_unique_output_path
from core.models import OperationResult, ToolType

if sys.platform == "win32":
    import winreg
else:  # pragma: no cover - Solo en entornos no Windows
    winreg = None  # type: ignore[assignment]

MOCK_WORD_ENV_VAR = "FLORAL_MOCK_WORD"
WORD_EXPORT_FORMAT_PDF = 17
WORD_CLSID_SUBKEY = r"Word.Application\CLSID"
POWERSHELL_EXECUTABLE = "powershell"
SUPPORTED_WORD_EXTENSIONS: frozenset[str] = frozenset({".docx", ".doc"})
WORD_POLL_INTERVAL_SECONDS = 0.15


def is_mock_word_enabled() -> bool:
    """Indica si está activo el modo simulado para pruebas sin Microsoft Word."""
    return os.environ.get(MOCK_WORD_ENV_VAR, "").strip() == "1"


def is_word_installed() -> bool:
    """Verifica mediante el Registro de Windows si Microsoft Word está instalado."""
    if sys.platform != "win32" or winreg is None:
        return False
    try:
        with winreg.OpenKey(winreg.HKEY_CLASSES_ROOT, WORD_CLSID_SUBKEY):
            return True
    except OSError:
        return False


def escape_powershell_single_quoted(value: str) -> str:
    """Escapa comillas simples para literales entre comillas simples en PowerShell."""
    return str(value).replace("'", "''")


def build_word_to_pdf_ps_script(input_path: Path, output_path: Path) -> str:
    """Construye el script PowerShell oculto que exporta un documento Word a PDF vía COM."""
    escaped_in = escape_powershell_single_quoted(str(Path(input_path).resolve()))
    escaped_out = escape_powershell_single_quoted(str(Path(output_path).resolve()))
    return (
        "$ErrorActionPreference = 'Stop'\n"
        f"$inPath = '{escaped_in}'\n"
        f"$outPath = '{escaped_out}'\n"
        "$word = $null\n"
        "$doc = $null\n"
        "try {\n"
        "    $word = New-Object -ComObject Word.Application\n"
        "    $word.Visible = $false\n"
        "    $word.DisplayAlerts = 0\n"
        "    $doc = $word.Documents.Open($inPath, $false, $true, $false)\n"
        f"    $doc.ExportAsFixedFormat($outPath, {WORD_EXPORT_FORMAT_PDF})\n"
        "} finally {\n"
        "    if ($doc -ne $null) {\n"
        "        try { $doc.Close([ref]$false) } catch {}\n"
        "        try { [void][System.Runtime.InteropServices.Marshal]::FinalReleaseComObject($doc) } catch {}\n"
        "    }\n"
        "    if ($word -ne $null) {\n"
        "        try { $word.Quit([ref]$false) } catch {}\n"
        "        try { [void][System.Runtime.InteropServices.Marshal]::FinalReleaseComObject($word) } catch {}\n"
        "    }\n"
        "    [GC]::Collect()\n"
        "    [GC]::WaitForPendingFinalizers()\n"
        "}\n"
    )


def _generate_mock_pdf(input_path: Path, output_path: Path) -> None:
    """Genera un PDF válido con PyMuPDF para probar el flujo sin Word instalado."""
    import pymupdf as fitz

    doc = fitz.open()
    try:
        page = doc.new_page(width=595, height=842)
        text = (
            "Mesa de Trabajo Floral - Conversión Word simulada\n"
            f"Modo de prueba: {MOCK_WORD_ENV_VAR}=1\n"
            f"Documento origen: {input_path.name}\n"
        )
        page.insert_text((56, 90), text, fontsize=14, color=(0.32, 0.1, 0.16))
        doc.save(str(output_path), deflate=True)
    finally:
        doc.close()


def _terminate_process_safely(proc: subprocess.Popen[str]) -> None:
    """Detiene un subproceso PowerShell activo ante cancelación sin propagar errores."""
    try:
        proc.terminate()
        proc.wait(timeout=2.0)
    except Exception:
        try:
            proc.kill()
        except Exception:
            pass


def convert_word_to_pdf(
    input_path: Path,
    output_path: Path,
    on_progress: Callable[[int, str], None] | None = None,
    is_cancelled: Callable[[], bool] | None = None,
) -> OperationResult:
    """Convierte un archivo .docx o .doc a PDF usando Word COM o modo simulado."""
    from core.pdf_engine import ensure_safe_output_path

    src_path = Path(input_path)
    if not src_path.exists() or not src_path.is_file():
        raise PDFStudioError(f"El archivo '{src_path.name}' no existe.")
    if src_path.suffix.lower() not in SUPPORTED_WORD_EXTENSIONS:
        raise PDFStudioError(
            f"Formato no compatible para Word a PDF: '{src_path.name}'."
        )
    if is_cancelled is not None and is_cancelled():
        raise TaskCancelledError("Operación cancelada por el usuario.")

    original_bytes = src_path.stat().st_size
    safe_dest = ensure_safe_output_path(src_path, Path(output_path), default_suffix="")
    safe_dest.parent.mkdir(parents=True, exist_ok=True)

    if on_progress is not None:
        on_progress(15, f"Preparando conversión de '{src_path.name}'...")

    if is_mock_word_enabled():
        _generate_mock_pdf(src_path, safe_dest)
        if on_progress is not None:
            on_progress(100, f"Conversión simulada completada: {safe_dest.name}")
        final_bytes = safe_dest.stat().st_size
        return OperationResult(
            tool=ToolType.WORD_TO_PDF,
            output_files=[safe_dest],
            original_size_bytes=original_bytes,
            final_size_bytes=final_bytes,
            saved_percentage=0.0,
            message=f"Word convertido (simulado) a '{safe_dest.name}'.",
        )

    if not is_word_installed():
        raise PDFStudioError(
            "Microsoft Word no está instalado en este equipo. "
            "Para convertir archivos .docx o .doc a PDF se requiere tener Microsoft Word instalado."
        )

    script = build_word_to_pdf_ps_script(src_path, safe_dest)
    creation_flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)

    if on_progress is not None:
        on_progress(35, f"Abriendo '{src_path.name}' en Microsoft Word...")

    try:
        proc = subprocess.Popen(
            [
                POWERSHELL_EXECUTABLE,
                "-NoProfile",
                "-NonInteractive",
                "-ExecutionPolicy",
                "Bypass",
                "-Command",
                script,
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            creationflags=creation_flags,
        )
    except OSError as exc:
        raise PDFStudioError(
            f"No se pudo iniciar PowerShell para convertir '{src_path.name}': {exc}"
        ) from exc

    while proc.poll() is None:
        if is_cancelled is not None and is_cancelled():
            _terminate_process_safely(proc)
            raise TaskCancelledError("Operación cancelada por el usuario.")
        time.sleep(WORD_POLL_INTERVAL_SECONDS)

    stdout_text, stderr_text = proc.communicate()
    if proc.returncode != 0:
        detail = (stderr_text or stdout_text or "").strip()
        if len(detail) > 220:
            detail = detail[:220] + "..."
        raise PDFStudioError(
            f"Microsoft Word no pudo convertir '{src_path.name}'"
            + (f": {detail}" if detail else ".")
        )

    if not safe_dest.exists() or safe_dest.stat().st_size == 0:
        raise PDFStudioError(
            f"Word finalizó sin generar el archivo PDF para '{src_path.name}'."
        )

    if on_progress is not None:
        on_progress(100, f"Convertido a '{safe_dest.name}'.")

    final_bytes = safe_dest.stat().st_size
    return OperationResult(
        tool=ToolType.WORD_TO_PDF,
        output_files=[safe_dest],
        original_size_bytes=original_bytes,
        final_size_bytes=final_bytes,
        saved_percentage=0.0,
        message=f"Documento Word convertido a '{safe_dest.name}'.",
    )


def convert_word_batch(
    input_files: list[Path],
    out_dir: Path,
    custom_base_name: str = "",
    on_progress: Callable[[int, str], None] | None = None,
    is_cancelled: Callable[[], bool] | None = None,
) -> OperationResult:
    """Convierte múltiples archivos Word (.docx/.doc) a PDF en lote sin sobrescribir originales."""
    if not input_files:
        raise PDFStudioError("No hay archivos de Word para convertir.")

    clean_custom = clean_windows_filename_stem(custom_base_name, extension=".pdf")
    protected_set = {Path(p).resolve() for p in input_files}
    outputs: list[Path] = []
    total_orig = 0
    total_final = 0
    total = len(input_files)

    for idx, word_path in enumerate(input_files):
        if is_cancelled is not None and is_cancelled():
            raise TaskCancelledError("Operación cancelada por el usuario.")

        fallback_stem = word_path.stem
        desired_stem = f"{clean_custom}_{idx + 1}" if clean_custom else fallback_stem
        dest = resolve_unique_output_path(
            out_dir,
            desired_stem,
            fallback_stem,
            extension=".pdf",
            protected_inputs=protected_set,
        )

        def _sub_progress(pct: int, msg: str, i: int = idx) -> None:
            if on_progress is not None:
                overall = int(((i + (pct / 100.0)) / total) * 100)
                on_progress(overall, f"[{i + 1}/{total}] {msg}")

        res = convert_word_to_pdf(
            word_path,
            dest,
            on_progress=_sub_progress,
            is_cancelled=is_cancelled,
        )
        outputs.extend(res.output_files)
        total_orig += res.original_size_bytes
        total_final += res.final_size_bytes

    return OperationResult(
        tool=ToolType.WORD_TO_PDF,
        output_files=outputs,
        original_size_bytes=total_orig,
        final_size_bytes=total_final,
        saved_percentage=0.0,
        message=f"Se convirtieron {len(outputs)} documento(s) Word a PDF.",
    )
