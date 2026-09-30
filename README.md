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
- Токен мобильного API ротируется вручную примерно раз в 30 дней. `signIn` с VPS закрыт: датацентровый IP получает капчу. В коде `signIn` нет. Пустой токен — подсказка обновить его с домашней машины. Если до `KWORK_TOKEN_EXPIRES` меньше 72 часов, владельцу уходит одно сообщение и не повторяется, пока срок в `.env` не сменят.
- Источник `kwork_api`, бейдж `KWORK_API`. Склейка с каналом IMAP на полке: один и тот же проект может прийти и из почты, и из API.
- В проде читается только первая страница. На зонде 30 Sep 2026 страница вмещала 12 проектов при `total=401` и `pages=34`. Если между тиками проектов больше, чем влезает на страницу, хвост в уведомления не попадёт.
- `/wantsStatusList` не используется: в OpenAPI это вкладки статусов покупателя, не лента биржи.

| Факт | Значение | Откуда |
|---|---|---|
| Auth | HTTP Basic мобильного клиента + `token` в query после `POST /signIn` | sabraman `src/kwork/api.rs`, OpenAPI pykwork |
| Цель | `POST /projects`, первая страница | OpenAPI pykwork, `get_projects` |
| Ссылка карточки | `https://kwork.ru/projects/{id}` | `bot/kwork_html.py`, тот же шаблон у API-карточки |
| User-Agent, принятый `/projects` | `kwork-parser/0.1` | тот же запрос. `signIn` этим UA с VPS токен не получил |
| Единицы `date_confirm` | unix-секунды | 12 значений на странице, все в прошлом относительно epoch зонда |
| Единицы `time_left` | секунды до закрытия, не unix | min 82211, max 258836 (около 23 ч – 3 суток). В OpenAPI поле названо UNIX, живые числа так не выглядят |

Коды `error_code`, которые есть в исходниках. Кода 105 среди них нет.

| Код | Что написано в источнике | Где |
|---|---|---|
| 100 | Пример общей ошибки: «Недостаточно параметров для метода API» | pykwork `docs/openapi.json`, схема `error` |
| 101 | «Некорректные значения параметров» у `/getWebAuthToken` | pykwork `docs/openapi.json`, описание `/getWebAuthToken` |
| 118 | Капча `signIn`: webview `http://kwork.ru/captcha_only` | pykwork `docs/openapi.json`, описание `/signIn` |
| 151 | Пустой список `workerOrders`, не ошибка для остановки пагинации | sabraman `src/kwork/api.rs`, `get_worker_orders` |
| 159 | Нет email у соцаккаунта, нужен `socialSignUp` | pykwork `docs/openapi.json`, `socialSignIn` |
| 160 | Соцаккаунт с таким email уже есть | pykwork `docs/openapi.json`, `socialSignUp` |
| 401, 403 | Повод один раз обновить токен, если код пришёл в JSON | sabraman `src/kwork/api.rs`, `post` |

В `source/kwork/api.py` числовые коды не разобраны: при `success=false` клиент бросает текст поля `error`. Каталога `issues/` в клонах нет. У sabraman на GitHub issues 0. У pykwork 30 issues, в них нет «105», «error code» и «signIn»; рядом по смыслу только текст капчи и просьба ввести последние 4 цифры телефона, без номера кода.

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
