from __future__ import annotations

from pathlib import Path
from typing import Any, ClassVar, Tuple, Type

from pydantic_settings import BaseSettings, JsonConfigSettingsSource, PydanticBaseSettingsSource, SettingsConfigDict

CONFIG_DIR = Path.home() / ".config" / "apple-music-tui"
CONFIG_FILE = CONFIG_DIR / "config.json"


class AppConfig(BaseSettings):
    theme: str = "textual-dark"

    model_config: ClassVar[SettingsConfigDict] = SettingsConfigDict(
        env_prefix="APPLE_MUSIC_TUI_",
        json_file=str(CONFIG_FILE),
        json_file_encoding="utf-8",
    )

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: Type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> Tuple[PydanticBaseSettingsSource, ...]:
        return (init_settings, env_settings, JsonConfigSettingsSource(settings_cls))

    def save(self) -> None:
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        CONFIG_FILE.write_text(self.model_dump_json(indent=2), encoding="utf-8")


def load_config() -> AppConfig:
    try:
        return AppConfig()
    except Exception:
        return AppConfig.model_construct(theme="textual-dark")
