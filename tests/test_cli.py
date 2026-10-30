"""Pruebas de la CLI."""

from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from biomech_pipelines.cli import app

SALT = "test-salt-with-more-than-16-characters"
runner = CliRunner()


def test_parse_y_inspect(fixtures_dir: Path, tmp_path: Path) -> None:
    output = tmp_path / "sesiones.json"
    result = runner.invoke(
        app,
        [
            "parse",
            str(fixtures_dir / "biobit_ejemplo.csv"),
            "--out",
            str(output),
            "--salt",
            SALT,
        ],
    )
    assert result.exit_code == 0, result.output
    assert output.exists()
    assert "Sesiones normalizadas: 2" in result.output

    inspect = runner.invoke(app, ["inspect", str(output)])
    assert inspect.exit_code == 0, inspect.output
    assert "Sesiones: 2" in inspect.output
    assert "salto_vertical" in inspect.output


def test_parse_sin_sal(fixtures_dir: Path, tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv("BIOMECH_ANON_SALT", raising=False)
    result = runner.invoke(
        app,
        [
            "parse",
            str(fixtures_dir / "biobit_ejemplo.csv"),
            "--out",
            str(tmp_path / "x.json"),
        ],
    )
    assert result.exit_code == 1
    assert "BIOMECH_ANON_SALT" in result.output


def test_export_csv(fixtures_dir: Path, tmp_path: Path) -> None:
    dataset = tmp_path / "sesiones.json"
    parse = runner.invoke(
        app,
        [
            "parse",
            str(fixtures_dir / "generico_tidy.csv"),
            "--out",
            str(dataset),
            "--salt",
            SALT,
        ],
    )
    assert parse.exit_code == 0, parse.output

    output = tmp_path / "export.csv"
    result = runner.invoke(
        app,
        ["export", str(dataset), "--out", str(output), "--format", "csv", "--salt", SALT],
    )
    assert result.exit_code == 0, result.output
    assert output.exists()
    assert "metrica_cadencia_pasos_min" in output.read_text(encoding="utf-8")


def test_anonymize_cli(tmp_path: Path) -> None:
    source = tmp_path / "raw.csv"
    source.write_text(
        "sujeto_id,nombre,email,valor\nLMH-1,Ana,ana@example.com,10\n",
        encoding="utf-8",
    )
    output = tmp_path / "clean.csv"
    result = runner.invoke(
        app,
        ["anonymize", str(source), "--out", str(output), "--salt", SALT],
    )
    assert result.exit_code == 0, result.output
    start = result.output.index("{")
    report = json.loads(result.output[start:])
    assert report["dropped_columns"] == ["nombre", "email"]


def test_version() -> None:
    result = runner.invoke(app, ["version"])
    assert result.exit_code == 0
    assert "biomech-pipelines" in result.output
