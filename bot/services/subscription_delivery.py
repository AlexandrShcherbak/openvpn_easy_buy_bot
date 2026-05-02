from aiogram import Bot
from aiogram.types import FSInputFile

from bot.keyboards.user import main_menu_kb
from config.config import settings
from database.crud import activate_subscription
from database.db import SessionLocal
from database.models.subscription import Subscription
from openvpn.generator import save_client_files
from openvpn.manager import OpenVPNPoolManager

ovpn_manager = OpenVPNPoolManager(pool_dir=settings.openvpn_pool_dir)


async def activate_and_deliver_subscription(bot: Bot, user_telegram_id: int, subscription: Subscription) -> None:
    client = ovpn_manager.get_next_config()
    conf_path, qr_path = save_client_files(client)

    async with SessionLocal() as session:
        managed_subscription = await session.get(Subscription, subscription.id)
        if not managed_subscription:
            return

        await activate_subscription(
            session=session,
            subscription=managed_subscription,
            vpn_client_id=client.id,
            vpn_client_name=client.name,
            config_path=conf_path,
        )

    await bot.send_document(
        user_telegram_id,
        FSInputFile(conf_path),
        caption='Оплата подтверждена. Ваш OpenVPN конфиг (.ovpn):',
    )
    await bot.send_photo(
        user_telegram_id,
        FSInputFile(qr_path),
        caption='QR-код для быстрого импорта в мобильное приложение',
    )
    await bot.send_message(user_telegram_id, 'Подписка активирована ✅', reply_markup=main_menu_kb())
