"""Pruebas de adaptadores de archivos."""

from __future__ import annotations

import json
import struct
from datetime import UTC, datetime
from pathlib import Path

import pytest

from biomech_pipelines.anonymize import Anonymizer
from biomech_pipelines.parsers import detect_source, parse_file
from biomech_pipelines.parsers.base import ParseError
from biomech_pipelines.parsers.c3d import read_header


def test_detecta_formatos(fixtures_dir: Path, tmp_path: Path, anonymizer: Anonymizer) -> None:
    assert detect_source(fixtures_dir / "biobit_ejemplo.csv") == "biobit"
    assert detect_source(fixtures_dir / "mdurance_ejemplo.csv") == "mdurance"
    assert detect_source(fixtures_dir / "generico_tidy.csv") == "csv_generic"
    assert detect_source(fixtures_dir / "generico_ancho.csv") == "csv_generic"

    c3d_path = _make_c3d(tmp_path / "sesion.c3d")
    assert detect_source(c3d_path) == "c3d"
    assert detect_source(tmp_path / "video.mp4") == "media"

    with pytest.raises(ParseError):
        detect_source(tmp_path / "datos.xlsx")


def test_biobit(fixtures_dir: Path, anonymizer: Anonymizer) -> None:
    sessions = parse_file(fixtures_dir / "biobit_ejemplo.csv", anonymizer)
    assert len(sessions) == 2
    first = sessions[0]
    assert first.fuente == "biobit"
    assert first.protocolo == "salto_vertical"
    assert first.dispositivo == "Biobit"
    assert first.sujeto_codigo.startswith("lmh-")
    assert first.metricas["altura_salto_cm"] == 34.2
    assert first.metricas["tiempo_vuelo_ms"] == 512
    assert "LMH-001" not in first.model_dump_json()


def test_mdurance_infiere_cmj(fixtures_dir: Path, anonymizer: Anonymizer) -> None:
    sessions = parse_file(fixtures_dir / "mdurance_ejemplo.csv", anonymizer)
    assert len(sessions) == 2
    assert all(session.protocolo == "salto_vertical" for session in sessions)
    assert sessions[0].metricas["jump_height_cm"] == 38.4
    assert sessions[0].metadata["test_original"] == "CMJ"


def test_generico_tidy_agrupa_metricas(fixtures_dir: Path, anonymizer: Anonymizer) -> None:
    sessions = parse_file(fixtures_dir / "generico_tidy.csv", anonymizer)
    assert len(sessions) == 1
    session = sessions[0]
    assert session.protocolo == "marcha"
    assert session.metricas["cadencia_pasos_min"] == 112
    assert session.metricas["velocidad_m_s"] == 1.41
    assert session.metadata["unidades"]["cadencia_pasos_min"] == "pasos/min"
    assert session.metadata["formato_export"] == "tidy_long"


def test_c3d_cabecera(tmp_path: Path, anonymizer: Anonymizer) -> None:
    path = _make_c3d(tmp_path / "marcha.c3d")
    header = read_header(path)
    assert header.n_points == 24
    assert header.n_frames == 100
    assert header.frame_rate == 100.0

    sessions = parse_file(
        path,
        anonymizer,
        fecha=datetime(2026, 10, 20, tzinfo=UTC),
    )
    assert len(sessions) == 1
    assert sessions[0].protocolo == "movilidad"
    assert sessions[0].metricas["puntos_3d"] == 24
    assert sessions[0].metadata["solo_cabecera"] is True


def test_media_sin_ffprobe(
    tmp_path: Path, anonymizer: Anonymizer, monkeypatch: pytest.MonkeyPatch
) -> None:
    import biomech_pipelines.parsers.media as media

    path = tmp_path / "video.mp4"
    path.write_bytes(b"\x00" * 2048)
    monkeypatch.setattr(media, "_probe", lambda _: None)

    sessions = media.parse(path, anonymizer)
    assert len(sessions) == 1
    assert sessions[0].metadata["ffprobe_disponible"] is False
    assert sessions[0].metricas["tamano_mb"] == 0.0


def test_generico_ancho(fixtures_dir: Path, anonymizer: Anonymizer) -> None:
    sessions = parse_file(fixtures_dir / "generico_ancho.csv", anonymizer)
    assert len(sessions) == 1
    session = sessions[0]
    assert session.protocolo == "salto_vertical"
    assert session.metricas["salto_altura_cm"] == 38.4
    assert session.dispositivo == "Manual"


def test_mdurance_json(tmp_path: Path, anonymizer: Anonymizer) -> None:
    path = tmp_path / "mdurance.json"
    path.write_text(
        json.dumps(
            {
                "sessions": [
                    {
                        "Athlete": "LMH-010",
                        "Date": "2026-10-21T10:00:00Z",
                        "Test": "Gait",
                        "Cadence": 110,
                        "Speed": 1.32,
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    sessions = parse_file(path, anonymizer)
    assert len(sessions) == 1
    assert sessions[0].fuente == "mdurance"
    assert sessions[0].protocolo == "marcha"
    assert sessions[0].metricas["cadence"] == 110


def test_media_con_ffprobe_simulado(
    tmp_path: Path, anonymizer: Anonymizer, monkeypatch: pytest.MonkeyPatch
) -> None:
    import biomech_pipelines.parsers.media as media

    path = tmp_path / "video.mp4"
    path.write_bytes(b"\x00" * 1024)
    monkeypatch.setattr(
        media,
        "_probe",
        lambda _: {
            "format": {"duration": "12.5"},
            "streams": [
                {
                    "codec_type": "video",
                    "width": 1920,
                    "height": 1080,
                    "avg_frame_rate": "30/1",
                    "codec_name": "h264",
                }
            ],
        },
    )
    sessions = media.parse(path, anonymizer)
    assert sessions[0].metricas["duracion_s"] == 12.5
    assert sessions[0].metricas["ancho_px"] == 1920
    assert sessions[0].metricas["frecuencia_muestreo_hz"] == 30.0
    assert sessions[0].metadata["codec"] == "h264"


def test_c3d_invalido(tmp_path: Path, anonymizer: Anonymizer) -> None:
    path = tmp_path / "roto.c3d"
    path.write_bytes(b"\x00" * 600)
    with pytest.raises(ParseError):
        read_header(path)


def test_archivo_inexistente(anonymizer: Anonymizer, tmp_path: Path) -> None:
    with pytest.raises(ParseError):
        parse_file(tmp_path / "no-existe.csv", anonymizer)


def _make_c3d(path: Path) -> Path:
    header = struct.pack(
        "<HHHHHHfHHf",
        1,  # parameter block
        24,  # points
        0,  # analog channels
        1,  # first frame
        100,  # last frame
        0,  # max gap
        0.5,  # scale
        2,  # data start block
        0,  # analog samples per frame
        100.0,  # frame rate
    )
    path.write_bytes(header + b"\x00" * (512 - len(header)) + b"\x00" * 256)
    return path
