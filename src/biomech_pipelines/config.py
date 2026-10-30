"""Configuración del pipeline, cargada desde variables de entorno."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="BIOMECH_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    anon_salt: SecretStr = SecretStr("")
    date_shift_days: int = Field(default=0, ge=0, le=3650)
    output_dir: Path = Path("datasets")
    max_file_mb: int = Field(default=2048, ge=1)
    pipeline_version: str = "0.1.0"

    @property
    def has_salt(self) -> bool:
        return bool(self.anon_salt.get_secret_value())


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
