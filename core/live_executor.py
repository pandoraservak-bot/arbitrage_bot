# Live trading executor using official SDKs
import asyncio
import time
import logging
import json
import os
from typing import Dict, List, Optional
from datetime import datetime

from config import DATA_DIR, TRADING_CONFIG, EXCHANGE_CONFIG

logger = logging.getLogger(__name__)

class LiveTradeExecutor:
    def __init__(self):
        self.config = TRADING_CONFIG
        self.exchange_config = EXCHANGE_CONFIG
        
        self.hyperliquid_exchange = None
        self.hyperliquid_info = None
        self.bitget_client = None
        
        self.initialized = False
        self.order_history = []
        self.trade_history = []
        
        self.hyperliquid_symbol = "NVDA"
        self.bitget_symbol = "NVDAUSDT"
        
    async def initialize(self) -> bool:
        """Initialize exchange connections"""
        try:
            hl_success = await self._init_hyperliquid()
            bg_success = await self._init_bitget()
            
            self.initialized = hl_success and bg_success
            
            if self.initialized:
                logger.info("Live Trading Executor initialized successfully")
            else:
                if not hl_success:
                    logger.warning("Hyperliquid initialization failed - check API keys")
                if not bg_success:
                    logger.warning("Bitget initialization failed - check API keys")
                    
            return self.initialized
            
        except Exception as e:
            logger.error(f"Error initializing Live Executor: {e}")
            return False
    
    async def _init_hyperliquid(self) -> bool:
        """Initialize Hyperliquid SDK connection"""
        try:
            from hyperliquid.info import Info
            from hyperliquid.exchange import Exchange
            from hyperliquid.utils import constants
            from eth_account import Account
            
            secret_key = os.environ.get('HYPERLIQUID_SECRET_KEY')
            account_address = os.environ.get('HYPERLIQUID_ACCOUNT_ADDRESS')
            
            if not secret_key:
                logger.warning("HYPERLIQUID_SECRET_KEY not set in environment")
                return False
                
            wallet = Account.from_key(secret_key)
            
            api_url = constants.MAINNET_API_URL
            
            self.hyperliquid_info = Info(api_url, skip_ws=True)
            self.hyperliquid_exchange = Exchange(
                wallet=wallet,
                base_url=api_url,
                account_address=account_address
            )
            
            user_state = self.hyperliquid_info.user_state(account_address or wallet.address)
            logger.info(f"Hyperliquid connected. Account: {wallet.address[:10]}...")
            
            return True
            
        except ImportError as e:
            logger.error(f"Hyperliquid SDK import error: {e}")
            return False
        except Exception as e:
            logger.error(f"Hyperliquid init error: {e}")
            return False
    
    async def _init_bitget(self) -> bool:
        """Initialize Bitget API connection"""
        try:
            import hmac
            import hashlib
            import base64
            import requests
            
            api_key = os.environ.get('BITGET_API_KEY')
            secret_key = os.environ.get('BITGET_SECRET_KEY')
            passphrase = os.environ.get('BITGET_PASSPHRASE')
            
            if not all([api_key, secret_key, passphrase]):
                logger.warning("Bitget API credentials not fully set in environment")
                return False
            
            self.bitget_credentials = {
                'api_key': api_key,
                'secret_key': secret_key,
                'passphrase': passphrase
            }
            
            self.bitget_base_url = "https://api.bitget.com"
            
            response = self._bitget_request('GET', '/api/v2/mix/account/account', {
                'symbol': 'NVDAUSDT',
                'productType': 'USDT-FUTURES',
                'marginCoin': 'USDT'
            })
            
            if response and response.get('code') == '00000':
                logger.info(f"Bitget connected. API Key: {api_key[:8]}...")
                return True
            else:
                logger.warning(f"Bitget connection test failed: {response}")
                return False
                
        except Exception as e:
            logger.error(f"Bitget init error: {e}")
            return False
    
    def _bitget_sign(self, timestamp: str, method: str, request_path: str, body: str = '') -> str:
        """Generate Bitget API signature"""
        import hmac
        import hashlib
        import base64
        
        message = timestamp + method.upper() + request_path + body
        secret = self.bitget_credentials['secret_key']
        
        signature = hmac.new(
            secret.encode('utf-8'),
            message.encode('utf-8'),
            hashlib.sha256
        ).digest()
        
        return base64.b64encode(signature).decode('utf-8')
    
    def _bitget_request(self, method: str, endpoint: str, params: Dict = None, body: Dict = None) -> Dict:
        """Make authenticated Bitget API request"""
        import requests
        import json
        
        timestamp = str(int(time.time() * 1000))
        
        if method.upper() == 'GET' and params:
            query_string = '&'.join([f"{k}={v}" for k, v in params.items()])
            request_path = f"{endpoint}?{query_string}"
            body_str = ''
        else:
            request_path = endpoint
            body_str = json.dumps(body) if body else ''
        
        signature = self._bitget_sign(timestamp, method, request_path, body_str)
        
        headers = {
            'ACCESS-KEY': self.bitget_credentials['api_key'],
            'ACCESS-SIGN': signature,
            'ACCESS-TIMESTAMP': timestamp,
            'ACCESS-PASSPHRASE': self.bitget_credentials['passphrase'],
            'Content-Type': 'application/json',
            'locale': 'en-US'
        }
        
        url = self.bitget_base_url + request_path
        
        try:
            if method.upper() == 'GET':
                response = requests.get(url, headers=headers, timeout=10)
            else:
                response = requests.post(url, headers=headers, data=body_str, timeout=10)
            
            return response.json()
        except Exception as e:
            logger.error(f"Bitget request error: {e}")
            return {'code': 'error', 'msg': str(e)}
    
    async def execute_hyperliquid_order(self, side: str, size: float, price: float = None) -> Dict:
        """Execute order on Hyperliquid"""
        if not self.hyperliquid_exchange:
            return {'success': False, 'error': 'Hyperliquid not initialized'}
        
        try:
            is_buy = side.lower() == 'buy'
            
            if price:
                order_result = self.hyperliquid_exchange.order(
                    name=self.hyperliquid_symbol,
                    is_buy=is_buy,
                    sz=size,
                    limit_px=price,
                    order_type={"limit": {"tif": "Ioc"}}
                )
            else:
                order_result = self.hyperliquid_exchange.market_open(
                    name=self.hyperliquid_symbol,
                    is_buy=is_buy,
                    sz=size,
                    slippage=self.config.get('MARKET_SLIPPAGE', 0.001)
                )
            
            if order_result.get('status') == 'ok':
                statuses = order_result.get('response', {}).get('data', {}).get('statuses', [])
                
                result = {
                    'success': True,
                    'exchange': 'hyperliquid',
                    'order_id': str(time.time()),
                    'side': side,
                    'size': size,
                    'status': 'filled' if statuses and 'filled' in str(statuses) else 'submitted',
                    'raw_response': order_result,
                    'timestamp': time.time()
                }
                
                self.order_history.append(result)
                logger.info(f"Hyperliquid order executed: {side} {size} {self.hyperliquid_symbol}")
                return result
            else:
                return {
                    'success': False,
                    'error': order_result.get('response', {}).get('data', {}).get('error', 'Unknown error'),
                    'raw_response': order_result
                }
                
        except Exception as e:
            logger.error(f"Hyperliquid order error: {e}")
            return {'success': False, 'error': str(e)}
    
    async def execute_bitget_order(self, side: str, size: float, price: float = None) -> Dict:
        """Execute order on Bitget"""
        if not self.bitget_credentials:
            return {'success': False, 'error': 'Bitget not initialized'}
        
        try:
            params = {
                'symbol': self.bitget_symbol,
                'productType': 'USDT-FUTURES',
                'marginMode': 'crossed',
                'marginCoin': 'USDT',
                'size': str(size),
                'side': 'buy' if side.lower() == 'buy' else 'sell',
                'tradeSide': 'open',
                'orderType': 'market' if not price else 'limit'
            }
            
            if price:
                params['price'] = str(price)
            
            response = self._bitget_request('POST', '/api/v2/mix/order/place-order', body=params)
            
            if response.get('code') == '00000':
                data = response.get('data', {})
                
                result = {
                    'success': True,
                    'exchange': 'bitget',
                    'order_id': data.get('orderId', str(time.time())),
                    'client_order_id': data.get('clientOid'),
                    'side': side,
                    'size': size,
                    'status': 'submitted',
                    'raw_response': response,
                    'timestamp': time.time()
                }
                
                self.order_history.append(result)
                logger.info(f"Bitget order executed: {side} {size} {self.bitget_symbol}")
                return result
            else:
                return {
                    'success': False,
                    'error': response.get('msg', 'Unknown error'),
                    'raw_response': response
                }
                
        except Exception as e:
            logger.error(f"Bitget order error: {e}")
            return {'success': False, 'error': str(e)}
    
    async def execute_fok_pair_async(self, buy_order: Dict, sell_order: Dict, tag: str = "") -> Dict:
        """Execute pair of orders (buy on one exchange, sell on another)"""
        if not self.initialized:
            return {'success': False, 'error': 'Executor not initialized', 'tag': tag}
        
        try:
            buy_exchange = buy_order.get('exchange', '').lower()
            sell_exchange = sell_order.get('exchange', '').lower()
            
            buy_amount = buy_order.get('amount', 0)
            sell_amount = sell_order.get('amount', 0)
            
            logger.info(f"Executing FOK pair: Buy on {buy_exchange}, Sell on {sell_exchange}, tag: {tag}")
            
            if buy_exchange == 'hyperliquid':
                buy_result = await self.execute_hyperliquid_order('buy', buy_amount)
            else:
                buy_result = await self.execute_bitget_order('buy', buy_amount)
            
            if not buy_result.get('success'):
                return {
                    'success': False,
                    'error': f"Buy order failed: {buy_result.get('error')}",
                    'tag': tag,
                    'buy_result': buy_result
                }
            
            if sell_exchange == 'hyperliquid':
                sell_result = await self.execute_hyperliquid_order('sell', sell_amount)
            else:
                sell_result = await self.execute_bitget_order('sell', sell_amount)
            
            if not sell_result.get('success'):
                logger.error(f"Sell order failed after buy succeeded! Manual intervention may be needed.")
                return {
                    'success': False,
                    'error': f"Sell order failed: {sell_result.get('error')}",
                    'tag': tag,
                    'buy_result': buy_result,
                    'sell_result': sell_result,
                    'requires_manual_intervention': True
                }
            
            trade_result = {
                'success': True,
                'tag': tag,
                'buy_order': buy_result,
                'sell_order': sell_result,
                'timestamp': time.time()
            }
            
            self.trade_history.append(trade_result)
            logger.info(f"FOK pair executed successfully: {tag}")
            
            return trade_result
            
        except Exception as e:
            logger.error(f"Error executing FOK pair: {e}")
            return {'success': False, 'error': str(e), 'tag': tag}
    
    async def get_hyperliquid_position(self) -> Dict:
        """Get current position on Hyperliquid"""
        if not self.hyperliquid_info:
            return {}
        
        try:
            address = os.environ.get('HYPERLIQUID_ACCOUNT_ADDRESS')
            if not address and self.hyperliquid_exchange:
                address = self.hyperliquid_exchange.wallet.address
            
            user_state = self.hyperliquid_info.user_state(address)
            
            for pos in user_state.get('assetPositions', []):
                if pos.get('position', {}).get('coin') == self.hyperliquid_symbol:
                    return pos.get('position', {})
            
            return {}
            
        except Exception as e:
            logger.error(f"Error getting Hyperliquid position: {e}")
            return {}
    
    async def get_bitget_position(self) -> Dict:
        """Get current position on Bitget"""
        if not self.bitget_credentials:
            return {}
        
        try:
            response = self._bitget_request('GET', '/api/v2/mix/position/single-position', {
                'symbol': self.bitget_symbol,
                'productType': 'USDT-FUTURES',
                'marginCoin': 'USDT'
            })
            
            if response.get('code') == '00000':
                data = response.get('data', [])
                if data:
                    return data[0] if isinstance(data, list) else data
            
            return {}
            
        except Exception as e:
            logger.error(f"Error getting Bitget position: {e}")
            return {}
    
    def get_trade_history(self) -> List[Dict]:
        """Get trade history"""
        return self.trade_history.copy()
    
    def get_order_history(self) -> List[Dict]:
        """Get order history"""
        return self.order_history.copy()
    
    def is_ready(self) -> bool:
        """Check if executor is ready for trading"""
        return self.initialized
    
    def get_status(self) -> Dict:
        """Get executor status"""
        return {
            'initialized': self.initialized,
            'hyperliquid_connected': self.hyperliquid_exchange is not None,
            'bitget_connected': self.bitget_credentials is not None,
            'orders_count': len(self.order_history),
            'trades_count': len(self.trade_history)
        }
