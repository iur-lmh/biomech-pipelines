"""Anonimización y seudonimización reproducible.

La sal se custodia en el gestor de secretos (`BIOMECH_ANON_SALT`). Sin sal no se
exporta ningún dato identificable.
"""

from __future__ import annotations

import hashlib
import hmac
import re
import unicodedata
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import pandas as pd

from biomech_pipelines.models import PII_KEYS, PII_TOKENS

SUBJECT_COLUMNS = (
    "sujeto_id",
    "paciente_id",
    "patient_id",
    "athlete",
    "atleta",
    "subject",
    "subject_id",
    "id_sujeto",
    "id_paciente",
)

DATE_COLUMNS = ("fecha", "fecha_hora", "fecha_evaluacion", "date", "timestamp", "datetime")


class PrivacyError(ValueError):
    """La operación requeriría exportar datos sin seudonimizar."""


def _normalize_token(value: str) -> str:
    decomposed = unicodedata.normalize("NFKD", value)
    return "".join(char for char in decomposed if not unicodedata.combining(char)).lower()


def _column_tokens(column: str) -> set[str]:
    normalized = re.sub(r"[^a-z0-9]+", "_", _normalize_token(str(column)))
    return {token for token in normalized.split("_") if token}


@dataclass(frozen=True)
class Anonymizer:
    salt: str
    date_shift_days: int = 0

    def __post_init__(self) -> None:
        if len(self.salt) < 16:
            raise PrivacyError(
                "BIOMECH_ANON_SALT debe tener al menos 16 caracteres. "
                'Generar con: python -c "import secrets; print(secrets.token_urlsafe(32))"'
            )

    def pseudonym(self, value: str) -> str:
        """Seudónimo estable y dependiente de la sal (HMAC-SHA256)."""
        cleaned = value.strip().lower()
        if not cleaned:
            raise PrivacyError("No se puede seudonimizar un identificador vacío")
        digest = hmac.new(
            self.salt.encode("utf-8"),
            cleaned.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()
        return f"lmh-{digest[:16]}"

    def shift_datetime(self, value: datetime, subject: str) -> datetime:
        """Desplaza la fecha de forma determinista por sujeto, preservando intervalos."""
        if self.date_shift_days == 0:
            return value
        digest = hmac.new(
            self.salt.encode("utf-8"),
            f"date:{subject}".encode(),
            hashlib.sha256,
        ).digest()
        offset = int.from_bytes(digest[:4], "big") % (2 * self.date_shift_days + 1)
        offset -= self.date_shift_days
        return value + timedelta(days=offset)

    @property
    def salt_fingerprint(self) -> str:
        return hashlib.sha256(self.salt.encode("utf-8")).hexdigest()[:8]

    @classmethod
    def from_salt(cls, salt: str, date_shift_days: int = 0) -> Anonymizer:
        return cls(salt=salt, date_shift_days=date_shift_days)


def hash_file(path: Path, chunk_size: int = 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(chunk_size), b""):
            digest.update(chunk)
    return digest.hexdigest()


@dataclass
class AnonymizationReport:
    dropped_columns: list[str] = field(default_factory=list)
    pseudonymized_columns: list[str] = field(default_factory=list)
    shifted_date_columns: list[str] = field(default_factory=list)
    rows: int = 0

    def as_dict(self) -> dict[str, Any]:
        return {
            "rows": self.rows,
            "dropped_columns": self.dropped_columns,
            "pseudonymized_columns": self.pseudonymized_columns,
            "shifted_date_columns": self.shifted_date_columns,
        }


def _is_pii_column(column: str) -> bool:
    normalized = _normalize_token(str(column)).strip()
    if normalized in PII_KEYS:
        return True
    tokens = _column_tokens(column)
    return bool(tokens & PII_TOKENS)


def _find_subject_column(columns: Iterable[str]) -> str | None:
    normalized = {str(column).strip().lower(): str(column) for column in columns}
    for candidate in SUBJECT_COLUMNS:
        if candidate in normalized:
            return normalized[candidate]
    return None


def anonymize_frame(
    frame: pd.DataFrame,
    anonymizer: Anonymizer,
    *,
    subject_column: str | None = None,
    strict: bool = True,
) -> tuple[pd.DataFrame, AnonymizationReport]:
    """Elimina PII, seudonimiza el sujeto y desplaza fechas de un DataFrame."""
    result = frame.copy()
    report = AnonymizationReport(rows=len(result))
    subject = subject_column or _find_subject_column(result.columns)

    if subject and subject in result.columns:
        result[subject] = result[subject].map(
            lambda value: (
                anonymizer.pseudonym(str(value))
                if pd.notna(value) and str(value).strip()
                else value
            )
        )
        report.pseudonymized_columns.append(subject)

    protected = set(report.pseudonymized_columns)
    dropped: list[str] = []
    for column in list(result.columns):
        if column in protected:
            continue
        if _is_pii_column(str(column)):
            dropped.append(str(column))
    if dropped:
        result = result.drop(columns=dropped)
        report.dropped_columns = dropped

    if anonymizer.date_shift_days > 0:
        for column in result.columns:
            normalized = _normalize_token(str(column))
            if not any(token in normalized for token in DATE_COLUMNS):
                continue
            parsed = pd.to_datetime(result[column], errors="coerce", utc=True)
            if parsed.isna().all():
                continue
            subject_values = (
                result[subject].astype(str)
                if subject and subject in result.columns
                else pd.Series([str(index) for index in result.index])
            )
            shifted = [
                anonymizer.shift_datetime(value.to_pydatetime(), subject_value)
                if pd.notna(value)
                else value
                for value, subject_value in zip(parsed, subject_values, strict=False)
            ]
            result[column] = shifted
            report.shifted_date_columns.append(str(column))

    return result, report


def strip_pii(value: Any, *, strict: bool = False) -> Any:
    """Devuelve una copia recursiva sin claves de identificación personal."""
    if isinstance(value, dict):
        cleaned: dict[str, Any] = {}
        for key, nested in value.items():
            normalized = str(key).strip().lower()
            if normalized in PII_KEYS:
                continue
            if strict and _column_tokens(str(key)) & PII_TOKENS:
                continue
            cleaned[str(key)] = strip_pii(nested, strict=strict)
        return cleaned
    if isinstance(value, list):
        return [strip_pii(item, strict=strict) for item in value]
    return value
