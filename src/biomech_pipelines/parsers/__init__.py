"""Registro y detección de adaptadores de dispositivos."""

from __future__ import annotations

import csv
from datetime import datetime
from pathlib import Path

from biomech_pipelines.anonymize import Anonymizer
from biomech_pipelines.models import SesionNormalizada
from biomech_pipelines.parsers import biobit, c3d, csv_generic, mdurance, media
from biomech_pipelines.parsers.base import ParseError, slugify

MEDIA_SUFFIXES = {".mp4", ".mov", ".avi", ".mkv", ".webm"}
C3D_SUFFIXES = {".c3d"}
JSON_SUFFIXES = {".json"}

BIOBIT_MARKERS = {
    "paciente_id",
    "paciente",
    "altura_salto_cm",
    "tiempo_vuelo_ms",
    "pico_fuerza_n",
    "biobit",
}
MDURANCE_MARKERS = {"athlete", "atleta", "test", "prueba", "mdurance"}


def _header_tokens(path: Path) -> set[str]:
    try:
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            header = next(csv.reader(handle), [])
    except (OSError, UnicodeDecodeError, StopIteration):
        return set()
    return {slugify(cell) for cell in header if cell}


def detect_source(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix in C3D_SUFFIXES:
        return "c3d"
    if suffix in MEDIA_SUFFIXES:
        return "media"
    if suffix in JSON_SUFFIXES:
        return "mdurance"
    if suffix == ".csv":
        tokens = _header_tokens(path)
        if {"metrica", "valor"} <= tokens or {"metric", "value"} <= tokens:
            return "csv_generic"
        if tokens & MDURANCE_MARKERS:
            return "mdurance"
        if tokens & BIOBIT_MARKERS:
            return "biobit"
        return "csv_generic"
    raise ParseError(
        f"Formato no soportado: {path.suffix or 'sin extensión'}. "
        "Soportados: CSV, JSON, C3D, MP4/MOV/AVI."
    )


def parse_file(
    path: Path,
    anonymizer: Anonymizer,
    *,
    source: str = "auto",
    protocolo: str | None = None,
    dispositivo: str | None = None,
    fecha: datetime | None = None,
    sujeto: str | None = None,
) -> list[SesionNormalizada]:
    if not path.exists() or not path.is_file():
        raise ParseError(f"No existe el archivo: {path}")
    resolved = detect_source(path) if source == "auto" else source
    if resolved == "biobit":
        return biobit.parse(
            path,
            anonymizer,
            protocolo=protocolo,
            dispositivo=dispositivo,
            fecha=fecha,
            sujeto=sujeto,
        )
    if resolved == "mdurance":
        return mdurance.parse(
            path,
            anonymizer,
            protocolo=protocolo,
            dispositivo=dispositivo,
            fecha=fecha,
            sujeto=sujeto,
        )
    if resolved == "csv_generic":
        return csv_generic.parse(
            path,
            anonymizer,
            protocolo=protocolo,
            dispositivo=dispositivo,
            fecha=fecha,
            sujeto=sujeto,
        )
    if resolved == "c3d":
        return c3d.parse(
            path,
            anonymizer,
            protocolo=protocolo,
            dispositivo=dispositivo,
            fecha=fecha,
            sujeto=sujeto,
        )
    if resolved == "media":
        return media.parse(
            path,
            anonymizer,
            protocolo=protocolo,
            dispositivo=dispositivo,
            fecha=fecha,
            sujeto=sujeto,
        )
    raise ParseError(
        f"Adaptador desconocido: {resolved}. Usar: auto, biobit, mdurance, csv_generic, c3d, media."
    )


__all__ = ["detect_source", "parse_file"]
