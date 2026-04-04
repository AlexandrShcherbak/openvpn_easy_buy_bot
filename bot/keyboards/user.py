from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup


def main_menu_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text='💳 Купить подписку', callback_data='buy')],
            [InlineKeyboardButton(text='🎁 Пробный период', callback_data='trial')],
            [InlineKeyboardButton(text='📘 Как подключить', callback_data='howto')],
            [InlineKeyboardButton(text='🆘 Написать в поддержку', callback_data='support')],
        ]
    )


def buy_methods_kb(subscription_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text='💳 FreeKassa', callback_data=f'pay_provider:freekassa:{subscription_id}')],
            [InlineKeyboardButton(text='💳 Platega', callback_data=f'pay_provider:platega:{subscription_id}')],
            [InlineKeyboardButton(text='💳 SeverPay', callback_data=f'pay_provider:severpay:{subscription_id}')],
            [InlineKeyboardButton(text='🤖 CryptoBot', callback_data=f'pay_provider:cryptobot:{subscription_id}')],
            [InlineKeyboardButton(text='💝 DonationAlerts', callback_data=f'pay_provider:donationalerts:{subscription_id}')],
            [InlineKeyboardButton(text='🏦 Оплатить по СБП', callback_data=f'pay_sbp:{subscription_id}')],
            [InlineKeyboardButton(text='⬅️ В меню', callback_data='menu')],
        ]
    )


def check_payment_kb(payment_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text='🔄 Проверить оплату', callback_data=f'check_payment:{payment_id}')],
            [InlineKeyboardButton(text='⬅️ В меню', callback_data='menu')],
        ]
    )
