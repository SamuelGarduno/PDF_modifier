"""Parser y validador de expresiones de rangos de páginas PDF (ej. '1-5, 8, 11-13')."""

from __future__ import annotations

import re
from core.exceptions import InvalidPageRangeError

RANGE_TOKEN_PATTERN = re.compile(r"^\s*(\d+)(?:\s*-\s*(\d+))?\s*$")


def parse_page_ranges(range_expr: str, max_pages: int) -> list[int]:
    """Convierte una cadena de rangos 1-based en una lista de índices 0-based en orden.

    Args:
        range_expr: Cadena como '1-5, 8, 11-13'.
        max_pages: Número total de páginas del documento (debe ser >= 1).

    Returns:
        Lista de índices 0-based sin duplicados consecutivos accidentales pero
        respetando la secuencia solicitada.

    Raises:
        InvalidPageRangeError: Si la cadena está vacía, tiene sintaxis inválida,
            contiene rangos invertidos (ej. '8-3') o páginas fuera de [1, max_pages].
    """
    if max_pages < 1:
        raise InvalidPageRangeError("El documento no contiene páginas válidas.")

    cleaned = range_expr.strip()
    if not cleaned:
        raise InvalidPageRangeError("El rango de páginas no puede estar vacío.")

    parts = [part.strip() for part in cleaned.split(",")]
    if any(not part for part in parts):
        raise InvalidPageRangeError(
            f"Sintaxis inválida en '{range_expr}': hay comas vacías o incompletas."
        )

    result_indices: list[int] = []
    seen_indices: set[int] = set()

    for part in parts:
        match = RANGE_TOKEN_PATTERN.match(part)
        if not match:
            raise InvalidPageRangeError(
                f"Formato inválido en el segmento '{part}'. Usa números o rangos como '1-5, 8'."
            )

        start_str, end_str = match.group(1), match.group(2)
        start_page = int(start_str)
        end_page = int(end_str) if end_str is not None else start_page

        if start_page < 1 or end_page < 1:
            raise InvalidPageRangeError(
                f"Las páginas deben ser mayores o iguales a 1 (recibido: '{part}')."
            )

        if start_page > end_page:
            raise InvalidPageRangeError(
                f"Rango invertido no permitido: '{part}' ({start_page} > {end_page})."
            )

        if end_page > max_pages or start_page > max_pages:
            raise InvalidPageRangeError(
                f"La página solicitada en '{part}' excede el total de páginas ({max_pages})."
            )

        for page_num in range(start_page, end_page + 1):
            zero_based = page_num - 1
            if zero_based not in seen_indices:
                seen_indices.add(zero_based)
                result_indices.append(zero_based)

    return result_indices


def validate_page_ranges_realtime(
    range_expr: str, max_pages: int
) -> tuple[bool, str, list[int]]:
    """Valida una expresión de rango en tiempo real para la UI sin lanzar excepciones.

    Returns:
        Tupla (es_valido, mensaje_estado, lista_indices_0_based).
    """
    try:
        indices = parse_page_ranges(range_expr, max_pages)
        return (
            True,
            f"Se extraerán {len(indices)} de {max_pages} página(s).",
            indices,
        )
    except InvalidPageRangeError as exc:
        return (False, str(exc), [])

