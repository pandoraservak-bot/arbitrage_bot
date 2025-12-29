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
        self.bitget_credentials = None
        self.bitget_base_url = "https://api.bitget.com"
        
        self.initialized = False
        self.hyperliquid_connected = False
        self.bitget_connected = False
        self.order_history = []
        self.trade_history = []
        
        self.hyperliquid_symbol = "NVDA"
        self.bitget_symbol = "NVDAUSDT"
        
        self.private_ws_manager = None
        self._ws_portfolio_callback = None
        
    async def initialize(self) -> bool:
        """Initialize exchange connections"""
        try:
            hl_success = await self._init_hyperliquid()
            bg_success = await self._init_bitget()
            
            self.hyperliquid_connected = hl_success
            self.bitget_connected = bg_success
            self.initialized = hl_success or bg_success
            
            if hl_success and bg_success:
                logger.info("Live Trading Executor initialized successfully (both exchanges)")
            elif hl_success:
                logger.warning("Live Trading: Only Hyperliquid connected. Check Bitget API keys")
            elif bg_success:
                logger.warning("Live Trading: Only Bitget connected. Check Hyperliquid API keys")
            else:
                logger.warning("Live Trading: No exchanges connected. Check API keys")
            
            await self._init_private_websockets()
                    
            return self.initialized
            
        except Exception as e:
            logger.error(f"Error initializing Live Executor: {e}")
            return False
    
    async def _init_private_websockets(self):
        """Initialize private WebSocket connections for real-time account data"""
        try:
            from core.private_websocket_clients import PrivateWSManager
            
            self.private_ws_manager = PrivateWSManager()
            ws_init = await self.private_ws_manager.initialize()
            
            if ws_init:
                self.private_ws_manager.on_portfolio_update = self._on_ws_portfolio_update
                await self.private_ws_manager.start()
                logger.info("Private WebSocket connections started for real-time account data")
            else:
                logger.warning("No private WebSocket connections initialized (missing credentials)")
                
        except Exception as e:
            logger.error(f"Error initializing private WebSockets: {e}")
    
    async def _on_ws_portfolio_update(self, portfolio: Dict):
        """Called when WebSocket receives new portfolio data"""
        if self._ws_portfolio_callback:
            await self._ws_portfolio_callback(portfolio)
    
    def set_portfolio_callback(self, callback):
        """Set callback for portfolio updates from WebSocket"""
        self._ws_portfolio_callback = callback
    
    async def _init_hyperliquid(self) -> bool:
        """Initialize Hyperliquid SDK connection"""
        try:
            from hyperliquid.info import Info
            from hyperliquid.exchange import Exchange
            from hyperliquid.utils import constants
            from eth_account import Account
            
            from config import API_CONFIG
            secret_key = os.environ.get('HYPERLIQUID_SECRET_KEY') or API_CONFIG.get('HYPERLIQUID_SECRET_KEY')
            account_address = os.environ.get('HYPERLIQUID_ACCOUNT_ADDRESS') or API_CONFIG.get('HYPERLIQUID_ACCOUNT_ADDRESS')
            
            if not secret_key:
                logger.warning("HYPERLIQUID_SECRET_KEY not set")
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
            
            from config import API_CONFIG
            api_key = os.environ.get('BITGET_API_KEY') or API_CONFIG.get('BITGET_API_KEY')
            secret_key = os.environ.get('BITGET_SECRET_KEY') or API_CONFIG.get('BITGET_SECRET_KEY')
            passphrase = os.environ.get('BITGET_PASSPHRASE') or API_CONFIG.get('BITGET_PASSPHRASE')
            
            if not all([api_key, secret_key, passphrase]):
                logger.warning("Bitget API credentials not fully set")
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
            
            response = await asyncio.to_thread(
                self._bitget_request, 'POST', '/api/v2/mix/order/place-order', None, params
            )
            
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
    
    async def execute_fok_pair(self, buy_order: Dict, sell_order: Dict, tag: str = "") -> Dict:
        """Execute pair of orders (buy on one exchange, sell on another) - alias for execute_fok_pair_async"""
        return await self.execute_fok_pair_async(buy_order, sell_order, tag)
    
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
            response = await asyncio.to_thread(
                self._bitget_request, 'GET', '/api/v2/mix/position/single-position', {
                    'symbol': self.bitget_symbol,
                    'productType': 'USDT-FUTURES',
                    'marginCoin': 'USDT'
                }
            )
            
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
    
    async def get_hyperliquid_balance(self) -> Dict:
        """Get Hyperliquid account balance and equity"""
        if not self.hyperliquid_info:
            return {'connected': False}
        
        try:
            account_address = os.environ.get('HYPERLIQUID_ACCOUNT_ADDRESS')
            if not account_address and self.hyperliquid_exchange:
                from eth_account import Account
                secret_key = os.environ.get('HYPERLIQUID_SECRET_KEY')
                if secret_key:
                    wallet = Account.from_key(secret_key)
                    account_address = wallet.address
            
            if not account_address:
                return {'connected': False, 'error': 'No account address'}
            
            user_state = await asyncio.to_thread(
                self.hyperliquid_info.user_state, account_address
            )
            
            if user_state:
                margin_summary = user_state.get('marginSummary', {})
                account_value = float(margin_summary.get('accountValue', 0))
                total_margin_used = float(margin_summary.get('totalMarginUsed', 0))
                total_ntl_pos = float(margin_summary.get('totalNtlPos', 0))
                
                withdrawable = user_state.get('withdrawable', '0')
                
                nvda_position = None
                for pos in user_state.get('assetPositions', []):
                    if pos.get('position', {}).get('coin') == self.hyperliquid_symbol:
                        position_data = pos.get('position', {})
                        nvda_position = {
                            'size': float(position_data.get('szi', 0)),
                            'entry_px': float(position_data.get('entryPx', 0)),
                            'unrealized_pnl': float(position_data.get('unrealizedPnl', 0)),
                            'liquidation_px': position_data.get('liquidationPx')
                        }
                        break
                
                return {
                    'connected': True,
                    'balance': account_value,
                    'equity': account_value,
                    'available': float(withdrawable),
                    'margin_used': total_margin_used,
                    'total_position_value': abs(total_ntl_pos),
                    'nvda_position': nvda_position
                }
            
            return {'connected': True, 'balance': 0, 'equity': 0}
            
        except Exception as e:
            logger.error(f"Error getting Hyperliquid balance: {e}")
            return {'connected': False, 'error': str(e)}
    
    async def get_bitget_balance(self) -> Dict:
        """Get Bitget account balance and equity"""
        if not self.bitget_credentials:
            return {'connected': False}
        
        try:
            response = await asyncio.to_thread(
                self._bitget_request, 'GET', '/api/v2/mix/account/account', {
                    'symbol': self.bitget_symbol,
                    'productType': 'USDT-FUTURES',
                    'marginCoin': 'USDT'
                }
            )
            
            if response.get('code') == '00000':
                data = response.get('data', {})
                if isinstance(data, list) and len(data) > 0:
                    data = data[0]
                
                equity = float(data.get('usdtEquity', 0))
                available = float(data.get('crossedMaxAvailable', data.get('available', 0)))
                margin_used = float(data.get('crossedMarginSize', data.get('locked', 0)))
                unrealized_pnl = float(data.get('unrealizedPL', 0))
                
                pos_response = await asyncio.to_thread(
                    self._bitget_request, 'GET', '/api/v2/mix/position/single-position', {
                        'symbol': self.bitget_symbol,
                        'productType': 'USDT-FUTURES',
                        'marginCoin': 'USDT'
                    }
                )
                
                nvda_position = None
                if pos_response.get('code') == '00000':
                    pos_data = pos_response.get('data', [])
                    if pos_data:
                        pos = pos_data[0] if isinstance(pos_data, list) else pos_data
                        size = float(pos.get('total', 0))
                        if pos.get('holdSide') == 'short':
                            size = -size
                        nvda_position = {
                            'size': size,
                            'entry_px': float(pos.get('openPriceAvg', 0)),
                            'unrealized_pnl': float(pos.get('unrealizedPL', 0)),
                            'liquidation_px': pos.get('liquidationPrice')
                        }
                
                return {
                    'connected': True,
                    'balance': equity - unrealized_pnl,
                    'equity': equity,
                    'available': available,
                    'margin_used': margin_used,
                    'unrealized_pnl': unrealized_pnl,
                    'nvda_position': nvda_position
                }
            
            return {'connected': False, 'error': response.get('msg', 'Unknown error')}
            
        except Exception as e:
            logger.error(f"Error getting Bitget balance: {e}")
            return {'connected': False, 'error': str(e)}
    
    async def get_live_portfolio(self) -> Dict:
        """Get combined portfolio from both exchanges"""
        if self.private_ws_manager and self.private_ws_manager.running:
            portfolio = self.private_ws_manager.get_portfolio()
            if portfolio.get('hyperliquid', {}).get('connected') or portfolio.get('bitget', {}).get('connected'):
                return portfolio
        
        hl_balance, bg_balance = await asyncio.gather(
            self.get_hyperliquid_balance(),
            self.get_bitget_balance()
        )
        
        hl_equity = hl_balance.get('equity', 0) if hl_balance.get('connected') else 0
        bg_equity = bg_balance.get('equity', 0) if bg_balance.get('connected') else 0
        
        hl_pnl = 0
        bg_pnl = 0
        if hl_balance.get('nvda_position'):
            hl_pnl = hl_balance['nvda_position'].get('unrealized_pnl', 0)
        if bg_balance.get('nvda_position'):
            bg_pnl = bg_balance['nvda_position'].get('unrealized_pnl', 0)
        
        return {
            'hyperliquid': hl_balance,
            'bitget': bg_balance,
            'combined': {
                'total_equity': hl_equity + bg_equity,
                'total_pnl': hl_pnl + bg_pnl
            },
            'timestamp': time.time()
        }
    
    def get_ws_portfolio(self) -> Optional[Dict]:
        """Get portfolio from WebSocket data (non-async, for real-time updates)"""
        if self.private_ws_manager:
            return self.private_ws_manager.get_portfolio()
        return None
    
    def get_ws_connection_status(self) -> Dict:
        """Get WebSocket connection status"""
        if self.private_ws_manager:
            return self.private_ws_manager.is_connected()
        return {'hyperliquid': False, 'bitget': False}
    
    def is_ready(self) -> bool:
        """Check if executor is ready for trading"""
        return self.initialized
    
    def get_status(self) -> Dict:
        """Get executor status"""
        return {
            'initialized': self.initialized,
            'hyperliquid_connected': self.hyperliquid_connected,
            'bitget_connected': self.bitget_connected,
            'orders_count': len(self.order_history),
            'trades_count': len(self.trade_history)
        }
    
    async def shutdown(self):
        """Shutdown executor and WebSocket connections"""
        self._ws_portfolio_callback = None
        
        if self.private_ws_manager:
            await self.private_ws_manager.stop()
            self.private_ws_manager = None
        
        self.initialized = False
        self.hyperliquid_connected = False
        self.bitget_connected = False
        logger.info("Live executor shutdown complete")
