from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

DEFAULT_CORE_KEYWORDS = "bot,бот,telegram,телеграм,tg"
DEFAULT_SECONDARY_KEYWORDS = (
    "python,ai,ии,gpt,автоматизация,парсер,скрипт,магазин,оплата,корзина,анкета,заявка,опрос,рассылка"
)
DEFAULT_NEGATIVE_KEYWORDS = (
    "дизайн,логотип,баннер,иллюстрац,презентац,3d,3д,архитектур,инженер,смет,чертеж,"
    "овик,вк,вышивк,перевод,копирайт,рерайт,smm,таргет,seo,контекст,авито,фотограф,"
    "музык,диктор,тендер,android,андроид,ios,мобильн,сайт,лендинг"
)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    TELEGRAM_BOT_TOKEN: str = Field(default="PLACEHOLDER_TOKEN")
    NOTIFY_CHAT_IDS: str = Field(default="")

    ENABLE_KWORK_IMAP: bool = Field(default=True)
    IMAP_HOST: str = Field(default="")
    IMAP_PORT: int = Field(default=993)
    IMAP_USERNAME: str = Field(default="")
    IMAP_APP_PASSWORD: str = Field(default="")
    IMAP_FOLDER: str = Field(default="INBOX")
    KWORK_EMAIL_FROM: str = Field(default="mail@kwork.ru")
    KWORK_EMAIL_SUBJECT_HINT: str = Field(default="")

    ENABLE_KWORK: bool = Field(default=False)
    KWORK_PROJECTS_URL: str = Field(default="https://kwork.ru/projects")
    KWORK_TOKEN: str = Field(default="")

    CORE_KEYWORDS: str = Field(default=DEFAULT_CORE_KEYWORDS)
    SECONDARY_KEYWORDS: str = Field(default=DEFAULT_SECONDARY_KEYWORDS)
    NEGATIVE_KEYWORDS: str = Field(default=DEFAULT_NEGATIVE_KEYWORDS)
    POLL_INTERVAL_SECONDS: int = Field(default=180)
    DB_PATH: str = Field(default="data/order_hunter.db")

    @property
    def notify_chat_ids(self) -> list[int]:
        raw = self.NOTIFY_CHAT_IDS.strip()
        if not raw:
            return []
        return [int(v.strip()) for v in raw.split(",") if v.strip()]

    @property
    def core_keywords(self) -> list[str]:
        raw = self.CORE_KEYWORDS.strip() or DEFAULT_CORE_KEYWORDS
        return [part.strip().lower() for part in raw.split(",") if part.strip()]

    @property
    def secondary_keywords(self) -> list[str]:
        raw = self.SECONDARY_KEYWORDS.strip() or DEFAULT_SECONDARY_KEYWORDS
        return [part.strip().lower() for part in raw.split(",") if part.strip()]

    @property
    def negative_keywords(self) -> list[str]:
        raw = self.NEGATIVE_KEYWORDS.strip() or DEFAULT_NEGATIVE_KEYWORDS
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

    @property
    def kwork_token(self) -> str:
        return self.KWORK_TOKEN.strip()

    @property
    def imap_ready(self) -> bool:
        return (
            bool(self.IMAP_HOST.strip())
            and bool(self.IMAP_USERNAME.strip())
            and bool(self.IMAP_APP_PASSWORD.strip())
        )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
