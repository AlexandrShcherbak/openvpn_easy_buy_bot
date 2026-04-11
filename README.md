# WireGuard VPN Telegram Bot

Готовая базовая структура для продажи VPN-подписок через Telegram и WireGuard Easy API.

## Возможности
- Регистрация пользователя в Telegram-боте.
- Покупка/активация подписки.
- Генерация WireGuard-конфига по шаблону и выдача `.conf` + QR-кода.
- Оплата через FreeKassa, Platega, SeverPay, CryptoCloud, CrystalPay, CryptoBot, DonationAlerts, Boosty и СБП (ручная).
- Команда `/howto` с краткой инструкцией по подключению.
- Webhook-интеграции для Crypto Bot / донатов / Sendler.
- Простая админ-панель (`/admin`) со статистикой.
- Базовые юридические документы для банковской проверки: политика, соглашение, контакты.

## Стек
- `aiogram` (бот)
- `SQLAlchemy` + `SQLite` (хранилище)
- `aiohttp` (интеграция с WireGuard Easy API)

## Быстрый старт
1. Создайте `.env` в корне проекта:
   ```env
   BOT_TOKEN=...
   # Можно указать одного админа:
   ADMIN_ID=123456789
   # или список:
   ADMIN_IDS=[123456789]
   DATABASE_URL=sqlite+aiosqlite:///./vpn_bot.db

   WIREGUARD_API_URL=https://your-wg-easy-domain
   WIREGUARD_API_TOKEN=your_api_token
   WIREGUARD_SERVER_PUBLIC_KEY=server_public_key
   WIREGUARD_SERVER_ENDPOINT=1.2.3.4:51820

   SUPPORT_CONTACT=support@example.com
   SUPPORT_EMAIL=support@example.com
   OWNER_CONTACT=owner@example.com
   TELEGRAM_BOT_URL=https://t.me/wireguard_easy_buy_bot

   # Платежи
   FREEKASSA_SHOP_ID=
   FREEKASSA_SECRET_WORD_1=
   FREEKASSA_SECRET_WORD_2=
   PLATEGA_BASE_URL=
   PLATEGA_SHOP_ID=
   PLATEGA_API_KEY=
   PLATEGA_CREATE_INVOICE_PATH=/transaction/process
   PLATEGA_SUCCESS_URL=
   SEVERPAY_MID=
   SEVERPAY_TOKEN=
   CRYPTOCLOUD_API_KEY=
   CRYSTALPAY_BASE_URL=
   CRYSTALPAY_TOKEN=
   CRYPTOBOT_TOKEN=
   DONATIONALERTS_TOKEN=
   DONATIONALERTS_BASE_URL=
   BOOSTY_BASE_URL=

   # Webhook сервер (для callback от Sendler/донатов/CryptoBot)
   SENDLER_WEBHOOK_ENABLED=true
   SENDLER_WEBHOOK_HOST=0.0.0.0
   SENDLER_WEBHOOK_PORT=8080
   SENDLER_WEBHOOK_SECRET=super-secret
   ```
2. Установите зависимости:
   ```bash
   pip install -r requirements.txt
   ```
3. Запустите из корня репозитория:
   ```bash
   python main.py
   ```


### Почему `main.py` не читает `.env` напрямую
`main.py` только запускает приложение (`asyncio.run(main())`). Настройки читаются внутри модулей через `config.settings`/`config.config`, например в `bot/bot_instance.py` и `bot/handlers/*`. Это нормальная схема: точка входа минимальная, а конфигурация загружается там, где используется.

Поддерживаются оба файла переменных: `.env` и `env` в корне проекта. Загрузка выполняется встроенным парсером (`KEY=VALUE`) и не требует `python-dotenv`.

> Важно: переменные `WG_CONFIG_PATH` и `WG_INTERFACE` в текущей версии кода не используются — интеграция построена через `WIREGUARD_API_*` и параметры сервера (`WIREGUARD_SERVER_*`).

## Структура проекта
- `main.py` — корневая точка входа (запуск приложения).
- `bot/` — пакет Telegram-бота (handlers, keyboards, middleware, внутренняя точка входа `bot.main`).
- `database/` — модели и CRUD.
- `wireguard/` — генерация WireGuard-конфигов и manager.
- `integrations/` — слой внешних интеграций (пока заглушки для платежей и WireGuard API).
- `scripts/` — запуск/деплой/бэкапы.

### Почему `main.py` был внутри `bot/`
`bot/` — это Python-пакет с кодом приложения, поэтому `bot/main.py` удобно использовать как модульную точку входа (`python -m bot.main`).

Чтобы не путаться с запуском из разных директорий, добавлена корневая точка входа `main.py`.
Теперь рекомендованный способ — всегда запускать из корня:

```bash
python main.py
```

## Webhook endpoints
- `POST /webhooks/cryptobot` — успешные события оплаты Crypto Bot.
- `POST /webhooks/donation` — подтверждение рублёвой оплаты от донат-сервиса.
- `POST /webhooks/sendler` — лиды/события из Sendler.
- `POST /webhooks/platega` — callback от Platega (статусы `CONFIRMED/CANCELED/CHARGEBACK`).

## Важно
- Для безопасности включайте `SENDLER_WEBHOOK_SECRET` и проверяйте секрет в webhook-запросах.
- Для части платежных провайдеров статус подтверждается вручную поддержкой.
- Для Platega укажите в личном кабинете callback URL вида `https://<ваш-домен>/webhooks/platega`.
- Цена подписки по умолчанию — `600 ₽` (`DEFAULT_PLAN_PRICE_RUB=600`).

## Юридические документы
- Политика конфиденциальности: `legal/privacy-policy.md`
- Пользовательское соглашение: `legal/terms-of-service.md`
- Контакты владельца/поддержки: `legal/contacts.md`
