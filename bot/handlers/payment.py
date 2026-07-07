import hashlib
import hmac
import json

from aiohttp import web
from aiogram import Router
from sqlalchemy import or_, select

from bot.bot_instance import bot
from bot.services.subscription_delivery import activate_and_deliver_subscription
from config.config import settings
from database.crud import get_payment, get_subscription, mark_payment_paid
from database.db import SessionLocal

router = Router(name='payment_router')


def _extract_payment_id_from_order_id(order_id: str | None) -> int | None:
    if not order_id:
        return None
    # Формат payload: subscription:{subscription_id}:payment:{payment_id}
    if ":payment:" not in order_id:
        return None
    try:
        return int(order_id.rsplit(":payment:", 1)[-1])
    except ValueError:
        return None


async def _deliver_or_fallback(user_id: int, subscription) -> None:
    """Автовыдача конфига после оплаты. Если пул пуст/ошибка — уведомляем
    пользователя и админов, чтобы выдали вручную."""
    try:
        await activate_and_deliver_subscription(bot, user_id, subscription)
    except Exception:
        support_contact = getattr(settings, "support_contact", "@support_bot")
        await bot.send_message(
            user_id,
            "✅ Оплата подтверждена.\n\n"
            f"🤖 Перейдите в Telegram-бот: {settings.telegram_bot_url}\n"
            "📩 Отправьте чек в личные сообщения поддержки, чтобы получить конфигурацию и QR-код.\n"
            f"Контакт поддержки: {support_contact}"
        )
        for admin_id in settings.admin_ids:
            await bot.send_message(
                admin_id,
                "⚠️ Не удалось автоматически выдать конфиг после оплаты "
                f"пользователю {user_id} (пул пуст или ошибка генерации). Выдайте вручную.",
            )


async def cryptobot_webhook(request: web.Request) -> web.Response:
    payload = await request.json()
    update = payload.get('update', {})
    if update.get('status') != 'paid':
        return web.json_response({'ok': True})

    invoice_id = str(update.get('invoice_id', ''))
    async with SessionLocal() as session:
        from database.models.payment import Payment

        payment = (
            await session.execute(
                select(Payment).where(Payment.provider == 'cryptobot', Payment.provider_payment_id == invoice_id)
            )
        ).scalar_one_or_none()

        if not payment or payment.status == 'paid':
            return web.json_response({'ok': True})

        subscription = await get_subscription(session, payment.subscription_id)
        user_id = payment.user.telegram_id
        await mark_payment_paid(session, payment.id, invoice_id)

    if subscription:
        await _deliver_or_fallback(user_id, subscription)

    return web.json_response({'ok': True})


async def donation_webhook(request: web.Request) -> web.Response:
    if settings.sendler_webhook_secret:
        secret = request.headers.get('X-Webhook-Secret')
        if secret != settings.sendler_webhook_secret:
            return web.json_response({'ok': False, 'error': 'unauthorized'}, status=401)

    payload = await request.json()
    payment_id = int(payload.get('payment_id', 0))

    async with SessionLocal() as session:
        payment = await get_payment(session, payment_id)
        if not payment:
            return web.json_response({'ok': False, 'error': 'payment_not_found'}, status=404)

        if payment.status == 'paid':
            return web.json_response({'ok': True})

        subscription = await get_subscription(session, payment.subscription_id)
        await mark_payment_paid(session, payment.id, str(payload.get('transaction_id', payment_id)))
        user_id = payment.user.telegram_id

    if subscription:
        await _deliver_or_fallback(user_id, subscription)

    return web.json_response({'ok': True})


async def sendler_webhook(request: web.Request) -> web.Response:
    if settings.sendler_webhook_secret:
        secret = request.headers.get('X-Sendler-Secret')
        if secret != settings.sendler_webhook_secret:
            return web.json_response({'ok': False, 'error': 'unauthorized'}, status=401)

    payload = await request.json()
    event = payload.get('event', 'unknown')
    contact = payload.get('contact', {})
    text = (
        '📥 <b>Sendler webhook</b>\n'
        f'Событие: <code>{event}</code>\n'
        f'Имя: {contact.get("name", "-")}\n'
        f'Телефон: {contact.get("phone", "-")}\n'
        f'Email: {contact.get("email", "-")}'
    )

    for admin_id in settings.admin_ids:
        await bot.send_message(admin_id, text)

    return web.json_response({'ok': True})


async def platega_webhook(request: web.Request) -> web.Response:
    incoming_merchant_id = request.headers.get('X-MerchantId')
    incoming_secret = request.headers.get('X-Secret')
    if incoming_merchant_id != settings.platega_shop_id or incoming_secret != settings.platega_api_key:
        return web.json_response({'ok': False, 'error': 'unauthorized'}, status=401)

    payload = await request.json()
    status = str(payload.get('status', '')).upper()
    if status not in {'CONFIRMED', 'CANCELED', 'CHARGEBACK'}:
        return web.json_response({'ok': True})

    transaction_id = str(
        payload.get('transaction_id')
        or payload.get('invoice_id')
        or payload.get('id')
        or ''
    )
    order_id = str(payload.get('order_id') or payload.get('payload') or '')
    internal_payment_id = _extract_payment_id_from_order_id(order_id)

    async with SessionLocal() as session:
        from database.models.payment import Payment

        payment = None
        if internal_payment_id:
            payment = await get_payment(session, internal_payment_id)

        if not payment and transaction_id:
            payment = (
                await session.execute(
                    select(Payment).where(
                        Payment.provider == 'platega',
                        or_(Payment.provider_payment_id == transaction_id, Payment.provider_payment_id == order_id),
                    )
                )
            ).scalar_one_or_none()

        if not payment:
            return web.json_response({'ok': True})

        if status == 'CONFIRMED':
            if payment.status == 'paid':
                return web.json_response({'ok': True})
            subscription = await get_subscription(session, payment.subscription_id)
            await mark_payment_paid(session, payment.id, transaction_id or order_id or payment.provider_payment_id)
            user_id = payment.user.telegram_id
        else:
            payment.status = 'canceled'
            await session.commit()
            return web.json_response({'ok': True})

    if subscription:
        await _deliver_or_fallback(user_id, subscription)

    return web.json_response({'ok': True})


def _verify_severpay_signature(payload: dict, token: str) -> bool:
    """HMAC-SHA256 по документации SeverPay: подпись считается по JSON
    всего тела запроса без поля sign, ключи отсортированы."""
    provided_sign = payload.get('sign', '')
    if not provided_sign:
        return False
    data_copy = {k: v for k, v in payload.items() if k != 'sign'}
    sorted_data = dict(sorted(data_copy.items()))
    json_str = json.dumps(sorted_data, ensure_ascii=False, separators=(',', ':'))
    expected = hmac.new(token.encode('utf-8'), json_str.encode('utf-8'), hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, provided_sign)


async def severpay_webhook(request: web.Request) -> web.Response:
    """Внутренний бридж-эндпоинт: n8n принимает вебхук от SeverPay на
    публичном домене и форвардит сюда с секретом моста в заголовке.
    Путь /webhooks/severpay/{shop}, shop = 'ecom' или 'sbp' — определяет,
    каким токеном проверять подпись SeverPay."""
    if settings.sendler_webhook_secret:
        bridge_secret = request.headers.get('X-Bridge-Secret')
        if bridge_secret != settings.sendler_webhook_secret:
            return web.json_response({'status': False}, status=401)

    shop = request.match_info.get('shop', '')
    token_by_shop = {
        'ecom': settings.severpay_token,
        'sbp': getattr(settings, 'severpay_sbp_token', None),
    }
    token = token_by_shop.get(shop)
    if not token:
        return web.json_response({'status': False, 'error': 'unknown_shop'}, status=400)

    payload = await request.json()

    if not _verify_severpay_signature(payload, token):
        for admin_id in settings.admin_ids:
            await bot.send_message(
                admin_id,
                f"⚠️ SeverPay webhook ({shop}): неверная подпись, платёж не зачтён автоматически.\n"
                f"Данные: {payload.get('data')}\nПроверьте вручную.",
            )
        return web.json_response({'status': False, 'error': 'bad_signature'}, status=401)

    if payload.get('type') != 'payin':
        return web.json_response({'status': True})

    data = payload.get('data', {})
    if str(data.get('status', '')).lower() != 'success':
        return web.json_response({'status': True})

    order_id = str(data.get('order_id', ''))
    invoice_id = str(data.get('id', ''))
    internal_payment_id = _extract_payment_id_from_order_id(order_id)

    async with SessionLocal() as session:
        from database.models.payment import Payment

        payment = None
        if internal_payment_id:
            payment = await get_payment(session, internal_payment_id)

        if not payment and invoice_id:
            payment = (
                await session.execute(
                    select(Payment).where(
                        Payment.provider == 'severpay',
                        Payment.provider_payment_id == invoice_id,
                    )
                )
            ).scalar_one_or_none()

        if not payment or payment.status == 'paid':
            return web.json_response({'status': True})

        subscription = await get_subscription(session, payment.subscription_id)
        user_id = payment.user.telegram_id
        await mark_payment_paid(session, payment.id, invoice_id or order_id)

    if subscription:
        await _deliver_or_fallback(user_id, subscription)

    return web.json_response({'status': True})


async def create_webhook_app() -> web.Application:
    app = web.Application()
    app.router.add_post('/webhooks/cryptobot', cryptobot_webhook)
    app.router.add_post('/webhooks/donation', donation_webhook)
    app.router.add_post('/webhooks/sendler', sendler_webhook)
    app.router.add_post('/webhooks/platega', platega_webhook)
    app.router.add_post('/webhooks/severpay/{shop}', severpay_webhook)
    return app
