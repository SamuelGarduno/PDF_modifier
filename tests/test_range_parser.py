"""Pruebas unitarias para el parser y validador de rangos de páginas."""

from __future__ import annotations

import pytest

from core.exceptions import InvalidPageRangeError
from core.range_parser import parse_page_ranges, validate_page_ranges_realtime


def test_parse_valid_mixed_ranges() -> None:
    """Verifica el caso estándar con rangos y páginas sueltas ('1-5, 8, 11-13')."""
    indices = parse_page_ranges("1-5, 8, 11-13", max_pages=15)
    assert indices == [0, 1, 2, 3, 4, 7, 10, 11, 12]


def test_parse_single_page_and_deduplication() -> None:
    """Verifica páginas individuales y deduplicación preservando el orden."""
    indices = parse_page_ranges("3, 1-3, 2", max_pages=5)
    assert indices == [2, 0, 1]


@pytest.mark.parametrize(
    "invalid_expr",
    [
        "",
        "   ",
        "1-5, ",
        ", 2-3",
        "8-3",  # Rango invertido
        "0-3",  # Página 0 no existe en 1-based
        "1-50",  # Excede max_pages=10
        "12",  # Excede max_pages=10
        "abc",  # No numérico
        "1-2-3",  # Sintaxis inválida
        "-4",  # Negativo o guión suelto
    ],
)
def test_parse_invalid_ranges_raises(invalid_expr: str) -> None:
    """Verifica que cualquier sintaxis inválida o fuera de límites lance InvalidPageRangeError."""
    with pytest.raises(InvalidPageRangeError):
        parse_page_ranges(invalid_expr, max_pages=10)


def test_validate_realtime_helper() -> None:
    """Verifica el validador en tiempo real usado por los inputs de la interfaz."""
    ok, msg, indices = validate_page_ranges_realtime("1-3, 5", max_pages=6)
    assert ok is True
    assert indices == [0, 1, 2, 4]
    assert "4 de 6" in msg

    ok_bad, msg_bad, indices_bad = validate_page_ranges_realtime("9-2", max_pages=6)
    assert ok_bad is False
    assert indices_bad == []
    assert "invertido" in msg_bad.lower()

