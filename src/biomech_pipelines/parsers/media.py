"""Metadatos de video MP4/MOV mediante `ffprobe` (opcional)."""

from __future__ import annotations

import contextlib
import json
import shutil
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Any

from biomech_pipelines.anonymize import Anonymizer
from biomech_pipelines.models import SesionNormalizada
from biomech_pipelines.parsers.base import build_session, file_datetime


def _probe(path: Path) -> dict[str, Any] | None:
    executable = shutil.which("ffprobe")
    if executable is None:
        return None
    try:
        completed = subprocess.run(
            [
                executable,
                "-v",
                "error",
                "-print_format",
                "json",
                "-show_format",
                "-show_streams",
                str(path),
            ],
            capture_output=True,
            text=True,
            timeout=20,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if completed.returncode != 0 or not completed.stdout.strip():
        return None
    try:
        return json.loads(completed.stdout)
    except json.JSONDecodeError:
        return None


def _frame_rate(value: str | None) -> float | None:
    if not value or "/" not in value:
        return None
    numerator, _, denominator = value.partition("/")
    try:
        rate = float(numerator) / float(denominator)
    except (ValueError, ZeroDivisionError):
        return None
    return round(rate, 3) if rate > 0 else None


def parse(
    path: Path,
    anonymizer: Anonymizer,
    *,
    protocolo: str | None = None,
    dispositivo: str | None = None,
    fecha: datetime | None = None,
    sujeto: str | None = None,
) -> list[SesionNormalizada]:
    probe = _probe(path)
    metrics: dict[str, Any] = {
        "tamano_mb": round(path.stat().st_size / (1024 * 1024), 2),
    }
    metadata: dict[str, Any] = {
        "formato_export": "media",
        "ffprobe_disponible": probe is not None,
    }

    if probe:
        format_info = probe.get("format") or {}
        duration = format_info.get("duration")
        if duration is not None:
            with contextlib.suppress(TypeError, ValueError):
                metrics["duracion_s"] = round(float(duration), 2)
        video = next(
            (stream for stream in probe.get("streams", []) if stream.get("codec_type") == "video"),
            None,
        )
        if video:
            for key, metric in (("width", "ancho_px"), ("height", "alto_px")):
                if video.get(key):
                    metrics[metric] = int(video[key])
            fps = _frame_rate(video.get("avg_frame_rate") or video.get("r_frame_rate"))
            if fps:
                metrics["frecuencia_muestreo_hz"] = fps
            if video.get("codec_name"):
                metadata["codec"] = str(video["codec_name"])

    return [
        build_session(
            source="media",
            source_path=path,
            anonymizer=anonymizer,
            raw_subject=sujeto,
            fallback_subject=path.stem,
            date_value=fecha,
            fallback_date=file_datetime(path),
            protocol=protocolo or "otro",
            device=dispositivo or "Cámara",
            metrics=metrics,
            metadata=metadata,
        )
    ]
