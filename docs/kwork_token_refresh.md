# Обновление токена Kwork

Мобильный `signIn` возвращает `token` и `expired` (срок жизни в секундах). Refresh-токена в ответе нет. Пример OpenAPI: `expired` = 2592000, то есть 30 суток. Токен, записанный на этом сервере 30 сентября 2026, получил отказ `/projects` 11 октября 2026, через 11 дней. Поэтому бот предупреждает через 7 дней после записи, а не через 30.

С этого VPS `signIn` вызывать нельзя. Датацентровый IP уже получал код 105 и капчу 118. Команда выполняется на домашней машине.

## Получить токен

Нужны логин (или e-mail) и пароль. Поле `phone_last` — последние 4 цифры телефона, его API просит не всегда. `g-recaptcha-response` нужен только после ошибки 118.

```bash
curl -sS -X POST 'https://api.kwork.ru/signIn' \
  -u 'mobile_api:qFvfRl7w' \
  -H 'User-Agent: kwork-parser/0.1' \
  -H 'Content-Type: application/x-www-form-urlencoded' \
  --data-urlencode 'login=YOUR_LOGIN' \
  --data-urlencode 'password=YOUR_PASSWORD'
```

Успешный ответ выглядит так. Вместо настоящего токена подставь значение из своего ответа:

```json
{
  "success": true,
  "response": {
    "token": "TOKEN_FROM_RESPONSE",
    "expired": 2592000
  }
}
```

Если пришёл `error_code` 118, открой `http://kwork.ru/captcha_only` в браузере, возьми хвост после `#response=` и повтори запрос с `--data-urlencode 'g-recaptcha-response=ХВОСТ'`. Если API просит телефон, добавь `--data-urlencode 'phone_last=1234'`.

## Положить токен на сервер

Токен в чат и в git не отправлять. На сервере, в каталоге бота:

```bash
cd /opt/bots/order-hunter-bot
venv/bin/python scripts/manual_token_update.py 'TOKEN_FROM_RESPONSE'
```

Скрипт записывает `KWORK_TOKEN` и `KWORK_TOKEN_UPDATED_AT` в `.env`, снимает метки отказа и предупреждения и перезапускает `order-hunter-bot.service`. Значение токена он не печатает. Число `expired` датой не записывается: срок считается от `KWORK_TOKEN_UPDATED_AT`.

Команда `/kwork_token_status` в Telegram показывает, задан ли токен, его длину, дату записи и был ли отказ `/projects`. Сам токен команда не показывает.
