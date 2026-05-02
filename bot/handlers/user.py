import logging
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from sqlalchemy.ext.asyncio import AsyncSession

# Импорты моделей и функций
from database.models.subscription import Subscription
from database.models.user import User
from database.models.payment import Payment
from database.crud import (
    get_or_create_user,
    create_subscription,
    get_subscription,
    create_payment,
    get_payment,
    mark_payment_paid,
    get_latest_pending_subscription
)
from config.config import settings
from bot.keyboards.inline import (
    get_main_keyboard,
    get_subscription_keyboard,
    get_payment_methods_keyboard,
    check_payment_kb,
    buy_methods_kb,
    main_menu_kb
)
from bot.states import SupportState
from integrations.payments.provider import get_payment_provider, CryptoBotProvider, SeverPayProvider
from database.db import SessionLocal
from aiogram.utils.formatting import Text, Bold
from aiogram.enums import ParseMode

router = Router()
logger = logging.getLogger(__name__)


def _build_howto_text() -> str:
    """Текст инструкции по подключению"""
    return (
        '📘 <b>Как подключить VPN за 1 минуту</b>\n\n'
        '1) Установите OpenVPN Connect:\n'
        '• Android: https://play.google.com/store/apps/details?id=net.openvpn.openvpn\n'
        '• iOS: https://apps.apple.com/us/app/openvpn-connect/id590379981\n'
        '• Windows/macOS/Linux: https://openvpn.net/client/\n\n'
        f'2) После оплаты перейдите в бота: {settings.telegram_bot_url}\n'
        '3) Отправьте чек в поддержку.\n'
        '4) Поддержка выдаст .ovpn файл и QR-код в личные сообщения.\n'
        '5) В OpenVPN Connect импортируйте .ovpn файл (или отсканируйте QR).\n'
        '6) Нажмите Connect и проверьте IP: https://2ip.ru\n\n'
        f'Если нужна помощь — {getattr(settings, "support_contact", "@support")}'
    )


def _provider_title(provider_name: str) -> str:
    titles = {
        'freekassa': 'FreeKassa',
        'platega': 'Platega',
        'severpay': 'SeverPay',
        'cryptobot': 'CryptoBot',
        'donationalerts': 'DonationAlerts',
    }
    return titles.get(provider_name, provider_name)


@router.message(Command("start"))
async def cmd_start(message: Message) -> None:
    """Обработчик команды /start"""
    try:
        async with SessionLocal() as session:
            await get_or_create_user(
                session=session,
                telegram_id=message.from_user.id,
                username=message.from_user.username,
                full_name=message.from_user.full_name or "Unknown",
            )
        await message.answer(
            '👋 Привет! Это VPN-бот.\n\n'
            'Я помогу вам подключить быстрый и безопасный VPN через OpenVPN.\n'
            'Выберите действие:',
            reply_markup=get_main_keyboard()
        )
    except Exception as e:
        logger.error(f"Error in cmd_start: {e}")
        await message.answer("Произошла ошибка. Попробуйте позже.")


@router.message(Command("howto"))
async def cmd_howto(message: Message) -> None:
    """Обработчик команды /howto"""
    await message.answer(
        _build_howto_text(),
        disable_web_page_preview=True,
        parse_mode=ParseMode.HTML
    )


@router.callback_query(F.data == "howto")
async def howto_callback(call: CallbackQuery) -> None:
    """Обработчик кнопки Howto"""
    await call.message.edit_text(
        _build_howto_text(),
        disable_web_page_preview=True,
        reply_markup=get_main_keyboard(),
        parse_mode=ParseMode.HTML
    )
    await call.answer()


@router.callback_query(F.data == "menu")
async def open_menu(call: CallbackQuery) -> None:
    """Возврат в главное меню"""
    await call.message.edit_text(
        '📋 Главное меню:',
        reply_markup=get_main_keyboard()
    )
    await call.answer()


@router.callback_query(F.data == "support")
async def write_to_support(call: CallbackQuery) -> None:
    """Обработчик кнопки поддержки"""
    support_contact = getattr(settings, "support_contact", "@support_bot")
    await call.message.edit_text(
        f'📞 Написать в поддержку: {support_contact}\n\n'
        f'Бот для покупки/подтверждения оплаты: {settings.telegram_bot_url}\n'
        'Опишите вашу проблему, и мы поможем!',
        reply_markup=get_main_keyboard(),
    )
    await call.answer()


@router.callback_query(F.data == "buy")
async def buy_sub(call: CallbackQuery) -> None:
    """Обработчик покупки подписки"""
    try:
        async with SessionLocal() as session:
            user = await get_or_create_user(
                session=session,
                telegram_id=call.from_user.id,
                username=call.from_user.username,
                full_name=call.from_user.full_name or "Unknown",
            )
            
            subscription = await create_subscription(
                session=session,
                user_id=user.id,
                plan_days=settings.default_plan_days,
                price_rub=settings.default_plan_price_rub,
            )

        text = (
            f'📦 <b>Подписка на {settings.default_plan_days} дней</b>\n\n'
            f'💰 Стоимость: <b>{settings.default_plan_price_rub} ₽</b>\n'
            f'🆔 Номер заказа: <code>{subscription.id}</code>\n\n'
            'Выберите способ оплаты:'
        )
        
        await call.message.edit_text(
            text,
            reply_markup=buy_methods_kb(subscription.id),
            parse_mode=ParseMode.HTML
        )
        await call.answer()
        
    except Exception as e:
        logger.error(f"Error in buy_sub: {e}")
        await call.answer("Ошибка при создании заказа", show_alert=True)


@router.callback_query(F.data == "trial")
async def trial_info(call: CallbackQuery) -> None:
    """Информация о пробном периоде"""
    await call.answer(
        'Пробный период подключается через поддержку. Напишите в чат поддержки.',
        show_alert=True
    )


@router.callback_query(F.data.startswith("pay_provider:"))
async def create_provider_payment(call: CallbackQuery) -> None:
    """Создание платежа через выбранный провайдер."""
    try:
        _, provider_name, subscription_id_raw = call.data.split(":", 2)
        subscription_id = int(subscription_id_raw)
        
        async with SessionLocal() as session:
            subscription = await get_subscription(session, subscription_id)
            user = await get_or_create_user(
                session=session,
                telegram_id=call.from_user.id,
                username=call.from_user.username,
                full_name=call.from_user.full_name or "Unknown",
            )
            
            if not subscription or subscription.user_id != user.id:
                await call.answer("Заказ не найден", show_alert=True)
                return

            payment = await create_payment(
                session=session,
                user_id=user.id,
                amount_rub=subscription.price_rub,
                subscription_id=subscription.id,
                provider=provider_name,
            )

        provider = get_payment_provider(provider_name, settings)
        payload = f"subscription:{subscription.id}:payment:{payment.id}"
        invoice = await provider.create_invoice(
            user_id=call.from_user.id,
            amount_rub=subscription.price_rub,
            payload=payload,
        )

        # Сохраняем ID инвойса
        async with SessionLocal() as session:
            db_payment = await get_payment(session, payment.id)
            if db_payment:
                db_payment.provider_payment_id = invoice.invoice_id
                await session.commit()

        await call.message.edit_text(
            f'✅ <b>Счёт создан ({_provider_title(provider_name)})</b>\n\n'
            f'Сумма: {subscription.price_rub} ₽\n'
            f'Номер счёта: <code>{invoice.invoice_id}</code>\n\n'
            f'Для оплаты перейдите по ссылке:\n{invoice.pay_url}',
            reply_markup=check_payment_kb(payment.id),
            parse_mode=ParseMode.HTML,
            disable_web_page_preview=True
        )
        await call.answer()
    except ValueError as e:
        logger.error(f"Provider config error: {e}")
        await call.answer(str(e), show_alert=True)
    except Exception as e:
        logger.error(f"Error in create_provider_payment: {e}")
        await call.answer("Ошибка при создании платежа", show_alert=True)


@router.callback_query(F.data.startswith("pay_sbp:"))
async def pay_sbp_info(call: CallbackQuery) -> None:
    """Информация об оплате через СБП"""
    support_contact = getattr(settings, "support_contact", "@support_bot")
    await call.message.edit_text(
        "🏦 <b>Оплата по СБП</b>\n\n"
        "Для оплаты через СБП напишите в поддержку и запросите актуальные реквизиты.\n"
        "После перевода отправьте чек в личные сообщения поддержки.\n\n"
        f"Контакт поддержки: {support_contact}",
        reply_markup=get_main_keyboard(),
        parse_mode=ParseMode.HTML
    )
    await call.answer()


@router.callback_query(F.data.startswith("check_payment:"))
async def check_payment_status(call: CallbackQuery) -> None:
    """Проверка статуса платежа"""
    try:
        payment_id = int(call.data.split(":")[1])
        
        async with SessionLocal() as session:
            payment = await get_payment(session, payment_id)
            if not payment:
                await call.answer("Платёж не найден", show_alert=True)
                return

            subscription = await get_subscription(session, payment.subscription_id)
            user = await get_or_create_user(
                session=session,
                telegram_id=call.from_user.id,
                username=call.from_user.username,
                full_name=call.from_user.full_name or "Unknown",
            )

            if payment.user_id != user.id or not subscription:
                await call.answer("Нет доступа к этому платежу", show_alert=True)
                return

            # Если уже оплачен
            if payment.status == 'paid':
                await call.answer("✅ Платёж уже подтверждён", show_alert=False)
                return

            # Проверяем статус в зависимости от провайдера
            is_paid = False
            
            if payment.provider == 'cryptobot':
                cryptobot_token = getattr(settings, 'cryptobot_token', None) or getattr(settings, 'payment_token', None)
                if cryptobot_token and payment.provider_payment_id:
                    provider = CryptoBotProvider(cryptobot_token)
                    status = await provider.get_status(payment.provider_payment_id)
                    is_paid = status.state == 'paid'
            elif payment.provider == 'severpay':
                # Для SeverPay проверка через API
                if payment.provider_payment_id and settings.severpay_mid and settings.severpay_token:
                    provider = SeverPayProvider(
                        settings.severpay_base_url, 
                        settings.severpay_mid, 
                        settings.severpay_token
                    )
                    status = await provider.get_status(payment.provider_payment_id)
                    is_paid = status.state == 'paid'
            elif payment.provider in {'donationalerts', 'freekassa', 'platega'}:
                # Для этих провайдеров оплата подтверждается вручную через webhook
                await call.answer(
                    "Оплата подтверждается вручную. Ожидайте подтверждения от поддержки.",
                    show_alert=True
                )
                return
            else:
                # Для остальных провайдеров - ручное подтверждение
                await call.answer(
                    "Для выбранного способа оплата подтверждается вручную. "
                    "Ожидайте подтверждения от поддержки.",
                    show_alert=True
                )
                return

            if not is_paid:
                await call.answer("❌ Оплата не найдена. Попробуйте позже.", show_alert=True)
                return

            # Подтверждаем оплату
            await mark_payment_paid(session, payment.id, payment.provider_payment_id)
            
        support_contact = getattr(settings, "support_contact", "@support_bot")
        await call.answer("✅ Оплата подтверждена", show_alert=False)
        
        # Возвращаемся в меню
        await call.message.edit_text(
            "✅ Оплата подтверждена!\n\n"
            f"🤖 Перейдите в Telegram-бот: {settings.telegram_bot_url}\n"
            "📩 Отправьте чек в личные сообщения поддержки для получения конфигурации и QR-кода.\n"
            f"Контакт поддержки: {support_contact}",
            reply_markup=get_main_keyboard()
        )
        
    except Exception as e:
        logger.error(f"Error in check_payment_status: {e}")
        await call.answer("Ошибка при проверке платежа", show_alert=True)


@router.callback_query(F.data.startswith("back_to_subscription:"))
async def back_to_subscription(call: CallbackQuery) -> None:
    """Возврат к информации о подписке"""
    try:
        subscription_id = int(call.data.split(":")[1])
        
        async with SessionLocal() as session:
            subscription = await get_subscription(session, subscription_id)
            if not subscription:
                await call.answer("Подписка не найдена", show_alert=True)
                return

        text = (
            f'📦 <b>Подписка на {subscription.plan_days} дней</b>\n\n'
            f'💰 Стоимость: <b>{subscription.price_rub} ₽</b>\n'
            f'🆔 Номер заказа: <code>{subscription.id}</code>\n\n'
            'Выберите способ оплаты:'
        )
        
        await call.message.edit_text(
            text,
            reply_markup=buy_methods_kb(subscription.id),
            parse_mode=ParseMode.HTML
        )
        await call.answer()
        
    except Exception as e:
        logger.error(f"Error in back_to_subscription: {e}")
        await call.answer("Ошибка", show_alert=True)


@router.callback_query(F.data == "paid")
async def paid_handler_deprecated(call: CallbackQuery) -> None:
    """Устаревший обработчик"""
    await call.answer(
        'Используйте новый способ оплаты через кнопки.',
        show_alert=True
    )


@router.callback_query(F.data == "legal_docs")
async def legal_docs(call: CallbackQuery) -> None:
    """Обработчик кнопки документы и контакты"""
    from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
    
    # Получаем ссылки из настроек
    privacy_url = getattr(settings, 'privacy_url', 'https://telegra.ph/Politika-konfidencialnosti-04-01-26')
    terms_url = getattr(settings, 'terms_url', 'https://telegra.ph/Polzovatelskoe-soglashenie-04-01-19')
    support_email = getattr(settings, 'support_email', 'scherbakalexanders@gmail.com')
    owner_contact = getattr(settings, 'owner_contact', 'https://t.me/alexandrshcherbak')
    
    # Проверяем, что URL начинаются с http:// или https://
    if not privacy_url.startswith(('http://', 'https://')):
        privacy_url = 'https://' + privacy_url.lstrip('/')
    if not terms_url.startswith(('http://', 'https://')):
        terms_url = 'https://' + terms_url.lstrip('/')
    if owner_contact and not owner_contact.startswith(('http://', 'https://', 'tg://', 't.me/')):
        owner_contact = 'https://' + owner_contact
    
    # Формируем текст
    text = (
        "📄 <b>Документы и контакты</b>\n\n"
        "🔐 <b>Политика конфиденциальности</b>\n"
        f"{privacy_url}\n\n"
        "📜 <b>Пользовательское соглашение</b>\n"
        f"{terms_url}\n\n"
        "📧 <b>Email поддержки</b>\n"
        f"{support_email}\n\n"
        "👤 <b>Контакты владельца</b>\n"
        f"{owner_contact}"
    )
    
    # Создаем клавиатуру со ссылками
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🔐 Политика конфиденциальности", url=privacy_url)],
            [InlineKeyboardButton(text="📜 Пользовательское соглашение", url=terms_url)],
            [InlineKeyboardButton(text="✉️ Email поддержки", callback_data="support")],
            [InlineKeyboardButton(text="👤 Контакты владельца", url=owner_contact if owner_contact.startswith(('http://', 'https://')) else "https://t.me/alexandrshcherbak")],
            [InlineKeyboardButton(text="⬅️ В меню", callback_data="menu")]
        ]
    )
    
    await call.message.edit_text(
        text,
        reply_markup=keyboard,
        parse_mode=ParseMode.HTML,
        disable_web_page_preview=True
    )
    await call.answer()