"""Excepciones personalizadas para el motor de procesamiento PDF."""

from __future__ import annotations


class PDFStudioError(Exception):
    """Excepción base para errores de la suite PDF."""


class PDFCorruptedError(PDFStudioError):
    """Se lanza cuando un archivo PDF está vacío, corrupto o tiene extensión falsa."""


class PDFEncryptedError(PDFStudioError):
    """Se lanza cuando se intenta procesar un PDF protegido sin la contraseña correcta."""


class InvalidPasswordError(PDFEncryptedError):
    """Se lanza cuando la contraseña proporcionada para desbloquear un PDF es incorrecta."""


class InvalidPageRangeError(PDFStudioError):
    """Se lanza cuando la sintaxis o los límites del rango de páginas son inválidos."""


class TaskCancelledError(PDFStudioError):
    """Se lanza cuando el usuario cancela explícitamente una operación en curso."""

