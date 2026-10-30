"""CLI de biomech-pipelines."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Annotated, Any

import typer

from biomech_pipelines import __version__
from biomech_pipelines.anonymize import Anonymizer, PrivacyError
from biomech_pipelines.config import settings
from biomech_pipelines.export import (
    anonymize_dataset_file,
    load_sessions,
    write_dataset,
)
from biomech_pipelines.parsers import detect_source, parse_file
from biomech_pipelines.parsers.base import ParseError

app = typer.Typer(
    name="biomech",
    help="Parsing, anonimización y exportación de datos biomecánicos del LMH.",
    no_args_is_help=True,
    add_completion=False,
)

SUPPORTED_SUFFIXES = {".csv", ".json", ".c3d", ".mp4", ".mov", ".avi", ".mkv", ".webm"}
FORMATS = {"json", "jsonl", "csv", "parquet"}


def _fail(message: str) -> typer.Exit:
    typer.secho(f"Error: {message}", fg=typer.colors.RED, err=True)
    return typer.Exit(code=1)


def _anonymizer(salt: str | None, date_shift: int | None) -> Anonymizer:
    resolved = salt or settings.anon_salt.get_secret_value()
    if not resolved:
        raise PrivacyError(
            "Falta BIOMECH_ANON_SALT. Definir la variable de entorno o pasar --salt."
        )
    return Anonymizer(
        salt=resolved,
        date_shift_days=date_shift if date_shift is not None else settings.date_shift_days,
    )


def _parse_date(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"Fecha inválida: {value}. Usar ISO 8601 (YYYY-MM-DD).") from exc


def _inputs(path: Path) -> list[Path]:
    if path.is_dir():
        files = sorted(
            candidate
            for candidate in path.rglob("*")
            if candidate.is_file() and candidate.suffix.lower() in SUPPORTED_SUFFIXES
        )
        if not files:
            raise ValueError(f"No se encontraron archivos soportados en {path}")
        return files
    return [path]


def _summarize(sessions: list[Any], output: Path) -> None:
    fuentes: dict[str, int] = {}
    for session in sessions:
        fuentes[session.fuente] = fuentes.get(session.fuente, 0) + 1
    typer.echo(f"Sesiones normalizadas: {len(sessions)}")
    typer.echo("Fuentes: " + ", ".join(f"{key}={value}" for key, value in fuentes.items()))
    typer.echo(f"Salida: {output}")
    if sessions:
        typer.echo(f"Sujetos seudonimizados: {len({s.sujeto_codigo for s in sessions})}")


@app.command()
def parse(
    input: Annotated[Path, typer.Argument(help="Archivo o directorio a procesar", exists=True)],
    output: Annotated[Path, typer.Option("--out", "-o", help="Archivo de salida")] = Path(
        "datasets/sesiones.json"
    ),
    format: Annotated[
        str, typer.Option("--format", "-f", help="json | jsonl | csv | parquet")
    ] = "json",
    source: Annotated[
        str,
        typer.Option(
            "--source",
            "-s",
            help="auto | biobit | mdurance | csv_generic | c3d | media",
        ),
    ] = "auto",
    salt: Annotated[
        str | None,
        typer.Option("--salt", help="Sal HMAC (preferir BIOMECH_ANON_SALT)"),
    ] = None,
    date_shift: Annotated[
        int | None,
        typer.Option("--date-shift", help="Días máximos de desplazamiento por sujeto"),
    ] = None,
    protocolo: Annotated[
        str | None, typer.Option("--protocol", help="Forzar protocolo canónico")
    ] = None,
    dispositivo: Annotated[
        str | None, typer.Option("--device", help="Forzar dispositivo de origen")
    ] = None,
    fecha: Annotated[str | None, typer.Option("--date", help="Forzar fecha ISO 8601")] = None,
    subject: Annotated[
        str | None, typer.Option("--subject", help="Sujeto por defecto si el archivo no lo trae")
    ] = None,
) -> None:
    """Parsea uno o varios archivos y genera un dataset normalizado."""
    if format not in FORMATS:
        raise typer.BadParameter(f"Formato inválido. Usar: {', '.join(sorted(FORMATS))}")

    try:
        anonymizer = _anonymizer(salt, date_shift)
        default_date = _parse_date(fecha)
        sessions: list[Any] = []
        files = _inputs(input)
        for path in files:
            detected = detect_source(path) if source == "auto" else source
            typer.echo(f"- {path.name} -> {detected}")
            sessions.extend(
                parse_file(
                    path,
                    anonymizer,
                    source=source,
                    protocolo=protocolo,
                    dispositivo=dispositivo,
                    fecha=default_date,
                    sujeto=subject,
                )
            )
        manifest = write_dataset(
            sessions,
            output,
            anonymizer,
            format=format,  # type: ignore[arg-type]
            filters={"source": source, "archivos": [path.name for path in files]},
        )
        _summarize(sessions, output)
        typer.echo(
            f"Manifest: {manifest.total_sesiones} sesiones · "
            f"pipeline {manifest.pipeline_version} · salt {manifest.salt_fingerprint}"
        )
    except (PrivacyError, ParseError, ValueError, OSError) as exc:
        raise _fail(str(exc)) from None


@app.command()
def anonymize(
    input: Annotated[Path, typer.Argument(help="CSV/JSON tabular a anonimizar", exists=True)],
    output: Annotated[Path, typer.Option("--out", "-o", help="Archivo de salida")] = Path(
        "datasets/anonimizado.csv"
    ),
    subject_column: Annotated[
        str | None,
        typer.Option("--subject-column", help="Columna identificadora del sujeto"),
    ] = None,
    salt: Annotated[
        str | None,
        typer.Option("--salt", help="Sal HMAC (preferir BIOMECH_ANON_SALT)"),
    ] = None,
    date_shift: Annotated[
        int | None,
        typer.Option("--date-shift", help="Días máximos de desplazamiento por sujeto"),
    ] = None,
) -> None:
    """Elimina columnas PII y seudonimiza un CSV/JSON de exportación directa."""
    try:
        anonymizer = _anonymizer(salt, date_shift)
        report = anonymize_dataset_file(
            input,
            output,
            anonymizer,
            subject_column=subject_column,
        )
        typer.echo(f"Salida: {output}")
        typer.echo(json.dumps(report.as_dict(), ensure_ascii=False, indent=2))
    except (PrivacyError, ValueError, OSError) as exc:
        raise _fail(str(exc)) from None


@app.command()
def inspect(
    input: Annotated[
        Path,
        typer.Argument(help="Dataset normalizado JSON/JSONL", exists=True),
    ],
) -> None:
    """Resume un dataset normalizado (sin necesidad de sal)."""
    try:
        sessions = load_sessions(input)
    except (ValueError, OSError) as exc:
        raise _fail(str(exc)) from None

    protocols: dict[str, int] = {}
    devices: dict[str, int] = {}
    for session in sessions:
        protocols[session.protocolo] = protocols.get(session.protocolo, 0) + 1
        devices[session.dispositivo] = devices.get(session.dispositivo, 0) + 1
    typer.echo(f"Sesiones: {len(sessions)}")
    typer.echo(f"Sujetos: {len({s.sujeto_codigo for s in sessions})}")
    typer.echo(f"Protocolos: {json.dumps(protocols, ensure_ascii=False)}")
    typer.echo(f"Dispositivos: {json.dumps(devices, ensure_ascii=False)}")
    if sessions:
        first = sessions[0]
        typer.echo(
            f"Primera sesión: {first.fecha.isoformat()} · {first.protocolo} · "
            f"{len(first.metricas)} métricas · {len(first.series)} series"
        )


@app.command()
def export(
    input: Annotated[Path, typer.Argument(help="Dataset normalizado JSON/JSONL", exists=True)],
    output: Annotated[Path, typer.Option("--out", "-o", help="Archivo de salida")] = Path(
        "datasets/export.csv"
    ),
    format: Annotated[
        str, typer.Option("--format", "-f", help="json | jsonl | csv | parquet")
    ] = "csv",
    salt: Annotated[
        str | None,
        typer.Option("--salt", help="Sal HMAC (preferir BIOMECH_ANON_SALT)"),
    ] = None,
) -> None:
    """Reexporta un dataset normalizado a otro formato con manifiesto."""
    if format not in FORMATS:
        raise typer.BadParameter(f"Formato inválido. Usar: {', '.join(sorted(FORMATS))}")
    try:
        anonymizer = _anonymizer(salt, None)
        sessions = load_sessions(input)
        write_dataset(
            sessions,
            output,
            anonymizer,
            format=format,  # type: ignore[arg-type]
            filters={"source": str(input)},
        )
        _summarize(sessions, output)
    except (PrivacyError, ValueError, OSError) as exc:
        raise _fail(str(exc)) from None


@app.command()
def version() -> None:
    """Muestra la versión instalada."""
    typer.echo(f"biomech-pipelines {__version__}")


if __name__ == "__main__":  # pragma: no cover
    app()
