import os
from functools import lru_cache
from pathlib import Path
from typing import Optional

from pydantic.v1 import BaseSettings, Field, ValidationError, root_validator

ROOT_DIR = Path(__file__).resolve().parent.parent
ENV_FILES = (
    ROOT_DIR / '.env',
    ROOT_DIR / 'env',
    Path.cwd() / '.env',
    Path.cwd() / 'env',
)


def _load_env_files() -> None:
    """Load KEY=VALUE pairs from local env files without python-dotenv."""
    loaded_paths: set[Path] = set()
    for env_file in ENV_FILES:
        env_path = env_file.resolve()
        if env_path in loaded_paths:
            continue
        loaded_paths.add(env_path)

        if not env_file.exists():
            continue

        for raw_line in env_file.read_text(encoding='utf-8-sig').splitlines():
            line = raw_line.strip()
            if not line or line.startswith('#') or '=' not in line:
                continue

            if line.startswith('export '):
                line = line[len('export '):].strip()

            key, value = line.split('=', 1)
            key = key.strip()
            value = value.strip()

            if ' #' in value and not value.startswith(('"', "'")):
                value = value.split(' #', 1)[0].rstrip()

            if value and ((value[0] == value[-1]) and value[0] in {'"', "'"}):
                value = value[1:-1]

            os.environ.setdefault(key, value)

    # Совместимость со старыми именами переменных.
    if 'ADMIN_IDS' not in os.environ and 'ADMIN_ID' in os.environ:
        os.environ['ADMIN_IDS'] = f"[{os.environ['ADMIN_ID']}]"

    if 'CRYPTOBOT_TOKEN' not in os.environ:
        legacy_token = os.environ.get('CRYPTOBOT_API_TOKEN') or os.environ.get('PAYMENT_TOKEN')
        if legacy_token:
            os.environ['CRYPTOBOT_TOKEN'] = legacy_token

    if 'DONATIONALERTS_BASE_URL' not in os.environ and 'DONATIONALERTS_URL' in os.environ:
        os.environ['DONATIONALERTS_BASE_URL'] = os.environ['DONATIONALERTS_URL']


class Settings(BaseSettings):
    bot_token: str = Field(..., env='BOT_TOKEN')
    admin_ids: list[int] = Field(default_factory=list, env='ADMIN_IDS')

    database_url: str = Field(default='sqlite+aiosqlite:///./vpn_bot.db', env='DATABASE_URL')

    openvpn_pool_dir: str = Field(default='storage/configs/pool', env='OPENVPN_POOL_DIR')

    payment_provider: str = Field(default='manual', env='PAYMENT_PROVIDER')
    payment_token: str | None = Field(default=None, env='PAYMENT_TOKEN')
    cryptobot_token: str | None = Field(default=None, env='CRYPTOBOT_TOKEN')
    donationalerts_token: str | None = Field(default=None, env='DONATIONALERTS_TOKEN') 
    donationalerts_base_url: str | None = Field(default=None, env='DONATIONALERTS_BASE_URL')
    boosty_base_url: str | None = Field(default=None, env='BOOSTY_BASE_URL')
    support_contact: str = Field(default='support@example.com', env='SUPPORT_CONTACT')
    support_email: str = Field(default='support@example.com', env='SUPPORT_EMAIL')
    owner_contact: str = Field(default='owner@example.com', env='OWNER_CONTACT')
    telegram_bot_url: str = Field(default='https://telegram.me/wireguard_easy_buy_bot', env='TELEGRAM_BOT_URL')

    # n8n — тот же вебхук, что принимает заявки с лендинга (для прогрева/реактивации
    # пользователей, пришедших сразу в бота, минуя лендинг)
    n8n_lead_webhook_url: str | None = Field(
        default='https://n8n.redviberussian.com/webhook/vpn-lead', env='N8N_LEAD_WEBHOOK_URL'
    )

    # URLs для документов (обновлены ссылки)
    terms_url: str = Field(default='https://telegra.ph/Polzovatelskoe-soglashenie-04-01-19', env='TERMS_URL')
    privacy_url: str = Field(default='https://telegra.ph/Politika-konfidencialnosti-04-01-26', env='PRIVACY_URL')
    contacts_url: str = Field(default='https://telegram.me/alexandrshcherbak', env='CONTACTS_URL')

    # FreeKassa
    freekassa_shop_id: str | None = Field(default=None, env='FREEKASSA_SHOP_ID')
    freekassa_secret_word_1: str | None = Field(default=None, env='FREEKASSA_SECRET_WORD_1')
    freekassa_secret_word_2: str | None = Field(default=None, env='FREEKASSA_SECRET_WORD_2')

    # Platega
    platega_base_url: str | None = Field(default=None, env='PLATEGA_BASE_URL')
    platega_shop_id: str | None = Field(default=None, env='PLATEGA_SHOP_ID')
    platega_api_key: str | None = Field(default=None, env='PLATEGA_API_KEY')
    platega_create_invoice_path: str = Field(default='/api/v1/invoices', env='PLATEGA_CREATE_INVOICE_PATH')
    platega_success_url: str | None = Field(default=None, env='PLATEGA_SUCCESS_URL')

    # SeverPay (магазин ecom / card)
    severpay_base_url: str = Field(default='https://severpay.io/api/merchant', env='SEVERPAY_BASE_URL')
    severpay_mid: int | None = Field(default=None, env='SEVERPAY_MID')
    severpay_token: str | None = Field(default=None, env='SEVERPAY_TOKEN')
    severpay_client_email: str | None = Field(default=None, env='SEVERPAY_CLIENT_EMAIL')
    severpay_return_url: str | None = Field(default=None, env='SEVERPAY_RETURN_URL')
    severpay_lifetime_minutes: int | None = Field(default=None, env='SEVERPAY_LIFETIME_MINUTES')

    # SeverPay (второй магазин sbp / СБП)
    severpay_sbp_mid: int | None = Field(default=None, env='SEVERPAY_SBP_MID')
    severpay_sbp_token: str | None = Field(default=None, env='SEVERPAY_SBP_TOKEN')

    # CryptoCloud (оставлен для совместимости, но не используется в UI)
    cryptocloud_base_url: str = Field(default='https://api.cryptocloud.plus/v2', env='CRYPTOCLOUD_BASE_URL')
    cryptocloud_api_key: Optional[str] = Field(default=None, env='CRYPTOCLOUD_API_KEY')
    cryptocloud_shop_id: Optional[str] = Field(default=None, env='CRYPTOCLOUD_SHOP_ID')
    cryptocloud_test_mode: bool = Field(default=True, env='CRYPTOCLOUD_TEST_MODE')

    # CrystalPay (оставлен для совместимости, но не используется в UI)
    crystalpay_base_url: str | None = Field(default=None, env='CRYSTALPAY_BASE_URL')
    crystalpay_api_url: str = Field(default='https://api.crystalpay.io/v3', env='CRYSTALPAY_API_URL')
    crystalpay_auth_login: str | None = Field(default=None, env='CRYSTALPAY_AUTH_LOGIN')
    crystalpay_auth_secret: str | None = Field(default=None, env='CRYSTALPAY_AUTH_SECRET')
    crystalpay_token: str | None = Field(default=None, env='CRYSTALPAY_TOKEN')
    crystalpay_salt: str | None = Field(default=None, env='CRYSTALPAY_SALT')
    crystalpay_shop_id: str | None = Field(default=None, env='CRYSTALPAY_SHOP_ID')
    crystalpay_callback_url: str | None = Field(default=None, env='CRYSTALPAY_CALLBACK_URL')

    # Вебхуки
    sendler_webhook_enabled: bool = Field(default=False, env='SENDLER_WEBHOOK_ENABLED')
    sendler_webhook_host: str = Field(default='0.0.0.0', env='SENDLER_WEBHOOK_HOST')
    sendler_webhook_port: int = Field(default=8080, env='SENDLER_WEBHOOK_PORT')
    sendler_webhook_secret: str | None = Field(default=None, env='SENDLER_WEBHOOK_SECRET')

    # План подписки
    trial_days: int = Field(default=1, env='TRIAL_DAYS')
    default_plan_days: int = Field(default=180, env='DEFAULT_PLAN_DAYS')
    default_plan_price_rub: int = Field(default=600, env='DEFAULT_PLAN_PRICE_RUB')

    @root_validator(pre=True)
    def populate_admin_ids_from_single_admin_id(cls, values: dict) -> dict:
        """Support ADMIN_ID for convenience when ADMIN_IDS is not defined."""
        if not values.get('ADMIN_IDS') and not values.get('admin_ids'):
            single_admin_id = values.get('ADMIN_ID') or values.get('admin_id')
            if single_admin_id not in (None, ''):
                values['ADMIN_IDS'] = f'[{single_admin_id}]'

        if not values.get('CRYPTOBOT_TOKEN') and not values.get('cryptobot_token'):
            values['CRYPTOBOT_TOKEN'] = (
                values.get('CRYPTOBOT_API_TOKEN')
                or values.get('cryptobot_api_token')
                or values.get('PAYMENT_TOKEN')
                or values.get('payment_token')
            )

        if not values.get('DONATIONALERTS_BASE_URL') and not values.get('donationalerts_base_url'):
            values['DONATIONALERTS_BASE_URL'] = values.get('DONATIONALERTS_URL') or values.get('donationalerts_url')
        
        # Fix for PRIVACY_URL and TERMS_URL - обновляем на новые ссылки
        if values.get('PRIVACY_URL') in ('/privacy', 'https://telegra.ph/Politika-konfidencialnosti-08-15-17'):
            values['PRIVACY_URL'] = 'https://telegra.ph/Politika-konfidencialnosti-04-01-26'
        if values.get('TERMS_URL') in ('/terms', 'https://telegra.ph/Polzovatelskoe-soglashenie-08-15-10'):
            values['TERMS_URL'] = 'https://telegra.ph/Polzovatelskoe-soglashenie-04-01-19'
        if values.get('CONTACTS_URL') == '/contacts':
            values['CONTACTS_URL'] = 'https://telegram.me/alexandrshcherbak'
        
        # Для CrystalPay: используем shop_id как auth_login если не задан отдельно
        if not values.get('CRYSTALPAY_AUTH_LOGIN') and values.get('CRYSTALPAY_SHOP_ID'):
            values['CRYSTALPAY_AUTH_LOGIN'] = values.get('CRYSTALPAY_SHOP_ID')
        
        # Для CrystalPay: используем token как auth_secret если не задан отдельно
        if not values.get('CRYSTALPAY_AUTH_SECRET') and values.get('CRYSTALPAY_TOKEN'):
            values['CRYSTALPAY_AUTH_SECRET'] = values.get('CRYSTALPAY_TOKEN')

        return values

    class Config:
        extra = 'ignore'


@lru_cache
def get_settings() -> Settings:
    _load_env_files()
    return Settings()
