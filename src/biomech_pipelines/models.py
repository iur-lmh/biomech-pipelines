"""Modelo canónico y contrato de datos de las sesiones biomecánicas."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

PII_KEYS = {
    "nombre",
    "nombres",
    "apellido",
    "apellidos",
    "dni",
    "documento",
    "email",
    "correo",
    "telefono",
    "teléfono",
    "direccion",
    "dirección",
    "fecha_nacimiento",
    "birthdate",
    "phone",
    "address",
}
PII_TOKENS = {
    "nombre",
    "apellido",
    "dni",
    "documento",
    "email",
    "correo",
    "telefono",
    "direccion",
    "nacimiento",
    "birth",
    "phone",
    "address",
}


def _key_tokens(key: str) -> set[str]:
    normalized = (
        key.strip()
        .lower()
        .replace("á", "a")
        .replace("é", "e")
        .replace("í", "i")
        .replace("ó", "o")
        .replace("ú", "u")
        .replace("ñ", "n")
    )
    for separator in ("-", ".", "/", "\\"):
        normalized = normalized.replace(separator, "_")
    return {token for token in normalized.split("_") if token}


def contains_pii(value: Any, *, strict: bool = False) -> bool:
    """Detecta claves de identificación personal en estructuras anidadas.

    En modo estricto, cualquier token de una clave compuesta se considera PII
    (por ejemplo `nombre_paciente`). En modo laxo solo se comparan claves exactas.
    """
    if isinstance(value, dict):
        for key, nested in value.items():
            normalized = str(key).strip().lower()
            tokens = _key_tokens(str(key))
            if normalized in PII_KEYS or (strict and tokens & PII_TOKENS):
                return True
            if contains_pii(nested, strict=strict):
                return True
    elif isinstance(value, list):
        return any(contains_pii(item, strict=strict) for item in value)
    return False


class SerieTemporal(BaseModel):
    canal: str = Field(min_length=1, max_length=80)
    unidad: str | None = Field(default=None, max_length=24)
    frecuencia_hz: float | None = Field(default=None, gt=0)
    valores: list[float] = Field(min_length=1)

    model_config = ConfigDict(extra="forbid")


class ArchivoReferencia(BaseModel):
    nombre: str = Field(min_length=1, max_length=255)
    tipo: str = Field(min_length=1, max_length=16)
    sha256: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")
    tamano_bytes: int | None = Field(default=None, ge=0)

    model_config = ConfigDict(extra="forbid")


class SesionNormalizada(BaseModel):
    """Una sesión de medición lista para almacenarse o exportarse."""

    schema_version: str = "1.0"
    fuente: str = Field(min_length=1, max_length=40)
    id_externo: str = Field(min_length=1, max_length=120)
    fecha: datetime
    sujeto_codigo: str = Field(min_length=1, max_length=64)
    protocolo: str = Field(min_length=1, max_length=60)
    dispositivo: str = Field(min_length=1, max_length=80)
    metricas: dict[str, float | int | str | bool | None] = Field(default_factory=dict)
    series: list[SerieTemporal] = Field(default_factory=list)
    archivos: list[ArchivoReferencia] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)

    model_config = ConfigDict(extra="forbid")

    @field_validator("fecha")
    @classmethod
    def normalizar_fecha(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value.astimezone(UTC)

    @model_validator(mode="after")
    def validar_privacidad(self) -> SesionNormalizada:
        if contains_pii(self.metricas):
            raise ValueError("metricas contiene claves de identificación personal")
        if contains_pii(self.metadata):
            raise ValueError("metadata contiene claves de identificación personal")
        return self

    def metrica(self, nombre: str) -> float | int | str | bool | None:
        return self.metricas.get(nombre)


class DatasetManifest(BaseModel):
    dataset_version: str = "1.0"
    pipeline_version: str
    generated_at: datetime
    total_sesiones: int
    fuentes: dict[str, int] = Field(default_factory=dict)
    filtros: dict[str, Any] = Field(default_factory=dict)
    salt_fingerprint: str
    schema_version: str = "1.0"


class DatasetExport(BaseModel):
    manifest: DatasetManifest
    items: list[SesionNormalizada]
