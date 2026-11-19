"""Pruebas unitarias para sanitización de nombres Windows y apertura segura de rutas del footer."""

from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys

import pytest

from core.filename_utils import (
    DEFAULT_FALLBACK_STEM,
    MAX_FILENAME_STEM_LENGTH,
    clean_windows_filename_stem,
    resolve_unique_output_path,
    sanitize_windows_filename,
)
from core.history import OperationHistoryStore
from ui.main_window import CoquetteQuickApp


def test_sanitize_windows_filename_valid_and_special_chars() -> None:
    """Conserva espacios/acentos/ñ, elimina inválidos Windows y recorta extensión .pdf duplicada."""
    assert (
        sanitize_windows_filename(
            "Carta de Presentación — Niño 2026",
            fallback="doc_unido",
        )
        == "Carta de Presentación — Niño 2026"
    )
    assert (
        sanitize_windows_filename(
            'Mi:Archivo*2026?/Final|"Prueba"<1>\\ok',
            fallback="doc_unido",
        )
        == "MiArchivo2026FinalPrueba1ok"
    )
    assert sanitize_windows_filename("informe_final.PDF", fallback="doc") == "informe_final"
    assert sanitize_windows_filename("informe_final.pdf.pdf", fallback="doc") == "informe_final"
    assert sanitize_windows_filename("  ..mi   pliego..  ", fallback="doc") == "mi pliego"

    # Longitud máxima acotada de forma segura
    very_long = "A" * (MAX_FILENAME_STEM_LENGTH + 45)
    cleaned_long = sanitize_windows_filename(very_long, fallback="doc")
    assert len(cleaned_long) == MAX_FILENAME_STEM_LENGTH


@pytest.mark.parametrize(
    "raw_name",
    [
        "",
        "   ",
        "...",
        "***",
        "///",
        '\\/:*?"<>|',
        "CON",
        "prn",
        "Aux.txt",
        "NUL",
        "COM1",
        "LPT9",
    ],
)
def test_sanitize_windows_filename_reverts_to_fallback_on_empty_or_reserved(
    raw_name: str,
) -> None:
    """Si queda vacío, solo inválidos o nombre reservado Windows, revierte al sugerido."""
    assert clean_windows_filename_stem(raw_name) == ""
    assert (
        sanitize_windows_filename(raw_name, fallback="pliego_organizado")
        == "pliego_organizado"
    )
    assert sanitize_windows_filename(raw_name, fallback="///") == DEFAULT_FALLBACK_STEM


def test_resolve_unique_output_path_incremental_and_protected(tmp_path: Path) -> None:
    """Agrega sufijo incremental ' (1)', ' (2)' cuando existe destino o coincide con entrada."""
    out_dir = tmp_path / "Destino con Espacios & Ñ"
    out_dir.mkdir(parents=True)

    first = resolve_unique_output_path(
        out_dir, desired_stem="Contrato Final", fallback_stem="fallback"
    )
    assert first == out_dir.resolve() / "Contrato Final.pdf"
    first.write_bytes(b"%PDF-1.4\n")

    second = resolve_unique_output_path(
        out_dir, desired_stem="Contrato Final", fallback_stem="fallback"
    )
    assert second == out_dir.resolve() / "Contrato Final (1).pdf"
    second.write_bytes(b"%PDF-1.4\n")

    third = resolve_unique_output_path(
        out_dir, desired_stem="Contrato Final", fallback_stem="fallback"
    )
    assert third == out_dir.resolve() / "Contrato Final (2).pdf"

    # Si el nombre deseado coincide con un archivo protegido de entrada, tampoco sobrescribe
    protected_file = out_dir / "Original Protegido.pdf"
    protected_file.write_bytes(b"%PDF-1.4\n")
    protected_res = resolve_unique_output_path(
        out_dir,
        desired_stem="Original Protegido",
        fallback_stem="Original Protegido_modificado",
        protected_inputs={protected_file},
    )
    assert protected_res == out_dir.resolve() / "Original Protegido (1).pdf"

    # Si el nombre deseado es inválido ('***'), usa el fallback y protege contra colisión
    existing_fallback = out_dir / "mi_fallback.pdf"
    existing_fallback.write_bytes(b"%PDF-1.4\n")
    reverted = resolve_unique_output_path(
        out_dir,
        desired_stem="***",
        fallback_stem="mi_fallback",
    )
    assert reverted == out_dir.resolve() / "mi_fallback (1).pdf"


def test_bridge_last_output_file_path_and_safe_open_in_windows(
    sample_pdf_5p: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    qtbot,
) -> None:
    """Verifica lastOutputFilePath independiente de la cola, rutas con espacios/acentos y fallback Explorer."""
    special_out_dir = tmp_path / "Carpeta de Pruebas — Ñoño & Acentos áéíóú"
    special_out_dir.mkdir(parents=True)

    store = OperationHistoryStore(storage_path=tmp_path / "paths_hist.json")
    app_wrapper = CoquetteQuickApp(history_store=store)
    bridge = app_wrapper.studio_bridge

    bridge.addSingleFilePath(str(sample_pdf_5p))
    bridge.setOutputDirectory(str(special_out_dir))
    bridge.selectTool("split")
    bridge.setRangeExpr("1-2")
    bridge.setOutputFileName("Acta Sesión Ñoño 2026")
    bridge.commitOutputFileName()

    with qtbot.waitSignal(bridge.operationCompleted, timeout=10000) as blocker:
        bridge.executeActiveOperation()

    generated_path = Path(blocker.args[1]).resolve()
    assert generated_path.exists()
    assert generated_path.parent == special_out_dir.resolve()
    assert generated_path.name == "Acta Sesión Ñoño 2026.pdf"
    assert bridge.lastOutputFilePath == str(generated_path)

    # Vaciar completamente la cola NO debe invalidar ni borrar lastOutputFilePath
    bridge.clearFiles()
    assert bridge.fileCount == 0
    assert bridge.lastOutputFilePath == str(generated_path)

    # Simular entorno Windows y verificar os.startfile / subprocess.Popen con la ruta normalizada
    monkeypatch.setattr(sys, "platform", "win32")
    started_paths: list[str] = []
    popen_cmds: list[list[str]] = []

    def _fake_startfile(path_arg: str) -> None:
        started_paths.append(path_arg)

    def _fake_popen(cmd: list[str], *_args, **_kwargs):
        popen_cmds.append(cmd)
        return object()

    monkeypatch.setattr(os, "startfile", _fake_startfile, raising=False)
    monkeypatch.setattr(subprocess, "Popen", _fake_popen)

    assert bridge.openFileInSystem("") is True
    assert started_paths[-1] == str(generated_path)

    assert bridge.showFileInFolder("") is True
    assert popen_cmds[-1] == ["explorer", "/select,", str(generated_path)]

    # Si explorer /select falla con OSError, debe hacer fallback a os.startfile(parent)
    def _failing_popen(*_args, **_kwargs):
        raise OSError("Explorer no disponible")

    monkeypatch.setattr(subprocess, "Popen", _failing_popen)
    assert bridge.showFileInFolder(bridge.lastOutputFilePath) is True
    assert started_paths[-1] == str(generated_path.parent)

    # Si el archivo ya no existe, openFileInSystem falla limpiamente con aviso sin lanzar excepción
    generated_path.unlink()
    errors: list[str] = []
    bridge.errorOccurred.connect(errors.append)
    assert bridge.openFileInSystem(bridge.lastOutputFilePath) is False
    assert errors and "No se encontró el archivo" in errors[-1]

    # showFileInFolder con archivo faltante pero carpeta existente hace fallback seguro a la carpeta
    assert bridge.showFileInFolder(bridge.lastOutputFilePath) is True
    assert started_paths[-1] == str(generated_path.parent)
