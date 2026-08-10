# Order Hunter Bot (internal)

Внутренний бот для уведомлений о релевантных заказах.

## MVP scope

- FL.ru RSS (`https://www.fl.ru/rss/all.xml`) с polling каждые 180 секунд.
- Фильтр по ключевым словам из `.env`.
- Дедупликация в SQLite (повторы не отправляются).
- Уведомление в Telegram карточкой: title, цена (если найдена), ссылка, кнопка "Открыть заказ".
- Dry-run при пустом/placeholder токене: бот не падает, пишет события в stdout.

## Kwork (phase 2)

- Реализация за флагом `ENABLE_KWORK=false`.
- Страница проектов Kwork JS-driven, структура HTML может меняться; стабильный парсинг не гарантирован в MVP.

## Запуск

```bash
cd /opt/bots/order-hunter-bot
python3 -m venv venv
venv/bin/pip install -r requirements.txt
cp .env.example .env
venv/bin/python -m bot.main
```

## Systemd

Юнит: `/etc/systemd/system/order-hunter-bot.service`.

```bash
systemctl daemon-reload
systemctl enable order-hunter-bot
systemctl start order-hunter-bot
systemctl status order-hunter-bot
```

## Live-check уведомлений

```bash
venv/bin/python scripts/live_check.py
```

## Ограничения и вежливость к площадкам

- Интервал опроса не короче 180 секунд.
- Нет агрессивных обходов и high-frequency scraping.
- Нет автооткликов: человек в цикле, бот только уведомляет.
