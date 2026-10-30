"""Pruebas de aplanado, manifiestos y exportación."""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

from biomech_pipelines.anonymize import Anonymizer
from biomech_pipelines.export import (
    anonymize_dataset_file as anonymize_file,
)
from biomech_pipelines.export import (
    flatten_session,
    load_sessions,
    sessions_frame,
    write_dataset,
)
from biomech_pipelines.parsers import parse_file


def _sessions(fixtures_dir: Path, anonymizer: Anonymizer):
    return parse_file(fixtures_dir / "biobit_ejemplo.csv", anonymizer)


def test_flatten_y_dataframe(fixtures_dir: Path, anonymizer: Anonymizer) -> None:
    sessions = _sessions(fixtures_dir, anonymizer)
    row = flatten_session(sessions[0])
    assert row["metrica_altura_salto_cm"] == 34.2
    assert row["sujeto_codigo"].startswith("lmh-")
    assert "metadata_json" in row
    frame = sessions_frame(sessions)
    assert len(frame) == 2
    assert frame["protocolo"].unique().tolist() == ["salto_vertical"]


def test_export_json_con_manifiesto(
    fixtures_dir: Path, anonymizer: Anonymizer, tmp_path: Path
) -> None:
    sessions = _sessions(fixtures_dir, anonymizer)
    output = tmp_path / "dataset.json"
    manifest = write_dataset(sessions, output, anonymizer, format="json")

    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["manifest"]["total_sesiones"] == 2
    assert payload["manifest"]["salt_fingerprint"] == anonymizer.salt_fingerprint
    assert len(payload["items"]) == 2
    assert manifest.pipeline_version == "0.1.0"

    loaded = load_sessions(output)
    assert len(loaded) == 2
    assert loaded[0].sujeto_codigo == sessions[0].sujeto_codigo


def test_export_csv_y_jsonl(fixtures_dir: Path, anonymizer: Anonymizer, tmp_path: Path) -> None:
    sessions = _sessions(fixtures_dir, anonymizer)
    csv_path = tmp_path / "dataset.csv"
    write_dataset(sessions, csv_path, anonymizer, format="csv")
    frame = pd.read_csv(csv_path)
    assert len(frame) == 2
    assert "metrica_altura_salto_cm" in frame.columns
    assert csv_path.with_suffix(".csv.manifest.json").exists()

    jsonl_path = tmp_path / "dataset.jsonl"
    write_dataset(sessions, jsonl_path, anonymizer, format="jsonl")
    lines = jsonl_path.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 2
    assert json.loads(lines[0])["fuente"] == "biobit"


def test_export_formato_invalido(
    fixtures_dir: Path, anonymizer: Anonymizer, tmp_path: Path
) -> None:
    sessions = _sessions(fixtures_dir, anonymizer)
    with pytest.raises(ValueError):
        write_dataset(sessions, tmp_path / "x.xml", anonymizer, format="xml")  # type: ignore[arg-type]


def test_anonimiza_csv_directo(tmp_path: Path, anonymizer: Anonymizer) -> None:
    source = tmp_path / "export.csv"
    source.write_text(
        "paciente_id,nombre,email,fecha,altura\nLMH-100,Ana,ana@example.com,2026-10-01,30\n",
        encoding="utf-8",
    )
    output = tmp_path / "anon.csv"
    report = anonymize_file(source, output, anonymizer)
    frame = pd.read_csv(output)
    assert "nombre" not in frame.columns
    assert "email" not in frame.columns
    assert frame["paciente_id"].iloc[0].startswith("lmh-")
    assert report.dropped_columns == ["nombre", "email"]


def test_anonimiza_json_directo(tmp_path: Path, anonymizer: Anonymizer) -> None:
    source = tmp_path / "export.json"
    source.write_text(
        json.dumps(
            [
                {
                    "sujeto_id": "LMH-200",
                    "nombre": "Bruno",
                    "fecha": "2026-10-01",
                    "metrica": 12,
                }
            ]
        ),
        encoding="utf-8",
    )
    output = tmp_path / "anon.json"
    anonymize_file(source, output, anonymizer)
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["report"]["rows"] == 1
    assert payload["items"][0]["sujeto_id"].startswith("lmh-")
    assert "nombre" not in payload["items"][0]
