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
        lifetime_minutes: int | None = None,
    ) -> None:
        self.base_url = base_url.rstrip('/')
        self.mid = mid
        self.token = token
        self.client_email = client_email
        self.return_url = return_url
        self.lifetime_minutes = lifetime_minutes
        logger.info(f"SeverPayProvider initialized with base_url: {base_url}, mid: {mid}")

    def _generate_sign(self, params: dict) -> str:
        """
        Генерация подписи для SeverPay согласно документации:
        1. Сортируем параметры по ключам
        2. Создаем JSON представление отсортированного массива (ensure_ascii=False, separators=(',', ':'))
        3. Вычисляем подпись sign с использованием алгоритма HMAC-SHA256 на основе JSON-представления и секретного ключа token
        """
        # Убираем sign если он есть
        params_copy = {k: v for k, v in params.items() if k != 'sign'}
        
        # Сортируем по ключам
        sorted_params = dict(sorted(params_copy.items()))
        
        # Создаем JSON представление без пробелов
        json_str = json.dumps(sorted_params, ensure_ascii=False, separators=(',', ':'))
        
        logger.debug(f"SeverPay JSON for signature: {json_str}")
        
        # Вычисляем HMAC-SHA256
        signature = hmac.new(
            self.token.encode('utf-8'),
            json_str.encode('utf-8'),
            hashlib.sha256
        ).hexdigest()
        
        logger.debug(f"SeverPay signature: {signature}")
        
        return signature

    async def create_invoice(self, user_id: int, amount_rub: int, payload: str | None = None) -> Invoice:
        order_id = payload or f"sp_{user_id}_{int(time.time())}"

        client_email = self.client_email or f"user{user_id}@example.com"
        params = {
            'mid': self.mid,
            'order_id': order_id,
            'amount': float(amount_rub),
            'currency': 'RUB',
            'client_id': str(user_id),
            'client_email': client_email,
            'salt': str(int(time.time()))
        }
        if self.return_url:
            params['url_return'] = self.return_url
        if self.lifetime_minutes and 30 <= self.lifetime_minutes <= 4320:
            params['lifetime'] = int(self.lifetime_minutes)
        
        logger.info(f"Creating SeverPay invoice for user {user_id}, amount: {amount_rub} RUB")
        logger.debug(f"SeverPay request params: {params}")
        
        # Генерируем подпись
        sign = self._generate_sign(params)
        params['sign'] = sign
        
        async with aiohttp.ClientSession() as session:
            async with session.post(
                f"{self.base_url}/payin/create",
                json=params,
                headers={'Content-Type': 'application/json'},
                timeout=30,
            ) as resp:
                response_text = await resp.text()
                logger.debug(f"SeverPay response status: {resp.status}")
                logger.debug(f"SeverPay response body: {response_text}")
                
                try:
                    data = await resp.json(content_type=None)
                except Exception as e:
                    logger.error(f"Failed to parse SeverPay response: {e}")
                    raise RuntimeError(f"SeverPay create payment error: {response_text}")
                
                if resp.status != 200:
                    logger.error(f"SeverPay HTTP error: {resp.status}")
                    raise RuntimeError(f"SeverPay HTTP error {resp.status}: {response_text}")
                
                if not data.get('status'):
                    logger.error(f"SeverPay API error: {data}")
                    raise RuntimeError(f"SeverPay create payment error: {data}")
                
                if not data.get('data') or not data['data'].get('id'):
                    logger.error(f"SeverPay response missing data: {data}")
                    raise RuntimeError(f"SeverPay response missing data: {data}")
                
                invoice_id = str(data['data']['id'])
                pay_url = data['data']['url']
                
                logger.info(f"SeverPay invoice created: {invoice_id}")
                logger.info(f"SeverPay pay URL: {pay_url}")
                
                return Invoice(
                    invoice_id=invoice_id,
                    pay_url=pay_url,
                    amount=float(amount_rub),
                    currency='RUB'
                )

    async def get_status(self, invoice_id: str) -> PaymentStatus:
        # Формируем параметры для запроса статуса
        params = {
            'id': str(invoice_id),
            'mid': self.mid,
            'salt': str(int(time.time()))
        }
        
        logger.debug(f"Checking SeverPay status for invoice: {invoice_id}")
        
        # Генерируем подпись
        sign = self._generate_sign(params)
        params['sign'] = sign
        
        async with aiohttp.ClientSession() as session:
            async with session.post(
                f"{self.base_url}/payin/get",
                json=params,
                headers={'Content-Type': 'application/json'},
                timeout=30,
            ) as resp:
                try:
                    data = await resp.json(content_type=None)
                    logger.debug(f"SeverPay status response: {data}")
                except Exception as e:
                    logger.error(f"Failed to parse SeverPay status response: {e}")
                    return PaymentStatus(invoice_id=invoice_id, state='pending')
                
                if resp.status != 200 or not data.get('status'):
                    logger.warning(f"SeverPay status check failed: {data}")
                    return PaymentStatus(invoice_id=invoice_id, state='pending')
                
                if not data.get('data'):
                    logger.warning(f"SeverPay status response missing data: {data}")
                    return PaymentStatus(invoice_id=invoice_id, state='pending')
                
                # Маппинг статусов SeverPay
                status_map = {
                    0: 'pending',    # ожидает оплаты
                    1: 'paid',       # оплачен
                    2: 'canceled',   # отменен
                    3: 'expired',    # истек
                }
                
                payment_status = data['data'].get('status', 0)
                status = status_map.get(payment_status, 'pending')
                
                logger.info(f"SeverPay payment status for {invoice_id}: {status}")
                
                return PaymentStatus(
                    invoice_id=invoice_id, 
                    state=status,
                    amount=data['data'].get('amount'),
                    currency='RUB'
                )


class PlategaProvider:
    """Провайдер для Platega API."""

    def __init__(
        self,
        base_url: str,
        merchant_id: str,
        api_key: str,
        create_invoice_path: str = "/transaction/process",
        success_url: str | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.merchant_id = merchant_id
        self.api_key = api_key
        self.create_invoice_path = create_invoice_path if create_invoice_path.startswith("/") else f"/{create_invoice_path}"
        self.success_url = success_url

    def _extract_invoice_id(self, response_data: dict[str, Any]) -> str | None:
        candidates = (
            response_data.get("id"),
            response_data.get("invoice_id"),
            response_data.get("transaction_id"),
            (response_data.get("data") or {}).get("id"),
            (response_data.get("data") or {}).get("invoice_id"),
            (response_data.get("result") or {}).get("id"),
            (response_data.get("result") or {}).get("invoice_id"),
        )
        for value in candidates:
            if value not in (None, ""):
                return str(value)
        return None

    def _extract_pay_url(self, response_data: dict[str, Any]) -> str | None:
        candidates = (
            response_data.get("url"),
            response_data.get("pay_url"),
            response_data.get("payment_url"),
            response_data.get("checkout_url"),
            (response_data.get("data") or {}).get("url"),
            (response_data.get("data") or {}).get("pay_url"),
            (response_data.get("result") or {}).get("url"),
            (response_data.get("result") or {}).get("pay_url"),
        )
        for value in candidates:
            if value:
                return str(value)
        return None

    async def create_invoice(self, user_id: int, amount_rub: int, payload: str | None = None) -> Invoice:
        order_id = payload or f"platega_{user_id}_{int(time.time())}"
        request_data: dict[str, Any] = {
            "amount": amount_rub,
            "currency": "RUB",
            "orderId": order_id,
            "description": f"VPN subscription for user {user_id}",
        }
        if self.success_url:
            request_data["successUrl"] = self.success_url

        headers = {
            "Content-Type": "application/json",
            "X-MerchantId": self.merchant_id,
            "X-Secret": self.api_key,
            "Accept": "application/json",
        }
        candidate_paths = [self.create_invoice_path]
        if self.create_invoice_path != "/transaction/process":
            candidate_paths.append("/transaction/process")

        response_data: dict[str, Any] | None = None
        last_error = ""
        async with aiohttp.ClientSession() as session:
            for path in candidate_paths:
                url = f"{self.base_url}{path}"
                async with session.post(url, json=request_data, headers=headers, timeout=30) as resp:
                    response_text = await resp.text()
                    if resp.status == 404 and path != "/transaction/process":
                        last_error = f"{path} -> 404"
                        continue
                    if resp.status >= 400:
                        raise RuntimeError(f"Platega API error {resp.status}: {response_text}")

                    try:
                        response_data = json.loads(response_text)
                    except json.JSONDecodeError as exc:
                        raise RuntimeError(f"Platega invalid JSON response: {response_text}") from exc
                    break

        if response_data is None:
            raise RuntimeError(f"Platega API error - endpoint not found ({last_error})")

        invoice_id = (
            response_data.get("transactionId")
            or response_data.get("transaction_id")
            or self._extract_invoice_id(response_data)
        )
        pay_url = response_data.get("redirect") or self._extract_pay_url(response_data)
        if not invoice_id or not pay_url:
            raise RuntimeError(f"Platega response missing transactionId/redirect: {response_data}")

        return Invoice(invoice_id=str(invoice_id), pay_url=str(pay_url), amount=float(amount_rub), currency="RUB")

    async def get_status(self, invoice_id: str) -> PaymentStatus:
        # Статус платежа обновляется через callback/webhook.
        return PaymentStatus(invoice_id=invoice_id, state="pending")


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
        if not settings.platega_base_url or not settings.platega_shop_id or not settings.platega_api_key:
            raise ValueError("Platega credentials not configured")
        return PlategaProvider(
            base_url=settings.platega_base_url,
            merchant_id=settings.platega_shop_id,
            api_key=settings.platega_api_key,
            create_invoice_path=getattr(settings, "platega_create_invoice_path", "/transaction/process"),
            success_url=getattr(settings, "platega_success_url", None),
        )

    logger.warning(f"No matching provider found for {provider}, using StubPaymentProvider")
    return StubPaymentProvider()
