"""Adaptador para CSV genérico: formato tidy largo o ancho."""

from __future__ import annotations

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
    numeric_metrics,
    parse_datetime,
    pick,
    read_csv,
    to_number,
)

SUBJECT_ALIASES = ("sujeto_id", "paciente_id", "subject_id", "sujeto", "paciente", "subject")
DATE_ALIASES = ("fecha", "fecha_hora", "fecha_evaluacion", "date", "timestamp", "datetime")
PROTOCOL_ALIASES = ("protocolo", "tipo_protocolo", "test", "prueba")
DEVICE_ALIASES = ("dispositivo", "dispositivo_origen", "device", "equipo")
METRIC_ALIASES = ("metrica", "variable", "metric", "nombre_metrica")
VALUE_ALIASES = ("valor", "value", "resultado")
UNIT_ALIASES = ("unidad", "unit", "units")
RESERVED = set(
    SUBJECT_ALIASES
    + DATE_ALIASES
    + PROTOCOL_ALIASES
    + DEVICE_ALIASES
    + METRIC_ALIASES
    + VALUE_ALIASES
    + UNIT_ALIASES
)


def _parse_long(
    frame: pd.DataFrame,
    path: Path,
    anonymizer: Anonymizer,
    *,
    protocolo: str | None,
    dispositivo: str | None,
    fecha: datetime | None,
    sujeto: str | None,
) -> list[SesionNormalizada]:
    fallback_date = fecha or file_datetime(path)
    sessions: list[SesionNormalizada] = []

    group_columns = [
        column
        for column in frame.columns
        if column in RESERVED
        and column not in METRIC_ALIASES
        and column not in VALUE_ALIASES
        and column not in UNIT_ALIASES
    ]
    groups = (
        frame.groupby(group_columns, dropna=False, sort=False) if group_columns else [(0, frame)]
    )
    for _, group in groups:
        first = group.iloc[0]
        raw_subject = pick(first, SUBJECT_ALIASES) or sujeto
        if raw_subject is None:
            raise ParseError(
                f"{path.name}: falta sujeto_id. En formato tidy cada fila debe indicar el sujeto."
            )

        metrics: dict[str, float | int | str | bool] = {}
        units: dict[str, str] = {}
        for _, row in group.iterrows():
            metric_name = pick(row, METRIC_ALIASES)
            raw_value = pick(row, VALUE_ALIASES)
            if metric_name is None or raw_value is None:
                continue
            number = to_number(raw_value)
            metrics[str(metric_name)] = number if number is not None else str(raw_value)
            unit = pick(row, UNIT_ALIASES)
            if unit is not None:
                units[str(metric_name)] = str(unit)

        raw_protocol = pick(first, PROTOCOL_ALIASES)
        resolved_protocol = protocolo or infer_protocol(raw_protocol, path.stem, default="otro")
        resolved_device = dispositivo or str(pick(first, DEVICE_ALIASES) or "Manual")
        metadata: dict[str, Any] = {
            "formato_export": "tidy_long",
        }
        if units:
            metadata["unidades"] = units

        sessions.append(
            build_session(
                source="csv_generic",
                source_path=path,
                anonymizer=anonymizer,
                raw_subject=raw_subject,
                fallback_subject=path.stem,
                date_value=pick(first, DATE_ALIASES) or fecha,
                fallback_date=fallback_date,
                protocol=resolved_protocol,
                device=resolved_device,
                metrics=metrics,
                metadata=metadata,
            )
        )
    return sessions


def parse(
    path: Path,
    anonymizer: Anonymizer,
    *,
    protocolo: str | None = None,
    dispositivo: str | None = None,
    fecha: datetime | None = None,
    sujeto: str | None = None,
) -> list[SesionNormalizada]:
    frame = read_csv(path)
    fallback_date = fecha or file_datetime(path)

    if any(column in frame.columns for column in METRIC_ALIASES) and any(
        column in frame.columns for column in VALUE_ALIASES
    ):
        return _parse_long(
            frame,
            path,
            anonymizer,
            protocolo=protocolo,
            dispositivo=dispositivo,
            fecha=fecha,
            sujeto=sujeto,
        )

    sessions: list[SesionNormalizada] = []
    for row_number, (_, row) in enumerate(frame.iterrows(), start=2):
        raw_subject = pick(row, SUBJECT_ALIASES) or sujeto
        if raw_subject is None:
            raise ParseError(f"{path.name}: falta sujeto_id/paciente_id en la fila {row_number}.")
        raw_protocol = pick(row, PROTOCOL_ALIASES)
        resolved_protocol = protocolo or infer_protocol(raw_protocol, path.stem, default="otro")
        metrics = numeric_metrics(row, exclude=RESERVED)
        sessions.append(
            build_session(
                source="csv_generic",
                source_path=path,
                anonymizer=anonymizer,
                raw_subject=raw_subject,
                fallback_subject=path.stem,
                date_value=pick(row, DATE_ALIASES) or fecha,
                fallback_date=fallback_date,
                protocol=resolved_protocol,
                device=dispositivo or str(pick(row, DEVICE_ALIASES) or "Manual"),
                metrics=metrics,
                metadata={"formato_export": "wide", "fila": row_number},
            )
        )
    return sessions


__all__ = ["parse", "parse_datetime"]
