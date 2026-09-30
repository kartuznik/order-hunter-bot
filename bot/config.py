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

GREEN_WEIGHTS: dict[str, int] = {
    "python": 3,
    "питон": 3,
    "пайтон": 3,
    "aiogram": 3,
    "fastapi": 3,
    "django": 3,
    "flask": 3,
    "pydantic": 3,
    "asyncio": 3,
    "telethon": 3,
    "pyrogram": 3,
    "ai": 3,
    "llm": 3,
    "openai": 2,
    "chatgpt": 2,
    "gpt": 2,
    "claude": 2,
    "anthropic": 2,
    "telegram": 2,
    "телеграм": 2,
    "телега": 2,
    "тг": 2,
    "бот": 2,
    "bot": 2,
    "чат-бот": 2,
    "чатбот": 2,
    "автобот": 2,
    "парсер": 2,
    "парсинг": 2,
    "скрапинг": 2,
    "скрейпинг": 2,
    "scraping": 2,
    "crawler": 2,
    "краулер": 2,
    "автоматизация": 2,
    "автоматизировать": 2,
    "импорт": 2,
    "экспорт": 2,
    "миграция": 2,
    "etl": 2,
    "обработка данных": 2,
    "backend": 1,
    "бэкенд": 1,
    "бекенд": 1,
    "api": 1,
    "веб-сервис": 1,
    "микросервис": 1,
    "rest": 1,
    "grpc": 1,
    "webhook": 1,
    "вебхук": 1,
    "интеграция": 1,
    "sqlite": 1,
    "postgresql": 1,
    "postgres": 1,
    "redis": 1,
    "база данных": 1,
    "docker": 1,
    "docker-compose": 1,
    "systemd": 1,
    "nginx": 1,
    "linux": 1,
    "сервер": 1,
    "vps": 1,
    "deploy": 1,
    "деплой": 1,
    "ci/cd": 1,
    "github actions": 1,
    "yookassa": 1,
    "юкасса": 1,
    "платежи": 1,
    "подписка": 1,
    "оплата": 1,
    "биллинг": 1,
    "админка": 1,
    "админ панель": 1,
    "панель управления": 1,
    "crud": 1,
    "json": 1,
    "csv": 1,
    "excel": 1,
    "xml": 1,
    "celery": 1,
    "apscheduler": 1,
    "логирование": 1,
    "мониторинг": 1,
    "pytest": 1,
    "unittest": 1,
    "тестирование": 1,
}

GREEN_SCORE_THRESHOLD = 3

RED_KEYWORDS: tuple[str, ...] = (
    "salebot",
    "n8n",
    "make",
    "zapier",
    "airtable",
    "bubble",
    "retool",
    "react",
    "vue",
    "angular",
    "frontend",
    "фронтенд",
    "mini app",
    "tma",
    "telegram mini app",
    "wordpress",
    "joomla",
    "bitrix",
    "modx",
    "laravel",
    "php",
    "nodejs",
    "javascript",
    "flutter",
    "ios",
    "android",
    "mobile app",
    "kotlin",
    "swift",
    "модерация чата",
    "поддержка",
    "smm",
    "seo",
    "контекст",
    "таргет",
    "копирайтинг",
    "дизайн",
    "логотип",
    "верстка",
    "figma",
    "unity",
    "unreal",
    "game dev",
    "геймдев",
    "data science",
    "ml",
    "machine learning",
    "deep learning",
    "1с",
    "битрикс24",
    "amo crm",
    "wordpress плагин",
    "опыт 3+ года",
    "middle+",
    "senior",
    "team lead",
    "офис",
    "гибрид",
)

GRAY_KEYWORDS: tuple[str, ...] = (
    "ai-ассистент",
    "llm",
    "openai",
    "chatgpt",
    "gpt",
    "docker-compose",
    "kubernetes",
    "срочно",
    "завтра",
    "вчера",
    "за 2 дня",
)

BUDGET_DROP_RUB = 2000
GRAY_BUDGET_RUB = 3000
MODULE_DROP_COUNT = 5
MODULE_DROP_BUDGET_RUB = 10000
GRAY_MODULE_COUNT = 3
DEADLINE_DROP_DAYS = 2
TITLE_REPEAT_DAYS = 7


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
