"""Utilidades puras de sanitización de nombres y resolución única de rutas en Windows."""

from __future__ import annotations

from pathlib import Path
import re

WINDOWS_INVALID_FILENAME_CHARS_RE = re.compile(r'[\\/:*?"<>|\x00-\x1f]')
WINDOWS_RESERVED_DEVICE_NAMES: frozenset[str] = frozenset(
    {
        "CON",
        "PRN",
        "AUX",
        "NUL",
        *(f"COM{i}" for i in range(1, 10)),
        *(f"LPT{i}" for i in range(1, 10)),
    }
)
MAX_FILENAME_STEM_LENGTH = 180
DEFAULT_FALLBACK_STEM = "documento"


def _strip_trailing_extension(text: str, extension: str) -> str:
    """Elimina la extensión final repetida (insensible a mayúsculas) si existe."""
    ext = (extension or "").strip()
    if not ext:
        return text
    ext_lower = ext.lower()
    while text.lower().endswith(ext_lower):
        text = text[: -len(ext)].strip()
    return text


def clean_windows_filename_stem(raw_name: str, extension: str = ".pdf") -> str:
    """Limpia un nombre base para Windows devolviendo cadena vacía si resulta inválido."""
    text = (raw_name or "").strip()
    if not text:
        return ""

    text = _strip_trailing_extension(text, extension)
    text = WINDOWS_INVALID_FILENAME_CHARS_RE.sub("", text)
    text = _strip_trailing_extension(text, extension)
    text = re.sub(r"\s+", " ", text).strip(" .")

    if not text:
        return ""

    if len(text) > MAX_FILENAME_STEM_LENGTH:
        text = text[:MAX_FILENAME_STEM_LENGTH].strip(" .")

    if not text:
        return ""

    first_segment = text.split(".", 1)[0].strip().upper()
    if first_segment in WINDOWS_RESERVED_DEVICE_NAMES:
        return ""

    return text


def sanitize_windows_filename(
    raw_name: str,
    fallback: str,
    extension: str = ".pdf",
) -> str:
    """Sanitiza un nombre personalizado o revierte automáticamente al nombre sugerido seguro."""
    cleaned = clean_windows_filename_stem(raw_name, extension=extension)
    if cleaned:
        return cleaned

    fallback_clean = clean_windows_filename_stem(fallback, extension=extension)
    return fallback_clean or DEFAULT_FALLBACK_STEM


def resolve_unique_output_path(
    target_dir: Path,
    desired_stem: str,
    fallback_stem: str,
    extension: str = ".pdf",
    protected_inputs: set[Path] | None = None,
) -> Path:
    """Resuelve una ruta única en destino añadiendo sufijo ' (1)', ' (2)' si ya existe."""
    safe_stem = sanitize_windows_filename(
        desired_stem,
        fallback=fallback_stem,
        extension=extension,
    )
    out_dir = Path(target_dir).resolve()
    protected = {Path(p).resolve() for p in (protected_inputs or set())}

    candidate = out_dir / f"{safe_stem}{extension}"
    if not candidate.exists() and candidate.resolve() not in protected:
        return candidate

    counter = 1
    while True:
        alt = out_dir / f"{safe_stem} ({counter}){extension}"
        if not alt.exists() and alt.resolve() not in protected:
            return alt
        counter += 1
