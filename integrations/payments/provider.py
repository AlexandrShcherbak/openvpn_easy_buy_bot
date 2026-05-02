from __future__ import annotations

from dataclasses import dataclass
from hashlib import md5
import hashlib
import hmac
from urllib.parse import urlencode
import json
import time
import logging
from typing import Optional, Dict, Any

import aiohttp

# Настройка логирования
logger = logging.getLogger(__name__)


@dataclass(slots=True)
class PaymentStatus:
    invoice_id: str
    state: str
    amount: Optional[float] = None
    currency: Optional[str] = None


@dataclass(slots=True)
class Invoice:
    invoice_id: str
    pay_url: str
    amount: Optional[float] = None
    currency: Optional[str] = None


class StubPaymentProvider:
    async def create_invoice(self, user_id: int, amount_rub: int, payload: str | None = None) -> Invoice:
        invoice_id = payload or f"stub-invoice-{user_id}-{amount_rub}"
        return Invoice(invoice_id=invoice_id, pay_url=f"https://example.com/pay/{invoice_id}")

    async def get_status(self, invoice_id: str) -> PaymentStatus:
        return PaymentStatus(invoice_id=invoice_id, state='pending')


class RedirectPaymentProvider:
    def __init__(self, base_url: str, provider_name: str) -> None:
        self.base_url = base_url.rstrip('/')
        self.provider_name = provider_name

    async def create_invoice(self, user_id: int, amount_rub: int, payload: str | None = None) -> Invoice:
        invoice_id = payload or f"{self.provider_name}_{user_id}_{amount_rub}_{int(time.time())}"
        query = urlencode({'amount': amount_rub, 'payload': invoice_id})
        return Invoice(invoice_id=invoice_id, pay_url=f"{self.base_url}?{query}")

    async def get_status(self, invoice_id: str) -> PaymentStatus:
        return PaymentStatus(invoice_id=invoice_id, state='pending')


class DonationAlertsProvider:
    """Провайдер для донатов через DonationAlerts"""
    
    def __init__(self, base_url: str, client_id: str = None, client_secret: str = None, 
                 redirect_uri: str = None, access_token: str = None) -> None:
        self.base_url = base_url.rstrip('/')
        self.client_id = client_id
        self.client_secret = client_secret
        self.redirect_uri = redirect_uri
        self.access_token = access_token
        self.api_url = 'https://www.donationalerts.com/api/v1'
        
    async def create_invoice(self, user_id: int, amount_rub: int, payload: str | None = None) -> Invoice:
        """
        Создание ссылки для доната через DonationAlerts
        """
        invoice_id = payload or f"donationalerts_{user_id}_{amount_rub}_{int(time.time())}"
        
        # Если есть access_token, можно добавить параметры для отслеживания
        if self.access_token:
            # Добавляем параметры для отслеживания источника доната
            query_params = {
                'amount': amount_rub,
                'payload': invoice_id,
                'user_id': user_id
            }
            query = urlencode(query_params)
            pay_url = f"{self.base_url}?{query}"
        else:
            # Простая ссылка на страницу сбора донатов
            pay_url = self.base_url
            
        return Invoice(invoice_id=invoice_id, pay_url=pay_url)
    
    async def get_status(self, invoice_id: str) -> PaymentStatus:
        """
        Проверка статуса доната
        Для DonationAlerts полагаемся на webhook уведомления
        """
        # Здесь можно добавить проверку через API DonationAlerts если есть access_token
        # Но обычно статус обновляется через webhook
        return PaymentStatus(invoice_id=invoice_id, state='pending')
    
    async def verify_webhook(self, data: dict, signature: str = None) -> bool:
        """
        Проверка подписи webhook от DonationAlerts
        """
        if not self.client_secret:
            return True  # Если секрет не настроен, пропускаем проверку
            
        # Простая проверка на основе client_secret
        expected_signature = hmac.new(
            self.client_secret.encode(),
            json.dumps(data, sort_keys=True).encode(),
            digestmod='sha256'
        ).hexdigest()
        
        if signature:
            return hmac.compare_digest(signature, expected_signature)
        return False


class FreekassaProvider:
    def __init__(self, merchant_id: str, secret_word_1: str) -> None:
        self.merchant_id = merchant_id
        self.secret_word_1 = secret_word_1
        self.base_url = 'https://pay.fk.money/'

    async def create_invoice(self, user_id: int, amount_rub: int, payload: str | None = None) -> Invoice:
        order_id = payload or f"fk_{user_id}_{int(time.time())}"
        amount = f"{amount_rub:.2f}"
        currency = 'RUB'
        sign = md5(f"{self.merchant_id}:{amount}:{self.secret_word_1}:{currency}:{order_id}".encode()).hexdigest()
        params = {
            'm': self.merchant_id,
            'oa': amount,
            'currency': currency,
            'o': order_id,
            's': sign,
            'lang': 'ru',
        }
        return Invoice(invoice_id=order_id, pay_url=f"{self.base_url}?{urlencode(params)}")

    async def get_status(self, invoice_id: str) -> PaymentStatus:
        return PaymentStatus(invoice_id=invoice_id, state='pending')


class SeverPayProvider:
    def __init__(
        self,
        base_url: str,
        mid: int,
        token: str,
        client_email: str | None = None,
        return_url: str | None = None,
        lifetime_minutes: int = 1440,
    ) -> None:
        self.base_url = base_url.rstrip('/')
        self.mid = mid
        self.token = token
        self.client_email = client_email
        self.return_url = return_url
        self.lifetime_minutes = lifetime_minutes
        logger.info(f"SeverPayProvider initialized with base_url: {base_url}, mid: {mid}")

    def _generate_sign(self, params: dict) -> str:
        """Генерация подписи строго по документации SeverPay."""
        params_copy = {k: v for k, v in params.items() if k != 'sign'}
        sorted_params = dict(sorted(params_copy.items()))
        json_str = json.dumps(sorted_params, ensure_ascii=False, separators=(',', ':'))
        
        signature = hmac.new(
            self.token.encode('utf-8'),
            json_str.encode('utf-8'),
            hashlib.sha256
        ).hexdigest()
        
        return signature

    async def create_invoice(self, user_id: int, amount_rub: int, payload: str | None = None) -> Invoice:
        order_id = payload or f"sp_{user_id}_{int(time.time())}"
        client_email = self.client_email or f"user{user_id}@telegram.local"
        
        # Важно: amount как число с двумя знаками
        amount = float(f"{amount_rub:.2f}")
        
        params = {
            'mid': self.mid,
            'order_id': order_id,
            'amount': amount,
            'currency': 'RUB',
            'client_id': str(user_id),
            'client_email': client_email,
            'salt': str(int(time.time() * 1000)),
            'lifetime': self.lifetime_minutes,
        }
        
        if self.return_url:
            params['url_return'] = self.return_url
        
        # Генерируем подпись
        sign = self._generate_sign(params)
        params['sign'] = sign
        
        logger.info(f"Creating SeverPay invoice: {params}")
        
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    f"{self.base_url}/payin/create",
                    json=params,
                    headers={'Content-Type': 'application/json'},
                    timeout=30,
                ) as resp:
                    data = await resp.json()
                    
                    logger.info(f"SeverPay response: {data}")
                    
                    if not data.get('status'):
                        raise RuntimeError(f"SeverPay error: {data.get('msg')}")
                    
                    return Invoice(
                        invoice_id=str(data['data']['id']),
                        pay_url=data['data']['url'],
                        amount=amount,
                        currency='RUB'
                    )
                    
        except Exception as e:
            logger.error(f"SeverPay error: {e}")
            raise

    async def get_status(self, invoice_id: str) -> PaymentStatus:
        params = {
            'mid': self.mid,
            'id': str(invoice_id),
            'salt': str(int(time.time() * 1000))
        }
        
        sign = self._generate_sign(params)
        params['sign'] = sign
        
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    f"{self.base_url}/payin/get",
                    json=params,
                    headers={'Content-Type': 'application/json'},
                    timeout=30,
                ) as resp:
                    data = await resp.json()
                    
                    if not data.get('status'):
                        return PaymentStatus(invoice_id=invoice_id, state='pending')
                    
                    status_map = {
                        'new': 'pending',
                        'process': 'pending',
                        'success': 'paid',
                        'decline': 'failed',
                        'fail': 'failed',
                    }
                    
                    state = status_map.get(data['data'].get('status', 'new'), 'pending')
                    
                    return PaymentStatus(
                        invoice_id=invoice_id,
                        state=state,
                        amount=data['data'].get('amount'),
                        currency='RUB'
                    )
                    
        except Exception as e:
            logger.error(f"SeverPay status error: {e}")
            return PaymentStatus(invoice_id=invoice_id, state='pending')


class PlategaProvider:
    """Провайдер для PlateGa API."""

    def __init__(
        self,
        merchant_id: str,
        api_key: str,
        payment_method: int = 2,  # 2 = СБП (QR-код)
        success_url: str | None = None,
        fail_url: str | None = None,
    ) -> None:
        self.merchant_id = merchant_id
        self.api_key = api_key
        self.payment_method = payment_method
        self.success_url = success_url
        self.fail_url = fail_url
        self.base_url = "https://app.platega.io"
        logger.info(f"PlategaProvider initialized with merchant_id: {merchant_id}")

    async def create_invoice(self, user_id: int, amount_rub: int, payload: str | None = None) -> Invoice:
        """Создание платежа через PlateGa API."""
        order_id = payload or f"platega_{user_id}_{int(time.time())}"
        
        # Формируем запрос согласно документации
        request_data = {
            "paymentMethod": self.payment_method,  # 2 = СБП
            "paymentDetails": {
                "amount": float(amount_rub),
                "currency": "RUB"
            },
            "description": f"TgId:{user_id}",  # Telegram ID в описании
        }
        
        # Добавляем URL для возврата
        if self.success_url:
            request_data["return"] = self.success_url
        if self.fail_url:
            request_data["failedUrl"] = self.fail_url
        if order_id:
            request_data["payload"] = order_id
            
        logger.info(f"Creating PlateGa invoice for user {user_id}, amount: {amount_rub} RUB")
        logger.debug(f"PlateGa request: {request_data}")
        
        # Правильные заголовки авторизации
        headers = {
            "Content-Type": "application/json",
            "X-MerchantId": self.merchant_id,
            "X-Secret": self.api_key
        }
        
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    f"{self.base_url}/transaction/process",
                    json=request_data,
                    headers=headers,
                    timeout=30
                ) as resp:
                    response_text = await resp.text()
                    logger.debug(f"PlateGa response status: {resp.status}")
                    logger.debug(f"PlateGa response body: {response_text}")
                    
                    if resp.status != 200:
                        logger.error(f"PlateGa HTTP error: {resp.status}")
                        raise RuntimeError(f"PlateGa API error {resp.status}: {response_text}")
                    
                    try:
                        data = json.loads(response_text)
                    except json.JSONDecodeError as e:
                        logger.error(f"Failed to parse PlateGa response: {e}")
                        raise RuntimeError(f"PlateGa invalid JSON response: {response_text}")
                    
                    # Получаем ID транзакции и ссылку для оплаты
                    transaction_id = data.get("transactionId")
                    redirect_url = data.get("redirect")
                    
                    if not transaction_id:
                        logger.error(f"PlateGa response missing transactionId: {data}")
                        raise RuntimeError(f"PlateGa response missing transactionId")
                    
                    if not redirect_url:
                        logger.error(f"PlateGa response missing redirect URL: {data}")
                        raise RuntimeError(f"PlateGa response missing redirect URL")
                    
                    logger.info(f"PlateGa invoice created: {transaction_id}")
                    logger.info(f"PlateGa redirect URL: {redirect_url}")
                    
                    return Invoice(
                        invoice_id=transaction_id,
                        pay_url=redirect_url,
                        amount=float(amount_rub),
                        currency='RUB'
                    )
                    
        except aiohttp.ClientError as e:
            logger.error(f"PlateGa connection error: {e}")
            raise RuntimeError(f"PlateGa connection error: {e}")
        except Exception as e:
            logger.error(f"PlateGa unexpected error: {e}")
            raise

    async def get_status(self, invoice_id: str) -> PaymentStatus:
        """Проверка статуса платежа через PlateGa API."""
        headers = {
            "X-MerchantId": self.merchant_id,
            "X-Secret": self.api_key
        }
        
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    f"{self.base_url}/transaction/{invoice_id}",
                    headers=headers,
                    timeout=30
                ) as resp:
                    if resp.status != 200:
                        logger.warning(f"PlateGa status check failed: {resp.status}")
                        return PaymentStatus(invoice_id=invoice_id, state='pending')
                    
                    data = await resp.json()
                    
                    # Маппинг статусов PlateGa
                    status_map = {
                        "PENDING": "pending",
                        "CONFIRMED": "paid",
                        "CANCELED": "canceled",
                        "CHARGEBACKED": "failed",
                    }
                    
                    plate_status = data.get("status", "PENDING")
                    state = status_map.get(plate_status, "pending")
                    
                    payment_details = data.get("paymentDetails", {})
                    amount = payment_details.get("amount") if isinstance(payment_details, dict) else None
                    currency = payment_details.get("currency") if isinstance(payment_details, dict) else "RUB"
                    
                    return PaymentStatus(
                        invoice_id=invoice_id,
                        state=state,
                        amount=amount,
                        currency=currency
                    )
                    
        except Exception as e:
            logger.error(f"PlateGa status check error: {e}")
            return PaymentStatus(invoice_id=invoice_id, state='pending')


class CryptoCloudProvider:
    """Провайдер для CryptoCloud"""
    
    def __init__(self, api_key: str, shop_id: str, api_url: str = "https://api.cryptocloud.plus/v2", 
                 test_mode: bool = True) -> None:
        """
        Инициализация CryptoCloud провайдера
        
        Args:
            api_key: API ключ из личного кабинета
            shop_id: ID магазина (обязателен)
            api_url: URL API CryptoCloud
            test_mode: Включен ли тестовый режим
        """
        self.api_key = api_key
        self.shop_id = shop_id  # Теперь shop_id обязателен
        self.api_url = api_url.rstrip('/')
        self.base_url = "https://cryptocloud.plus"
        self.test_mode = test_mode
        logger.info(f"CryptoCloudProvider initialized with shop_id: {shop_id}, test_mode: {test_mode}")
    
    async def create_invoice(self, user_id: int, amount_rub: int, payload: str | None = None) -> Invoice:
        """
        Создание счета через CryptoCloud API
        """
        # Формируем уникальный ID заказа
        order_id = payload or f"cryptocloud_{user_id}_{int(time.time())}"
        
        # Подготавливаем параметры для создания счета
        # shop_id обязателен!
        params = {
            "shop_id": self.shop_id,  # Обязательное поле
            "amount": float(amount_rub),
            "order_id": order_id,
            "currency": "RUB",
            "description": f"Payment from user {user_id}",
            "email": f"user{user_id}@example.com",
        }
        
        # Добавляем тестовый режим
        if self.test_mode:
            params["is_test"] = True
        
        logger.info(f"Creating CryptoCloud invoice for user {user_id}, amount: {amount_rub} RUB")
        logger.info(f"Using shop_id: {self.shop_id}")
        logger.debug(f"Request params: {params}")
        
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    f"{self.api_url}/invoice/create",
                    json=params,
                    headers={
                        'Authorization': f'Token {self.api_key}',
                        'Content-Type': 'application/json'
                    },
                    timeout=30
                ) as resp:
                    response_text = await resp.text()
                    logger.debug(f"CryptoCloud response status: {resp.status}")
                    logger.debug(f"CryptoCloud response body: {response_text}")
                    
                    if resp.status != 200:
                        logger.error(f"CryptoCloud API HTTP error: {resp.status}")
                        raise RuntimeError(f"CryptoCloud API error {resp.status}: {response_text}")
                    
                    try:
                        data = json.loads(response_text)
                    except json.JSONDecodeError as e:
                        logger.error(f"Failed to parse CryptoCloud response: {e}")
                        raise RuntimeError(f"CryptoCloud invalid JSON response: {response_text}")
                    
                    # Проверяем успешность ответа
                    if not data.get('success', False):
                        error_msg = data.get('message', 'Unknown error')
                        logger.error(f"CryptoCloud API error: {error_msg}")
                        raise RuntimeError(f"CryptoCloud API error: {error_msg}")
                    
                    result = data.get('result', {})
                    
                    # Получаем ID и URL счета
                    invoice_id = result.get('invoice_id') or result.get('id')
                    pay_url = result.get('pay_url') or result.get('url')
                    
                    if not invoice_id:
                        logger.error(f"CryptoCloud response missing invoice_id: {result}")
                        raise RuntimeError(f"CryptoCloud response missing invoice_id")
                    
                    # Если нет pay_url, формируем из base_url
                    if not pay_url:
                        pay_url = f"{self.base_url}/pay/{invoice_id}"
                    
                    # Если тестовый режим, добавляем параметр
                    if self.test_mode:
                        if '?' in pay_url:
                            pay_url += "&is_test=1"
                        else:
                            pay_url += "?is_test=1"
                    
                    logger.info(f"CryptoCloud invoice created: {invoice_id}")
                    logger.info(f"Pay URL: {pay_url}")
                    
                    return Invoice(
                        invoice_id=str(invoice_id),
                        pay_url=pay_url,
                        amount=float(amount_rub),
                        currency='RUB'
                    )
                    
        except aiohttp.ClientError as e:
            logger.error(f"CryptoCloud API client error: {e}")
            raise RuntimeError(f"CryptoCloud connection error: {e}")
        except Exception as e:
            logger.error(f"CryptoCloud unexpected error: {e}")
            raise


class CrystalPayRedirectProvider:
    """Провайдер для CrystalPay с фиксированным инвойсом"""
    
    def __init__(self, base_url: str, shop_id: str, static_invoice_id: str = None) -> None:
        self.base_url = base_url.rstrip('/')
        self.shop_id = shop_id
        # Используем статический инвойс, если он задан, иначе генерируем
        self.static_invoice_id = static_invoice_id or "715336239_JnDTgoxYNMToLC"
        logger.info(f"CrystalPayRedirectProvider initialized with base_url: {base_url}, static_invoice_id: {self.static_invoice_id}")

    async def create_invoice(self, user_id: int, amount_rub: int, payload: str | None = None) -> Invoice:
        """
        Используем фиксированный инвойс для всех платежей
        """
        # Используем статический инвойс
        invoice_id = self.static_invoice_id
        
        # Формируем URL для оплаты
        pay_url = f"{self.base_url}/?i={invoice_id}"
        
        logger.info(f"CrystalPay invoice created (static): {invoice_id}")
        logger.info(f"Pay URL: {pay_url}")
        
        return Invoice(
            invoice_id=invoice_id,
            pay_url=pay_url
        )

    async def get_status(self, invoice_id: str) -> PaymentStatus:
        """Проверка статуса платежа"""
        # Для статического инвойса проверка статуса происходит вручную через поддержку
        return PaymentStatus(invoice_id=invoice_id, state='pending')


class CryptoBotProvider:
    def __init__(self, token: str) -> None:
        self.token = token
        self.base_url = 'https://pay.crypt.bot/api'

    async def create_invoice(self, user_id: int, amount_rub: int, payload: str | None = None) -> Invoice:
        url = f"{self.base_url}/createInvoice"
        headers = {"Crypto-Pay-API-Token": self.token, "Content-Type": "application/json"}
        # Конвертируем RUB в USDT (примерный курс 1 USDT = 90 RUB)
        amount_usdt = round(amount_rub / 90, 2)
        data = {
            "asset": "USDT",
            "amount": str(amount_usdt),
            "description": f"VPN subscription for user {user_id}",
            "allow_comments": False,
            "allow_anonymous": False,
        }
        if payload:
            data["payload"] = payload
        async with aiohttp.ClientSession() as session:
            async with session.post(url, headers=headers, json=data, timeout=20) as resp:
                if resp.status != 200:
                    raise RuntimeError(f"CryptoBot API error: {resp.status} - {await resp.text()}")
                response_data = await resp.json()
        if not response_data.get('ok'):
            raise RuntimeError(f"CryptoBot invoice creation failed: {response_data}")
        result = response_data['result']
        pay_url = result.get('bot_invoice_url') or result.get('pay_url')
        return Invoice(
            invoice_id=str(result['invoice_id']), 
            pay_url=pay_url,
            amount=amount_usdt,
            currency='USDT'
        )

    async def get_status(self, invoice_id: str) -> PaymentStatus:
        url = f"{self.base_url}/getInvoices"
        headers = {"Crypto-Pay-API-Token": self.token, "Content-Type": "application/json"}
        params = {'invoice_ids': invoice_id}
        async with aiohttp.ClientSession() as session:
            async with session.get(url, headers=headers, params=params, timeout=20) as resp:
                if resp.status != 200:
                    raise RuntimeError(f"CryptoBot API error: {resp.status} - {await resp.text()}")
                data = await resp.json()
        if not data.get('ok'):
            raise RuntimeError(f"CryptoBot getInvoices failed: {data}")
        items = data.get('result', {}).get('items', [])
        if not items:
            return PaymentStatus(invoice_id=invoice_id, state='not_found')
        return PaymentStatus(
            invoice_id=invoice_id, 
            state=items[0].get('status', 'pending'),
            amount=float(items[0].get('amount', 0)),
            currency=items[0].get('asset', 'USDT')
        )


def get_payment_provider(provider_name: str, settings):
    provider = provider_name.lower()
    logger.info(f"Getting payment provider: {provider}")

    if provider == "cryptobot":
        if not settings.cryptobot_token:
            raise ValueError("CryptoBot token not configured")
        return CryptoBotProvider(settings.cryptobot_token)

    if provider == "freekassa":
        if not settings.freekassa_shop_id or not settings.freekassa_secret_word_1:
            raise ValueError("FreeKassa credentials not configured")
        return FreekassaProvider(settings.freekassa_shop_id, settings.freekassa_secret_word_1)

    if provider == "severpay":
        if not settings.severpay_mid or not settings.severpay_token:
            raise ValueError("SeverPay credentials not configured")
    
        logger.info(f"Creating SeverPayProvider with mid: {settings.severpay_mid}")
    
        return SeverPayProvider(
            settings.severpay_base_url,
            settings.severpay_mid,
            settings.severpay_token,
            client_email=getattr(settings, "severpay_client_email", None),
            return_url=getattr(settings, "severpay_return_url", None),
            lifetime_minutes=getattr(settings, "severpay_lifetime_minutes", None),
        )

    if provider == "cryptocloud":
        if not settings.cryptocloud_api_key:
            raise ValueError("CryptoCloud API key not configured")
        
        # shop_id обязателен!
        if not settings.cryptocloud_shop_id:
            raise ValueError("CryptoCloud shop_id is required. Please set CRYPTOCLOUD_SHOP_ID in .env")
        
        # Получаем настройки из settings
        shop_id = getattr(settings, 'cryptocloud_shop_id', None)
        api_url = getattr(settings, 'cryptocloud_base_url', 'https://api.cryptocloud.plus/v2')
        test_mode = getattr(settings, 'cryptocloud_test_mode', True)
        
        logger.info(f"Creating CryptoCloudProvider with shop_id: {shop_id}, test_mode: {test_mode}")
        return CryptoCloudProvider(
            api_key=settings.cryptocloud_api_key,
            shop_id=shop_id,
            api_url=api_url,
            test_mode=test_mode
        )

    if provider == "donationalerts":
        if not settings.donationalerts_base_url:
            raise ValueError("DonationAlerts url not configured")
        return DonationAlertsProvider(
            base_url=settings.donationalerts_base_url,
            client_id=getattr(settings, 'donationalerts_client_id', None),
            client_secret=getattr(settings, 'donationalerts_client_secret', None),
            redirect_uri=getattr(settings, 'donationalerts_redirect_uri', None),
            access_token=getattr(settings, 'donationalerts_access_token', None)
        )

    if provider == "boosty":
        if not settings.boosty_base_url:
            raise ValueError("Boosty url not configured")
        return RedirectPaymentProvider(settings.boosty_base_url, provider)

    if provider == "crystalpay":
        # Используем статический инвойс для CrystalPay
        if not settings.crystalpay_base_url:
            raise ValueError("CrystalPay base url not configured")
    
        # Получаем статический инвойс из настроек или используем значение по умолчанию
        static_invoice_id = getattr(settings, 'crystalpay_static_invoice_id', None)
        if not static_invoice_id:
            static_invoice_id = "715336239_JnDTgoxYNMToLC"  # Ваш инвойс
    
        logger.info(f"Using CrystalPayRedirectProvider with static invoice: {static_invoice_id}")
        return CrystalPayRedirectProvider(
            settings.crystalpay_base_url, 
            settings.crystalpay_shop_id,
            static_invoice_id
        )

    if provider == "platega":
        if not settings.platega_shop_id or not settings.platega_api_key:
            raise ValueError("Platega credentials not configured")
    
        # Получаем payment_method из настроек или используем 2 (СБП)
        payment_method = getattr(settings, 'platega_payment_method', 2)
    
        return PlategaProvider(
            merchant_id=settings.platega_shop_id,
            api_key=settings.platega_api_key,
            payment_method=payment_method,
            success_url=getattr(settings, "platega_success_url", None),
            fail_url=getattr(settings, "platega_fail_url", None),
        )

    logger.warning(f"No matching provider found for {provider}, using StubPaymentProvider")
    return StubPaymentProvider()
