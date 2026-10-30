"""Pruebas de anonimización y privacidad."""

from __future__ import annotations

from datetime import UTC, datetime

import pandas as pd
import pytest

from biomech_pipelines.anonymize import (
    Anonymizer,
    PrivacyError,
    anonymize_frame,
    strip_pii,
)
from biomech_pipelines.models import SesionNormalizada


def test_pseudonimo_estable_y_dependiente_de_sal() -> None:
    first = Anonymizer("salt-aaaaaaaaaaaaaaaa")
    second = Anonymizer("salt-bbbbbbbbbbbbbbbb")
    assert first.pseudonym("LMH-001") == first.pseudonym("lmh-001")
    assert first.pseudonym("LMH-001") != second.pseudonym("LMH-001")
    assert first.pseudonym("LMH-001").startswith("lmh-")
    assert len(first.pseudonym("LMH-001")) == 20


def test_sal_corta_es_rechazada() -> None:
    with pytest.raises(PrivacyError):
        Anonymizer("corta")


def test_desplazamiento_de_fechas_preserva_determinismo() -> None:
    anonymizer = Anonymizer("salt-cccccccccccccccc", date_shift_days=30)
    reference = datetime(2026, 10, 24, tzinfo=UTC)
    shifted = anonymizer.shift_datetime(reference, "lmh-abc")
    assert abs((shifted - reference).days) <= 30
    assert shifted == anonymizer.shift_datetime(reference, "lmh-abc")


def test_anonimiza_dataframe() -> None:
    frame = pd.DataFrame(
        {
            "paciente_id": ["LMH-001", "LMH-002"],
            "nombre_paciente": ["Ana", "Bruno"],
            "email": ["ana@example.com", "bruno@example.com"],
            "fecha": ["2026-10-24", "2026-10-25"],
            "altura_salto_cm": [34.2, 35.1],
        }
    )
    anonymizer = Anonymizer("salt-dddddddddddddddd", date_shift_days=10)
    clean, report = anonymize_frame(frame, anonymizer)

    assert "nombre_paciente" not in clean.columns
    assert "email" not in clean.columns
    assert clean["paciente_id"].iloc[0].startswith("lmh-")
    assert "paciente_id" in report.pseudonymized_columns
    assert set(report.dropped_columns) == {"nombre_paciente", "email"}
    assert report.rows == 2


def test_sesion_rechaza_pii_en_metricas() -> None:
    with pytest.raises(ValueError):
        SesionNormalizada(
            fuente="test",
            id_externo="1",
            fecha=datetime.now(UTC),
            sujeto_codigo="lmh-123",
            protocolo="salto_vertical",
            dispositivo="Test",
            metricas={"nombre": "Ana"},
        )


def test_strip_pii_anidado() -> None:
    cleaned = strip_pii(
        {
            "paciente": {"nombre": "Ana", "deporte": "running"},
            "metricas": {"altura": 30, "email": "ana@example.com"},
        }
    )
    assert cleaned == {
        "paciente": {"deporte": "running"},
        "metricas": {"altura": 30},
    }
