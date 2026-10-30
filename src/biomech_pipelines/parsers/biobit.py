"""Adaptador para exportaciones CSV de Biobit."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

from biomech_pipelines.anonymize import Anonymizer
from biomech_pipelines.parsers.base import (
    build_session,
    file_datetime,
    infer_protocol,
    numeric_metrics,
    parse_datetime,
    pick,
    read_csv,
)

SUBJECT_ALIASES = (
    "paciente_id",
    "paciente",
    "sujeto_id",
    "sujeto",
    "subject",
    "subject_id",
    "atleta",
    "athlete",
)
DATE_ALIASES = ("fecha", "fecha_hora", "fecha_evaluacion", "date", "timestamp", "datetime")
PROTOCOL_ALIASES = ("protocolo", "tipo_protocolo", "test", "prueba", "tipo")
DEVICE_ALIASES = ("dispositivo", "dispositivo_origen", "device", "equipo")
ID_ALIASES = ("id", "evaluacion_id", "session_id", "sesion_id")
RESERVED = set(SUBJECT_ALIASES + DATE_ALIASES + PROTOCOL_ALIASES + DEVICE_ALIASES + ID_ALIASES)


def parse(
    path: Path,
    anonymizer: Anonymizer,
    *,
    protocolo: str | None = None,
    dispositivo: str | None = None,
    fecha: datetime | None = None,
    sujeto: str | None = None,
) -> list[Any]:
    frame = read_csv(path)
    sessions = []
    fallback_date = fecha or file_datetime(path)

    for row_number, (_, row) in enumerate(frame.iterrows(), start=2):
        raw_subject = pick(row, SUBJECT_ALIASES) or sujeto
        if raw_subject is None:
            raise ValueError(
                f"{path.name}: la fila {row_number} no tiene paciente/sujeto. "
                "Agregá una columna paciente_id o usá --subject."
            )
        raw_protocol = pick(row, PROTOCOL_ALIASES)
        resolved_protocol = protocolo or infer_protocol(raw_protocol, path.stem, default="otro")
        resolved_device = dispositivo or str(pick(row, DEVICE_ALIASES) or "Biobit")
        metrics = numeric_metrics(row, exclude=RESERVED)
        metadata = {
            "formato_export": "biobit_csv",
            "fila": row_number,
        }
        if raw_protocol is not None:
            metadata["test_original"] = str(raw_protocol)

        sessions.append(
            build_session(
                source="biobit",
                source_path=path,
                anonymizer=anonymizer,
                raw_subject=raw_subject,
                fallback_subject=path.stem,
                date_value=pick(row, DATE_ALIASES) or fecha,
                fallback_date=fallback_date,
                protocol=resolved_protocol,
                device=resolved_device,
                metrics=metrics,
                metadata=metadata,
            )
        )

    return sessions


__all__ = ["parse", "parse_datetime"]
