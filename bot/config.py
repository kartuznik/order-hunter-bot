from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

DEFAULT_KEYWORDS = (
    "telegram,телеграм,tg,bot,бот,python,ai,ии,нейросеть,gpt,автоматизация,"
    "парсер,скрипт,магазин,оплата,корзина,анкета,заявка,опрос"
)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    TELEGRAM_BOT_TOKEN: str = Field(default="PLACEHOLDER_TOKEN")
    NOTIFY_CHAT_IDS: str = Field(default="")

    ENABLE_FL: bool = Field(default=True)
    FL_RSS_URL: str = Field(default="https://www.fl.ru/rss/all.xml")
    ENABLE_KWORK: bool = Field(default=False)
    KWORK_PROJECTS_URL: str = Field(default="https://kwork.ru/projects")

    KEYWORDS: str = Field(default=DEFAULT_KEYWORDS)
    POLL_INTERVAL_SECONDS: int = Field(default=180)
    DB_PATH: str = Field(default="data/order_hunter.db")

    @property
    def notify_chat_ids(self) -> list[int]:
        raw = self.NOTIFY_CHAT_IDS.strip()
        if not raw:
            return []
        return [int(v.strip()) for v in raw.split(",") if v.strip()]

    @property
    def keywords(self) -> list[str]:
        raw = self.KEYWORDS.strip() or DEFAULT_KEYWORDS
        return [part.strip().lower() for part in raw.split(",") if part.strip()]

    @field_validator("POLL_INTERVAL_SECONDS")
    @classmethod
    def clamp_poll_interval(cls, value: int) -> int:
        return max(180, int(value))

    @property
    def db_file(self) -> Path:
        path = Path(self.DB_PATH)
        if not path.is_absolute():
            path = Path("/opt/bots/order-hunter-bot") / path
        path.parent.mkdir(parents=True, exist_ok=True)
        return path

    @property
    def dry_run(self) -> bool:
        token = self.TELEGRAM_BOT_TOKEN.strip()
        return not token or token.upper().startswith("PLACEHOLDER")


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
