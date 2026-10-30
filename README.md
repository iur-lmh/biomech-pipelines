# biomech-pipelines — ingeniería de datos biomecánicos

CLI y biblioteca para **parsear exportaciones heterogéneas**, normalizarlas a un modelo
canónico y generar **datasets seudonimizados** listos para R, Python o la API de LabOS.

Pertenece al ecosistema del **Laboratorio de Movimiento Humano (IUR — UCASAL)**.

## Instalación

```bash
python -m venv .venv
. .venv/Scripts/activate        # Windows
# source .venv/bin/activate     # Linux/macOS

pip install -e ".[dev]"
cp .env.example .env
```

Generar una sal y guardarla en `.env`:

```bash
python -c "import secrets; print(secrets.token_urlsafe(32))"
```

```env
BIOMECH_ANON_SALT=<sal-de-32-bytes>
```

La sal **nunca** se versiona ni se incluye en los datasets. Rotarla invalida la
correlación histórica entre exportaciones.

## Uso rápido

```bash
# Inspeccionar formatos (detecta automáticamente el adaptador)
biomech parse examples/biobit_ejemplo.csv --out datasets/sesiones.json

# Exportar CSV aplanado + manifiesto
biomech parse examples/mdurance_ejemplo.csv --format csv --out datasets/mdurance.csv

# Procesar un directorio completo
biomech parse ./exports --out datasets/lote.json

# Resumen del dataset normalizado
biomech inspect datasets/sesiones.json

# Anonimizar una exportación tabular directa
biomech anonymize raw/export.csv --out datasets/anon.csv

# Reexportar a Parquet (requiere extra)
pip install -e ".[parquet]"
biomech export datasets/sesiones.json --format parquet --out datasets/sesiones.parquet
```

Opciones útiles:

| Opción | Descripción |
|---|---|
| `--source biobit\|mdurance\|csv_generic\|c3d\|media` | Forzar adaptador |
| `--protocol salto_vertical` | Forzar protocolo |
| `--device Biobit` | Forzar dispositivo |
| `--date 2026-10-24` | Forzar fecha si el archivo no la trae |
| `--subject LMH-001` | Sujeto por defecto si falta la columna |
| `--date-shift 30` | Desplazar fechas por sujeto (máx. 30 días) |
| `--salt` | Pasar sal por CLI (preferir variable de entorno) |

## Formatos soportados

| Formato | Detección | Estado | Notas |
|---|---|---|---|
| CSV Biobit | columnas `paciente_id`, `altura_salto_cm`… | Base | Métricas numéricas → `metricas` |
| CSV/JSON mDurance | columnas `Athlete`, `Test`, `Date` | Base | Infiere CMJ/SJ/marcha |
| CSV tidy | columnas `metrica`, `valor` | Estable | Agrupa por sujeto/fecha/protocolo |
| CSV ancho genérico | resto de CSV | Estable | Detección automática |
| C3D | `.c3d` | Cabecera | Puntos, frames, fps, escala; sin señales |
| MP4/MOV | `.mp4`, `.mov`… | Metadatos | Requiere `ffprobe`; degrada si no está |
| JSON mDurance | `.json` | Base | Lista o `{sessions: [...]}` |

> Los adaptadores propietarios se validan contra muestras reales antes de usarse en
> producción. Los nombres de columnas se normalizan a snake_case ASCII.

## Modelo canónico

```json
{
  "schema_version": "1.0",
  "fuente": "biobit",
  "id_externo": "a1b2c3d4e5f60718",
  "fecha": "2026-10-24T14:30:00Z",
  "sujeto_codigo": "lmh-7f3a92c1b4e5d6f7",
  "protocolo": "salto_vertical",
  "dispositivo": "Biobit",
  "metricas": {
    "altura_salto_cm": 34.2,
    "tiempo_vuelo_ms": 512,
    "pico_fuerza_n": 1820
  },
  "series": [
    {
      "canal": "fuerza_n",
      "unidad": "N",
      "frecuencia_hz": 1000,
      "valores": [0, 12.4, 88.1]
    }
  ],
  "archivos": [
    {
      "nombre": "salto_cmj.c3d",
      "tipo": "c3d",
      "sha256": "…64 hex…",
      "tamano_bytes": 2845100
    }
  ],
  "metadata": {"parser": "biobit", "formato_export": "biobit_csv"}
}
```

Protocolos canónicos: `salto_vertical`, `salto_horizontal`, `marcha`, `emg`, `fuerza`,
`equilibrio`, `movilidad`, `otro`.

## Privacidad

- **Seudonimización determinista** con `HMAC-SHA256(sal, id_sujeto)`; nunca SHA-256 simple.
- Eliminación de columnas PII (`nombre`, `apellido`, `dni`, `email`, `teléfono`,
  `dirección`, `fecha_nacimiento`).
- El modelo valida que `metricas` y `metadata` no contengan claves PII.
- Los nombres de archivo con tokens PII se reemplazan por seudónimos.
- Desplazamiento de fechas opcional por sujeto, preservando intervalos.
- El manifiesto incluye `salt_fingerprint` (primeros 8 hex del hash de la sal), no la sal.
- Los datasets de ejemplo son sintéticos.

> En Argentina, la Ley 25.326 considera los datos de salud sensibles. La seudonimización
> reduce el riesgo pero no reemplaza el consentimiento informado ni la evaluación ética.

## Salidas

| Formato | Archivo | Manifiesto |
|---|---|---|
| `json` | Envelope `{manifest, items}` | Incluido |
| `jsonl` | Una sesión por línea | `.manifest.json` |
| `csv` | Una fila por sesión, métricas con prefijo `metrica_` | `.manifest.json` |
| `parquet` | DataFrame aplanado | `.manifest.json` |

El manifiesto informa versión del pipeline, fecha, total, fuentes, filtros, fingerprint de
sal y versión de esquema.

## Integración con LabOS

1. El pipeline normaliza y anonimiza la exportación.
2. El archivo original + Parquet/CSV se sube a R2/S3.
3. Se registra la evaluación en `labos-core` con `datos_raw` (métricas y resumen de
   series) y el adjunto con URL + SHA-256.
4. La mesa de I+D de `labos-web` consume `/api/v1/investigaciones/dataset`.

## Calidad

```bash
ruff check .
ruff format --check .
mypy src
pytest --cov=biomech_pipelines
```

## Limitaciones actuales

- C3D solo lee cabecera; la decodificación de señales llegará con `ezc3d`.
- Los adaptadores de Biobit/mDurance son base y requieren validación con exports reales.
- No se procesan videos (solo metadatos con `ffprobe`).
- La anonimización directa trabaja sobre CSV/JSON tabulares, no sobre texto libre.
- No hay cola de trabajos: el CLI es sincrónico.

## Licencia

MIT.
