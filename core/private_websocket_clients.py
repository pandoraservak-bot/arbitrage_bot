# Private WebSocket clients for account data streaming
import asyncio
import websockets
import json
import time
import logging
import hmac
import hashlib
import base64
import os
from typing import Dict, Optional, Callable

logger = logging.getLogger(__name__)


class HyperliquidPrivateWS:
    """Hyperliquid private WebSocket for account data (webData2)"""
    
    def __init__(self, account_address: str):
        self.account_address = account_address
        self.ws_url = "wss://api.hyperliquid.xyz/ws"
        self.ws = None
        self.connected = False
        self.running = False
        self._task = None
        
        self.account_data = {
            'connected': False,
            'equity': 0,
            'available': 0,
            'margin_used': 0,
            'nvda_position': None,
            'last_update': 0
        }
        
        self.on_update: Optional[Callable] = None
    
    async def connect(self):
        """Connect and subscribe to webData2"""
        self.running = True
        
        while self.running:
            try:
                logger.info(f"Connecting to Hyperliquid private WS...")
                
                async with websockets.connect(self.ws_url) as ws:
                    self.ws = ws
                    self.connected = True
                    self.account_data['connected'] = True
                    logger.info("Hyperliquid private WS connected")
                    
                    subscribe_msg = {
                        "method": "subscribe",
                        "subscription": {
                            "type": "webData2",
                            "user": self.account_address
                        }
                    }
                    await ws.send(json.dumps(subscribe_msg))
                    logger.info(f"Subscribed to Hyperliquid webData2 for {self.account_address[:10]}...")
                    
                    await self._receive_loop(ws)
                    
            except websockets.exceptions.ConnectionClosed as e:
                logger.warning(f"Hyperliquid private WS disconnected: {e}")
                self.connected = False
                self.account_data['connected'] = False
            except Exception as e:
                logger.error(f"Hyperliquid private WS error: {e}")
                self.connected = False
                self.account_data['connected'] = False
            
            if self.running:
                logger.info("Reconnecting Hyperliquid private WS in 3s...")
                await asyncio.sleep(3)
    
    async def _receive_loop(self, ws):
        """Process incoming messages"""
        async for message in ws:
            try:
                data = json.loads(message)
                await self._handle_message(data)
            except json.JSONDecodeError as e:
                logger.error(f"Hyperliquid WS JSON error: {e}")
            except Exception as e:
                logger.error(f"Hyperliquid WS message error: {e}")
    
    async def _handle_message(self, data: Dict):
        """Handle incoming webData2 message"""
        channel = data.get('channel')
        
        if channel == 'webData2':
            web_data = data.get('data', {})
            clearinghouse = web_data.get('clearinghouseState', {})
            
            margin_summary = clearinghouse.get('marginSummary', {})
            
            try:
                account_value = float(margin_summary.get('accountValue', 0) or 0)
                total_margin_used = float(margin_summary.get('totalMarginUsed', 0) or 0)
                withdrawable = float(clearinghouse.get('withdrawable', 0) or 0)
            except (ValueError, TypeError) as e:
                logger.warning(f"Hyperliquid parse error: {e}")
                return
            
            nvda_position = None
            for pos in clearinghouse.get('assetPositions', []):
                position = pos.get('position', {})
                if position.get('coin') == 'NVDA':
                    try:
                        nvda_position = {
                            'size': float(position.get('szi', 0) or 0),
                            'entry_px': float(position.get('entryPx', 0) or 0),
                            'unrealized_pnl': float(position.get('unrealizedPnl', 0) or 0),
                            'liquidation_px': position.get('liquidationPx')
                        }
                    except (ValueError, TypeError):
                        nvda_position = None
                    break
            
            self.account_data = {
                'connected': True,
                'equity': account_value,
                'available': withdrawable,
                'margin_used': total_margin_used,
                'nvda_position': nvda_position,
                'last_update': time.time()
            }
            
            if self.on_update:
                await self.on_update('hyperliquid', self.account_data)
        
        elif channel == 'subscriptionResponse':
            logger.debug(f"Hyperliquid subscription confirmed: {data}")
    
    def get_account_data(self) -> Dict:
        """Get latest account data"""
        return self.account_data.copy()
    
    async def start(self):
        """Start WebSocket connection in background"""
        self._task = asyncio.create_task(self.connect())
    
    async def stop(self):
        """Stop WebSocket connection"""
        self.running = False
        self.connected = False
        self.account_data['connected'] = False
        
        if self.ws:
            await self.ws.close()
        
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass


class BitgetPrivateWS:
    """Bitget private WebSocket for account/positions data"""
    
    def __init__(self, api_key: str, secret_key: str, passphrase: str):
        self.api_key = api_key
        self.secret_key = secret_key
        self.passphrase = passphrase
        self.ws_url = "wss://ws.bitget.com/v2/ws/private"
        self.ws = None
        self.connected = False
        self.running = False
        self._task = None
        self._ping_task = None
        
        self.account_data = {
            'connected': False,
            'equity': 0,
            'available': 0,
            'margin_used': 0,
            'nvda_position': None,
            'last_update': 0
        }
        
        self.on_update: Optional[Callable] = None
    
    def _generate_signature(self, timestamp: str) -> str:
        """Generate login signature (timestamp in seconds)"""
        message = timestamp + "GET" + "/user/verify"
        signature = hmac.new(
            self.secret_key.encode('utf-8'),
            message.encode('utf-8'),
            hashlib.sha256
        ).digest()
        return base64.b64encode(signature).decode('utf-8')
    
    async def connect(self):
        """Connect, authenticate and subscribe"""
        self.running = True
        
        while self.running:
            try:
                logger.info("Connecting to Bitget private WS...")
                
                async with websockets.connect(self.ws_url) as ws:
                    self.ws = ws
                    
                    timestamp = str(int(time.time()))
                    signature = self._generate_signature(timestamp)
                    
                    login_msg = {
                        "op": "login",
                        "args": [{
                            "apiKey": self.api_key,
                            "passphrase": self.passphrase,
                            "timestamp": timestamp,
                            "sign": signature
                        }]
                    }
                    await ws.send(json.dumps(login_msg))
                    logger.debug(f"Bitget login sent with timestamp: {timestamp}")
                    
                    response = await asyncio.wait_for(ws.recv(), timeout=10)
                    login_result = json.loads(response)
                    logger.debug(f"Bitget login response: {login_result}")
                    
                    if login_result.get('event') == 'login' and str(login_result.get('code')) == '0':
                        logger.info("Bitget private WS authenticated")
                        self.connected = True
                        self.account_data['connected'] = True
                        
                        subscribe_msg = {
                            "op": "subscribe",
                            "args": [
                                {
                                    "instType": "USDT-FUTURES",
                                    "channel": "account",
                                    "coin": "default"
                                },
                                {
                                    "instType": "USDT-FUTURES",
                                    "channel": "positions",
                                    "instId": "default"
                                }
                            ]
                        }
                        await ws.send(json.dumps(subscribe_msg))
                        logger.info("Subscribed to Bitget account and positions")
                        
                        self._ping_task = asyncio.create_task(self._ping_loop(ws))
                        
                        await self._receive_loop(ws)
                    else:
                        error_code = login_result.get('code', 'unknown')
                        error_msg = login_result.get('msg', login_result)
                        logger.error(f"Bitget login failed: code={error_code}, msg={error_msg}")
                        self.connected = False
                        self.account_data['connected'] = False
                        await asyncio.sleep(5)
                    
            except websockets.exceptions.ConnectionClosed as e:
                logger.warning(f"Bitget private WS disconnected: {e}")
                self.connected = False
                self.account_data['connected'] = False
            except Exception as e:
                logger.error(f"Bitget private WS error: {e}")
                self.connected = False
                self.account_data['connected'] = False
            finally:
                if self._ping_task:
                    self._ping_task.cancel()
            
            if self.running:
                logger.info("Reconnecting Bitget private WS in 3s...")
                await asyncio.sleep(3)
    
    async def _ping_loop(self, ws):
        """Send ping every 25 seconds to keep connection alive"""
        while self.running:
            try:
                await asyncio.sleep(25)
                await ws.send("ping")
            except Exception:
                break
    
    async def _receive_loop(self, ws):
        """Process incoming messages"""
        async for message in ws:
            if message == "pong":
                continue
            
            try:
                data = json.loads(message)
                await self._handle_message(data)
            except json.JSONDecodeError:
                if message != "pong":
                    logger.debug(f"Bitget non-JSON message: {message}")
            except Exception as e:
                logger.error(f"Bitget WS message error: {e}")
    
    async def _handle_message(self, data: Dict):
        """Handle incoming account/positions message"""
        action = data.get('action')
        arg = data.get('arg', {})
        channel = arg.get('channel')
        msg_data = data.get('data', [])
        
        if channel == 'account':
            for item in msg_data:
                margin_coin = item.get('marginCoin')
                if margin_coin == 'USDT':
                    self.account_data['equity'] = float(item.get('usdtEquity', item.get('equity', 0)))
                    self.account_data['available'] = float(item.get('crossedMaxAvailable', item.get('available', 0)))
                    self.account_data['margin_used'] = float(item.get('crossedMarginSize', item.get('frozen', 0)))
                    self.account_data['last_update'] = time.time()
                    
                    if self.on_update:
                        await self.on_update('bitget', self.account_data)
        
        elif channel == 'positions':
            for item in msg_data:
                inst_id = item.get('instId', '')
                if 'NVDA' in inst_id:
                    size = float(item.get('total', 0))
                    if item.get('holdSide') == 'short':
                        size = -size
                    
                    self.account_data['nvda_position'] = {
                        'size': size,
                        'entry_px': float(item.get('openPriceAvg', 0)),
                        'unrealized_pnl': float(item.get('unrealizedPL', 0)),
                        'liquidation_px': item.get('liquidationPrice')
                    }
                    self.account_data['last_update'] = time.time()
                    
                    if self.on_update:
                        await self.on_update('bitget', self.account_data)
        
        elif data.get('event') == 'subscribe':
            logger.debug(f"Bitget subscription confirmed: {arg}")
    
    def get_account_data(self) -> Dict:
        """Get latest account data"""
        return self.account_data.copy()
    
    async def start(self):
        """Start WebSocket connection in background"""
        self._task = asyncio.create_task(self.connect())
    
    async def stop(self):
        """Stop WebSocket connection"""
        self.running = False
        self.connected = False
        self.account_data['connected'] = False
        
        if self._ping_task:
            self._ping_task.cancel()
        
        if self.ws:
            await self.ws.close()
        
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass


class PrivateWSManager:
    """Manager for private WebSocket connections to both exchanges"""
    
    def __init__(self):
        self.hyperliquid_ws: Optional[HyperliquidPrivateWS] = None
        self.bitget_ws: Optional[BitgetPrivateWS] = None
        self.running = False
        
        self._hl_data = {
            'connected': False,
            'equity': 0,
            'available': 0,
            'margin_used': 0,
            'nvda_position': None
        }
        self._bg_data = {
            'connected': False,
            'equity': 0,
            'available': 0,
            'margin_used': 0,
            'nvda_position': None
        }
        
        self.on_portfolio_update: Optional[Callable] = None
    
    async def initialize(self) -> bool:
        """Initialize WebSocket connections based on available credentials"""
        from config import API_CONFIG
        
        hl_success = False
        bg_success = False
        
        hl_address = os.environ.get('HYPERLIQUID_ACCOUNT_ADDRESS') or API_CONFIG.get('HYPERLIQUID_ACCOUNT_ADDRESS')
        hl_secret = os.environ.get('HYPERLIQUID_SECRET_KEY') or API_CONFIG.get('HYPERLIQUID_SECRET_KEY')
        
        if hl_address or hl_secret:
            if not hl_address and hl_secret:
                try:
                    from eth_account import Account
                    wallet = Account.from_key(hl_secret)
                    hl_address = wallet.address
                except Exception as e:
                    logger.error(f"Failed to derive HL address: {e}")
            
            if hl_address:
                self.hyperliquid_ws = HyperliquidPrivateWS(hl_address)
                self.hyperliquid_ws.on_update = self._on_exchange_update
                hl_success = True
                logger.info(f"Hyperliquid private WS initialized for {hl_address[:10]}...")
        
        bg_key = os.environ.get('BITGET_API_KEY') or API_CONFIG.get('BITGET_API_KEY')
        bg_secret = os.environ.get('BITGET_SECRET_KEY') or API_CONFIG.get('BITGET_SECRET_KEY')
        bg_pass = os.environ.get('BITGET_PASSPHRASE') or API_CONFIG.get('BITGET_PASSPHRASE')
        
        if all([bg_key, bg_secret, bg_pass]):
            self.bitget_ws = BitgetPrivateWS(bg_key, bg_secret, bg_pass)
            self.bitget_ws.on_update = self._on_exchange_update
            bg_success = True
            logger.info("Bitget private WS initialized")
        
        return hl_success or bg_success
    
    async def _on_exchange_update(self, exchange: str, data: Dict):
        """Called when exchange data updates"""
        if exchange == 'hyperliquid':
            self._hl_data = data
        elif exchange == 'bitget':
            self._bg_data = data
        
        if self.on_portfolio_update:
            portfolio = self.get_portfolio()
            await self.on_portfolio_update(portfolio)
    
    def get_portfolio(self) -> Dict:
        """Get combined portfolio from WebSocket data"""
        hl = self._hl_data
        bg = self._bg_data
        
        hl_equity = hl.get('equity', 0) if hl.get('connected') else 0
        bg_equity = bg.get('equity', 0) if bg.get('connected') else 0
        
        hl_pnl = 0
        bg_pnl = 0
        if hl.get('nvda_position'):
            hl_pnl = hl['nvda_position'].get('unrealized_pnl', 0)
        if bg.get('nvda_position'):
            bg_pnl = bg['nvda_position'].get('unrealized_pnl', 0)
        
        return {
            'hyperliquid': hl,
            'bitget': bg,
            'combined': {
                'total_equity': hl_equity + bg_equity,
                'total_pnl': hl_pnl + bg_pnl
            },
            'timestamp': time.time()
        }
    
    async def start(self):
        """Start all WebSocket connections"""
        self.running = True
        
        tasks = []
        if self.hyperliquid_ws:
            tasks.append(self.hyperliquid_ws.start())
        if self.bitget_ws:
            tasks.append(self.bitget_ws.start())
        
        if tasks:
            await asyncio.gather(*tasks)
    
    async def stop(self):
        """Stop all WebSocket connections"""
        self.running = False
        
        tasks = []
        if self.hyperliquid_ws:
            tasks.append(self.hyperliquid_ws.stop())
        if self.bitget_ws:
            tasks.append(self.bitget_ws.stop())
        
        if tasks:
            await asyncio.gather(*tasks)
        
        logger.info("Private WebSocket connections stopped")
    
    def is_connected(self) -> Dict:
        """Check connection status"""
        return {
            'hyperliquid': self.hyperliquid_ws.connected if self.hyperliquid_ws else False,
            'bitget': self.bitget_ws.connected if self.bitget_ws else False
        }
