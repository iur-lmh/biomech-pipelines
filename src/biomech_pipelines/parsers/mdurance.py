"""Adaptador para exportaciones CSV/JSON de mDurance."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd

from biomech_pipelines.anonymize import Anonymizer
from biomech_pipelines.models import SesionNormalizada
from biomech_pipelines.parsers.base import (
    ParseError,
    build_session,
    file_datetime,
    infer_protocol,
    normalize_columns,
    numeric_metrics,
    pick,
    read_csv,
)

SUBJECT_ALIASES = (
    "athlete",
    "atleta",
    "sujeto_id",
    "paciente_id",
    "subject",
    "subject_id",
    "paciente",
)
DATE_ALIASES = ("date", "fecha", "fecha_hora", "timestamp", "datetime")
PROTOCOL_ALIASES = ("test", "prueba", "protocolo", "tipo_protocolo", "ejercicio")
DEVICE_ALIASES = ("device", "dispositivo", "equipo")
ID_ALIASES = ("id", "session_id", "sesion_id", "evaluacion_id")
RESERVED = set(SUBJECT_ALIASES + DATE_ALIASES + PROTOCOL_ALIASES + DEVICE_ALIASES + ID_ALIASES)


def _load_frame(path: Path) -> pd.DataFrame:
    if path.suffix.lower() == ".json":
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise ParseError(f"{path.name}: JSON inválido ({exc})") from exc
        if isinstance(payload, dict):
            for key in ("sessions", "items", "data", "registros"):
                if isinstance(payload.get(key), list):
                    payload = payload[key]
                    break
            else:
                payload = [payload]
        if not isinstance(payload, list):
            raise ParseError(f"{path.name}: se esperaba una lista de sesiones")
        return normalize_columns(pd.DataFrame(payload))
    return read_csv(path)


def parse(
    path: Path,
    anonymizer: Anonymizer,
    *,
    protocolo: str | None = None,
    dispositivo: str | None = None,
    fecha: datetime | None = None,
    sujeto: str | None = None,
) -> list[SesionNormalizada]:
    frame = _load_frame(path)
    fallback_date = fecha or file_datetime(path)
    sessions: list[SesionNormalizada] = []

    for row_number, (_, row) in enumerate(frame.iterrows(), start=2):
        raw_subject = pick(row, SUBJECT_ALIASES) or sujeto
        if raw_subject is None:
            raise ParseError(
                f"{path.name}: la fila {row_number} no tiene atleta/sujeto. "
                "Indicá --subject o agregá la columna Athlete."
            )
        raw_protocol = pick(row, PROTOCOL_ALIASES)
        resolved_protocol = protocolo or infer_protocol(raw_protocol, path.stem, default="otro")
        resolved_device = dispositivo or str(pick(row, DEVICE_ALIASES) or "mDurance")
        metrics = numeric_metrics(row, exclude=RESERVED)
        metadata: dict[str, Any] = {
            "formato_export": "mdurance_json" if path.suffix.lower() == ".json" else "mdurance_csv",
            "fila": row_number,
        }
        if raw_protocol is not None:
            metadata["test_original"] = str(raw_protocol)

        sessions.append(
            build_session(
                source="mdurance",
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
