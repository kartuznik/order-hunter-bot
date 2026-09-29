# Order Hunter Bot (internal)

Внутренний бот для уведомлений о релевантных заказах.

## MVP scope

- Kwork email notifications через IMAP-поллер (приоритетный источник, если настроен).
- FL.ru RSS (`https://www.fl.ru/rss/all.xml`) с polling каждые 180 секунд.
- Фильтр качества по схеме core+secondary:
  - минимум 1 совпадение из ядра (`bot/бот/telegram/телеграм/tg`)
  - минимум 1 совпадение из вторичных терминов
  - block-list имеет приоритет и отсекает сразу.
- Дедупликация в SQLite (повторы не отправляются).
- Уведомление в Telegram карточкой: title, цена (если найдена), ссылка, кнопка "Открыть заказ".
- Dry-run при пустом/placeholder токене: бот не падает, пишет события в stdout.

## Kwork (phase 2)

- Приоритетный канал Kwork: IMAP-письма из уведомлений Kwork (`ENABLE_KWORK_IMAP`).
- HTML-парсер Kwork остаётся резервным и выключен по умолчанию (`ENABLE_KWORK=false`).
- Страница проектов Kwork JS-driven, структура HTML может меняться; стабильный парсинг не гарантирован.
- Ссылка и в HTML-заглушке, и в карточке мобильного API собирается одним шаблоном: `https://kwork.ru/projects/{id}`.

## Kwork mobile API

Неофициальное мобильное JSON API `https://api.kwork.ru`. Kwork может изменить или отключить его без предупреждения.

Контракт снят с открытых репозиториев [sabraman/kwork-parser](https://github.com/sabraman/kwork-parser) и [kesha1225/pykwork](https://github.com/kesha1225/pykwork). Живой веб Kwork для этого не использовался.

Решения:

- Свой тонкий клиент на уже стоящем `aiohttp`. Пакет pykwork не подключаем.
- Поллинг внутри текущего процесса order-hunter, со своим таймером. База 5 минут плюс случайные 30–90 секунд. Это единственная страховка от бана: прокси и запасные аккаунты не используются.
- Источник `kwork_api`, бейдж `KWORK_API`. Склейка с каналом IMAP на полке: один и тот же проект может прийти и из почты, и из API.
- В проде читается только первая страница. Если между тиками проектов больше, чем влезает на неё, хвост в уведомления не попадёт.
- `/wantsStatusList` не используется: в OpenAPI это вкладки статусов покупателя, не лента биржи.

| Факт | Значение | Откуда |
|---|---|---|
| Auth | HTTP Basic мобильного клиента + `token` в query после `POST /signIn` | sabraman `src/kwork/api.rs`, OpenAPI pykwork |
| Цель | `POST /projects`, первая страница | OpenAPI pykwork, `get_projects` |
| Ссылка карточки | `https://kwork.ru/projects/{id}` | `bot/kwork_html.py`, тот же шаблон у API-карточки |
| User-Agent, принятый `signIn` | не снят | зонд не выполнен: `KWORK_PASSWORD` в `.env` пустой |
| Единицы `date_confirm` | не сняты | тот же зонд |
| Единицы `time_left` | не сняты | тот же зонд |

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

После merge этой ветки юнит не меняется, `daemon-reload` не нужен. На сервере:

```bash
cd /opt/bots/order-hunter-bot
git pull
systemctl restart order-hunter-bot.service
systemctl status order-hunter-bot.service
journalctl -u order-hunter-bot -n 50
```

## Live-check уведомлений

```bash
venv/bin/python scripts/live_check.py
venv/bin/python scripts/live_check_fl.py
venv/bin/python scripts/live_check_kwork.py
```

## Telegram команда

- `/stats` — отдает текущие счетчики цикла.
- Доступ ограничен chat-id из `NOTIFY_CHAT_IDS`.

## Ограничения и вежливость к площадкам

- Интервал опроса не короче 180 секунд.
- Нет агрессивных обходов и high-frequency scraping.
- Нет автооткликов: человек в цикле, бот только уведомляет.
