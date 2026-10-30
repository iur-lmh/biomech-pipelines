"""Aplanado, manifiestos y exportación de datasets."""

from __future__ import annotations

import json
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

import pandas as pd

from biomech_pipelines.anonymize import (
    AnonymizationReport,
    Anonymizer,
    anonymize_frame,
)
from biomech_pipelines.config import settings
from biomech_pipelines.models import (
    DatasetExport,
    DatasetManifest,
    SesionNormalizada,
)

ExportFormat = Literal["json", "jsonl", "csv", "parquet"]


def flatten_session(session: SesionNormalizada) -> dict[str, Any]:
    """Una fila por sesión; métricas y series con prefijos estables."""
    row: dict[str, Any] = {
        "id_externo": session.id_externo,
        "fuente": session.fuente,
        "fecha": session.fecha.isoformat(),
        "sujeto_codigo": session.sujeto_codigo,
        "protocolo": session.protocolo,
        "dispositivo": session.dispositivo,
        "schema_version": session.schema_version,
        "n_series": len(session.series),
        "n_archivos": len(session.archivos),
    }
    for key, value in session.metricas.items():
        row[f"metrica_{key}"] = value
    for index, serie in enumerate(session.series):
        prefix = f"serie_{serie.canal}"
        row[f"{prefix}_n"] = len(serie.valores)
        row[f"{prefix}_unidad"] = serie.unidad
        row[f"{prefix}_frecuencia_hz"] = serie.frecuencia_hz
        row[f"{prefix}_primero"] = serie.valores[0]
        row[f"{prefix}_ultimo"] = serie.valores[-1]
        row[f"{prefix}_indice"] = index
    for index, archivo in enumerate(session.archivos):
        row[f"archivo_{index}_nombre"] = archivo.nombre
        row[f"archivo_{index}_tipo"] = archivo.tipo
        row[f"archivo_{index}_sha256"] = archivo.sha256
        row[f"archivo_{index}_bytes"] = archivo.tamano_bytes
    row["metadata_json"] = json.dumps(session.metadata, ensure_ascii=False, sort_keys=True)
    return row


def sessions_frame(sessions: list[SesionNormalizada]) -> pd.DataFrame:
    return pd.DataFrame([flatten_session(session) for session in sessions])


def build_manifest(
    sessions: list[SesionNormalizada],
    anonymizer: Anonymizer,
    *,
    filters: dict[str, Any] | None = None,
) -> DatasetManifest:
    sources = Counter(session.fuente for session in sessions)
    return DatasetManifest(
        pipeline_version=settings.pipeline_version,
        generated_at=datetime.now(UTC),
        total_sesiones=len(sessions),
        fuentes=dict(sources),
        filtros=filters or {},
        salt_fingerprint=anonymizer.salt_fingerprint,
    )


def write_dataset(
    sessions: list[SesionNormalizada],
    output: Path,
    anonymizer: Anonymizer,
    *,
    format: ExportFormat = "json",
    filters: dict[str, Any] | None = None,
) -> DatasetManifest:
    output.parent.mkdir(parents=True, exist_ok=True)
    manifest = build_manifest(sessions, anonymizer, filters=filters)

    if format == "json":
        payload = DatasetExport(manifest=manifest, items=sessions)
        output.write_text(
            payload.model_dump_json(indent=2),
            encoding="utf-8",
        )
    elif format == "jsonl":
        with output.open("w", encoding="utf-8") as handle:
            for session in sessions:
                handle.write(session.model_dump_json())
                handle.write("\n")
        _write_manifest(manifest, output)
    elif format == "csv":
        sessions_frame(sessions).to_csv(output, index=False)
        _write_manifest(manifest, output)
    elif format == "parquet":
        try:
            sessions_frame(sessions).to_parquet(output, index=False)
        except ImportError as exc:  # pragma: no cover - depende del entorno
            raise ImportError(
                "Parquet requiere pyarrow. Instalar con: pip install 'biomech-pipelines[parquet]'"
            ) from exc
        _write_manifest(manifest, output)
    else:  # pragma: no cover - Literal protege en tipos, validación para runtime
        raise ValueError(f"Formato de exportación no soportado: {format}")

    return manifest


def _write_manifest(manifest: DatasetManifest, output: Path) -> None:
    manifest_path = output.with_suffix(f"{output.suffix}.manifest.json")
    manifest_path.write_text(manifest.model_dump_json(indent=2), encoding="utf-8")


def load_sessions(path: Path) -> list[SesionNormalizada]:
    """Carga un dataset normalizado en JSON, JSONL o CSV aplanado."""
    suffix = path.suffix.lower()
    if suffix == ".jsonl":
        sessions: list[SesionNormalizada] = []
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                sessions.append(SesionNormalizada.model_validate_json(line))
        return sessions

    if suffix == ".json":
        payload = json.loads(path.read_text(encoding="utf-8"))
        items = payload.get("items") if isinstance(payload, dict) else payload
        if not isinstance(items, list):
            raise ValueError(f"{path.name}: se esperaba una lista o un objeto con 'items'")
        return [SesionNormalizada.model_validate(item) for item in items]

    raise ValueError(
        f"{path.name}: para reexportar usar JSON/JSONL normalizado, no CSV. "
        "El CSV aplanado pierde la estructura de series."
    )


def anonymize_dataset_file(
    input_path: Path,
    output_path: Path,
    anonymizer: Anonymizer,
    *,
    subject_column: str | None = None,
) -> AnonymizationReport:
    """Anonimiza un CSV/JSON tabular de exportación directa."""
    suffix = input_path.suffix.lower()
    if suffix == ".csv":
        frame = pd.read_csv(input_path)
    elif suffix == ".json":
        payload = json.loads(input_path.read_text(encoding="utf-8"))
        items = payload.get("items") if isinstance(payload, dict) else payload
        if not isinstance(items, list):
            raise ValueError(f"{input_path.name}: se esperaba una lista de registros")
        frame = pd.DataFrame(items)
    else:
        raise ValueError("La anonimización directa admite CSV o JSON")

    clean, report = anonymize_frame(
        frame,
        anonymizer,
        subject_column=subject_column,
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    if output_path.suffix.lower() == ".json":
        output_path.write_text(
            json.dumps(
                {"report": report.as_dict(), "items": clean.to_dict(orient="records")},
                ensure_ascii=False,
                indent=2,
                default=str,
            ),
            encoding="utf-8",
        )
    else:
        clean.to_csv(output_path, index=False)
    return report


__all__ = [
    "ExportFormat",
    "anonymize_dataset_file",
    "build_manifest",
    "flatten_session",
    "load_sessions",
    "sessions_frame",
    "write_dataset",
]
