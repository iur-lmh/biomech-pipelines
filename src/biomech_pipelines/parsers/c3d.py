"""Lectura de cabecera C3D (sin decodificar señales).

El formato C3D es binario y propietario en su capa de parámetros. Esta primera versión
extrae metadatos de la cabecera para catalogar el archivo. La decodificación de puntos
3D y canales analógicos se incorporará con `ezc3d` en la fase 1.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from biomech_pipelines.anonymize import Anonymizer
from biomech_pipelines.models import SesionNormalizada
from biomech_pipelines.parsers.base import ParseError, build_session, file_datetime


@dataclass(frozen=True)
class C3DHeader:
    parameter_block: int
    n_points: int
    n_analog: int
    first_frame: int
    last_frame: int
    max_gap: int
    scale_factor: float
    data_start_block: int
    analog_samples_per_frame: int
    frame_rate: float
    byte_order: str

    @property
    def n_frames(self) -> int:
        return max(0, self.last_frame - self.first_frame + 1)


def read_header(path: Path) -> C3DHeader:
    if path.stat().st_size < 512:
        raise ParseError(f"{path.name}: archivo demasiado pequeño para una cabecera C3D")
    with path.open("rb") as handle:
        payload = handle.read(512)

    candidates: list[C3DHeader] = []
    for byte_order in ("<", ">"):
        try:
            (
                parameter_block,
                n_points,
                n_analog,
                first_frame,
                last_frame,
                max_gap,
                scale_factor,
                data_start_block,
                analog_samples,
                frame_rate,
            ) = struct.unpack(f"{byte_order}HHHHHHfHHf", payload[:24])
        except struct.error:  # pragma: no cover - protección defensiva
            continue
        if not (0 < frame_rate <= 100_000):
            continue
        if not (0 <= n_points <= 10_000):
            continue
        if parameter_block <= 0 or data_start_block <= 0:
            continue
        candidates.append(
            C3DHeader(
                parameter_block=parameter_block,
                n_points=n_points,
                n_analog=n_analog,
                first_frame=first_frame,
                last_frame=last_frame,
                max_gap=max_gap,
                scale_factor=scale_factor,
                data_start_block=data_start_block,
                analog_samples_per_frame=analog_samples,
                frame_rate=frame_rate,
                byte_order="little-endian" if byte_order == "<" else "big-endian",
            )
        )

    if not candidates:
        raise ParseError(f"{path.name}: cabecera C3D inválida o no reconocida")
    return candidates[0]


def parse(
    path: Path,
    anonymizer: Anonymizer,
    *,
    protocolo: str | None = None,
    dispositivo: str | None = None,
    fecha: datetime | None = None,
    sujeto: str | None = None,
) -> list[SesionNormalizada]:
    header = read_header(path)
    metrics: dict[str, Any] = {
        "puntos_3d": header.n_points,
        "canales_analogicos": header.n_analog,
        "frecuencia_muestreo_hz": round(header.frame_rate, 3),
        "frames": header.n_frames,
        "muestras_analogicas_por_frame": header.analog_samples_per_frame,
        "escala": round(header.scale_factor, 6),
    }
    return [
        build_session(
            source="c3d",
            source_path=path,
            anonymizer=anonymizer,
            raw_subject=sujeto,
            fallback_subject=path.stem,
            date_value=fecha,
            fallback_date=file_datetime(path),
            protocol=protocolo or "movilidad",
            device=dispositivo or "C3D",
            metrics=metrics,
            metadata={
                "formato_export": "c3d",
                "solo_cabecera": True,
                "byte_order": header.byte_order,
                "primer_frame": header.first_frame,
                "ultimo_frame": header.last_frame,
            },
        )
    ]
