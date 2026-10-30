"""Utilidades compartidas por los adaptadores de dispositivos."""

from __future__ import annotations

import hashlib
import math
import re
import unicodedata
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pandas as pd

from biomech_pipelines.anonymize import Anonymizer, hash_file
from biomech_pipelines.models import ArchivoReferencia, SesionNormalizada


class ParseError(ValueError):
    """El archivo no cumple el formato esperado por el adaptador."""


def slugify(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value)
    ascii_value = "".join(char for char in normalized if not unicodedata.combining(char))
    return re.sub(r"[^a-z0-9]+", "_", ascii_value.lower()).strip("_")


def normalize_columns(frame: pd.DataFrame) -> pd.DataFrame:
    """Normaliza encabezados a snake_case ASCII y resuelve duplicados."""
    result = frame.copy()
    seen: dict[str, int] = {}
    columns: list[str] = []
    for column in result.columns:
        base = slugify(str(column)) or "columna"
        count = seen.get(base, 0)
        seen[base] = count + 1
        columns.append(base if count == 0 else f"{base}_{count + 1}")
    result.columns = columns
    return result


def read_csv(path: Path) -> pd.DataFrame:
    try:
        frame = pd.read_csv(path)
    except Exception as exc:  # pandas expone múltiples errores de parseo
        raise ParseError(f"No se pudo leer {path.name} como CSV: {exc}") from exc
    if frame.empty:
        raise ParseError(f"El archivo {path.name} no contiene filas")
    return normalize_columns(frame)


def pick(row: pd.Series | dict[str, Any], aliases: tuple[str, ...]) -> Any:
    for alias in aliases:
        if alias in row:
            value = row[alias]
            if pd.isna(value) if not isinstance(value, (list, dict)) else False:
                continue
            if isinstance(value, str) and not value.strip():
                continue
            return value
    return None


def parse_datetime(value: Any) -> datetime | None:
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return None
    try:
        parsed = pd.to_datetime(value, errors="raise", utc=True)
    except Exception:  # fecha no parseable
        return None
    return parsed.to_pydatetime()


def file_datetime(path: Path) -> datetime:
    return datetime.fromtimestamp(path.stat().st_mtime, tz=UTC)


def to_number(value: Any) -> float | int | None:
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return None
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, (int, float)):
        return value
    text = str(value).strip().replace(" ", "")
    if not text:
        return None
    if "," in text and "." not in text:
        text = text.replace(",", ".")
    try:
        number = float(text)
    except ValueError:
        return None
    if math.isnan(number) or math.isinf(number):
        return None
    return int(number) if number.is_integer() else number


def infer_protocol(*values: Any, default: str = "otro") -> str:
    """Infiere un protocolo canónico a partir de texto libre (test, archivo, columna)."""
    joined = " ".join(str(value) for value in values if value is not None)
    text = slugify(joined)
    rules: list[tuple[tuple[str, ...], str]] = [
        (("cmj", "countermovement", "sj", "squat_jump", "salto", "jump"), "salto_vertical"),
        (("horizontal", "broad"), "salto_horizontal"),
        (("gait", "marcha", "walk", "paso"), "marcha"),
        (("emg", "electromio", "muscle"), "emg"),
        (("force", "fuerza", "rfd", "isometric"), "fuerza"),
        (("balance", "equilibrio", "posturo"), "equilibrio"),
        (("rom", "movilidad", "mobility", "flexion", "range"), "movilidad"),
    ]
    for keywords, protocol in rules:
        if any(keyword in text for keyword in keywords):
            return protocol
    return default


def short_id(*parts: Any) -> str:
    digest = hashlib.sha256("|".join(str(part) for part in parts).encode("utf-8")).hexdigest()
    return digest[:16]


def source_file_reference(path: Path, anonymizer: Anonymizer) -> ArchivoReferencia:
    """Referencia al archivo original, con hash y sin PII en el nombre."""
    stem_tokens = set(slugify(path.stem).split("_"))
    from biomech_pipelines.models import PII_TOKENS  # import local: evita ciclo

    filename = path.name
    if stem_tokens & PII_TOKENS:
        filename = f"{anonymizer.pseudonym(path.stem)}{path.suffix.lower()}"
    return ArchivoReferencia(
        nombre=filename,
        tipo=path.suffix.lower().lstrip(".") or "otro",
        sha256=hash_file(path),
        tamano_bytes=path.stat().st_size,
    )


def build_session(
    *,
    source: str,
    source_path: Path,
    anonymizer: Anonymizer,
    raw_subject: Any,
    fallback_subject: str,
    date_value: Any,
    fallback_date: datetime,
    protocol: str,
    device: str,
    metrics: dict[str, Any],
    metadata: dict[str, Any] | None = None,
    series: list[Any] | None = None,
) -> SesionNormalizada:
    subject_raw = str(raw_subject).strip() if raw_subject is not None else fallback_subject
    subject = anonymizer.pseudonym(subject_raw)
    fecha = parse_datetime(date_value) or fallback_date
    fecha = anonymizer.shift_datetime(fecha, subject)
    clean_metrics = {
        key: value
        for key, value in metrics.items()
        if value is not None and not (isinstance(value, float) and math.isnan(value))
    }
    return SesionNormalizada(
        fuente=source,
        id_externo=short_id(source, subject, fecha.isoformat(), protocol),
        fecha=fecha,
        sujeto_codigo=subject,
        protocolo=protocol,
        dispositivo=device,
        metricas=clean_metrics,
        series=series or [],
        archivos=[source_file_reference(source_path, anonymizer)],
        metadata={
            "parser": source,
            "archivo": path_name_safe(source_path, anonymizer),
            **(metadata or {}),
        },
    )


def path_name_safe(path: Path, anonymizer: Anonymizer) -> str:
    stem_tokens = set(slugify(path.stem).split("_"))
    from biomech_pipelines.models import PII_TOKENS  # import local: evita ciclo

    if stem_tokens & PII_TOKENS:
        return f"{anonymizer.pseudonym(path.stem)}{path.suffix.lower()}"
    return path.name


def numeric_metrics(
    row: pd.Series,
    *,
    exclude: set[str],
) -> dict[str, float | int]:
    metrics: dict[str, float | int] = {}
    for column, value in row.items():
        key = str(column)
        if key in exclude:
            continue
        number = to_number(value)
        if number is not None:
            metrics[key] = number
    return metrics


def ensure_subject(value: str | None, path: Path) -> str:
    subject = (value or "").strip()
    if not subject:
        raise ParseError(
            f"{path.name}: falta la columna de sujeto. Indicá --subject o incluí una "
            "columna como sujeto_id / paciente_id."
        )
    return subject
