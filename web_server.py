# web_server.py
# Web Dashboard Server for NVDA Arbitrage Bot
import asyncio
import json
import logging
from pathlib import Path
from datetime import datetime
import time

try:
    from aiohttp import web, WSMsgType
except ImportError:
    logging.warning("aiohttp not installed. Web dashboard will not be available.")
    web = None

logger = logging.getLogger(__name__)


class DateTimeEncoder(json.JSONEncoder):
    """JSON encoder that handles datetime objects"""
    def default(self, obj):
        if isinstance(obj, datetime):
            return obj.isoformat()
        if hasattr(obj, 'isoformat'):
            return obj.isoformat()
        return super().default(obj)


class WebDashboardServer:
    """Web Dashboard Server with real-time WebSocket updates"""
    
    def __init__(self, bot, host='0.0.0.0', port=8080):
        self.bot = bot
        self.host = host
        self.port = port
        self.app = None
        self.runner = None
        self.site = None
        self.ws_clients = set()
        self.update_task = None
        
        # Web directory path
        self.web_dir = Path(__file__).parent / "web"
    
    def setup_routes(self):
        """Setup HTTP and WebSocket routes"""
        if web is None:
            return
        
        self.app = web.Application()
        
        # Static files
        self.app.router.add_static('/static', self.web_dir)
        
        # Main page
        self.app.router.add_get('/', self.handle_index)
        
        # WebSocket endpoint
        self.app.router.add_get('/ws', self.handle_websocket)
        
        # API endpoints
        self.app.router.add_get('/api/status', self.handle_api_status)
        self.app.router.add_get('/api/spreads', self.handle_api_spreads)
        self.app.router.add_get('/api/positions', self.handle_api_positions)
        self.app.router.add_get('/api/portfolio', self.handle_api_portfolio)
        self.app.router.add_get('/api/stats', self.handle_api_stats)
    
    async def handle_index(self, request):
        """Serve main dashboard page"""
        index_file = self.web_dir / "index.html"
        if index_file.exists():
            return web.FileResponse(index_file)
        return web.Response(text="Dashboard not found", status=404)
    
    async def handle_websocket(self, request):
        """Handle WebSocket connections for real-time updates"""
        if web is None:
            return web.Response(text="Web server not available", status=503)
        
        ws = web.WebSocketResponse()
        await ws.prepare(request)
        
        # Add client
        self.ws_clients.add(ws)
        logger.info(f"WebSocket client connected. Total clients: {len(self.ws_clients)}")
        
        try:
            async for msg in ws:
                if msg.type == WSMsgType.TEXT:
                    try:
                        data = json.loads(msg.data)
                        await self.handle_ws_message(ws, data)
                    except json.JSONDecodeError:
                        pass
                elif msg.type == WSMsgType.ERROR:
                    logger.error(f"WebSocket error: {ws.exception()}")
                    break
        
        finally:
            self.ws_clients.discard(ws)
            logger.info(f"WebSocket client disconnected. Total clients: {len(self.ws_clients)}")
        
        return ws
    
    async def handle_ws_message(self, ws, data):
        """Handle incoming WebSocket messages"""
        msg_type = data.get('type', '')
        
        if msg_type == 'request_full_update':
            # Send full update
            payload = self.collect_dashboard_data()
            await self.send_to_client(ws, 'full_update', payload)
        
        elif msg_type == 'ping':
            await self.send_to_client(ws, 'pong', {'timestamp': time.time()})
        
        elif msg_type == 'close_position':
            # Close a specific position
            position_id = data.get('position_id')
            if position_id:
                success = await self.close_position(position_id)
                await self.send_to_client(ws, 'close_result', {
                    'position_id': position_id,
                    'success': success
                })
        
        elif msg_type == 'toggle_trading':
            # Toggle trading mode
            self.bot.trading_enabled = not getattr(self.bot, 'trading_enabled', True)
            await self.send_to_client(ws, 'trading_status', {
                'enabled': getattr(self.bot, 'trading_enabled', True)
            })
    
    async def close_position(self, position_id):
        """Close a specific position"""
        try:
            positions = self.bot.arb_engine.get_open_positions()
            for pos in positions:
                if pos.id == position_id:
                    # Execute close logic
                    if hasattr(self.bot, 'arb_engine'):
                        await self.bot.arb_engine.close_position(pos)
                        return True
            return False
        except Exception as e:
            logger.error(f"Error closing position {position_id}: {e}")
            return False
    
    def collect_dashboard_data(self):
        """Collect all data needed for dashboard display"""
        runtime = time.time() - self.bot.session_start
        
        # Trading mode
        mode = 'stopped'
        if self.bot.trading_mode.value == 'ACTIVE':
            mode = 'active'
        elif self.bot.trading_mode.value == 'PARTIAL':
            mode = 'partial'
        
        # Collect spreads
        spreads = {}
        try:
            if self.bot.bitget_ws and self.bot.hyper_ws:
                bitget_data = self.bot.bitget_ws.get_latest_data()
                hyper_data = self.bot.hyper_ws.get_latest_data()
                
                if bitget_data and hyper_data:
                    bitget_slippage = self.bot.bitget_ws.get_estimated_slippage() if self.bot.bitget_ws else None
                    hyper_slippage = self.bot.hyper_ws.get_estimated_slippage() if self.bot.hyper_ws else None
                    
                    calc_spreads = self.bot.arb_engine.calculate_spreads(
                        bitget_data, hyper_data, bitget_slippage, hyper_slippage
                    )
                    
                    if calc_spreads:
                        for direction, spread_data in calc_spreads.items():
                            dir_key = direction.value if hasattr(direction, 'value') else str(direction)
                            spreads[dir_key] = {
                                'gross_spread': spread_data.get('gross_spread', 0)
                            }
        except Exception as e:
            logger.debug(f"Error calculating spreads: {e}")
        
        # Exit spreads
        exit_spreads = {}
        try:
            if self.bot.bitget_ws and self.bot.hyper_ws:
                bitget_data = self.bot.bitget_ws.get_latest_data()
                hyper_data = self.bot.hyper_ws.get_latest_data()
                
                if bitget_data and hyper_data:
                    bitget_slippage = self.bot.bitget_ws.get_estimated_slippage() if self.bot.bitget_ws else None
                    hyper_slippage = self.bot.hyper_ws.get_estimated_slippage() if self.bot.hyper_ws else None
                    
                    exit_calc = self.bot.arb_engine.calculate_exit_spread_for_market(
                        bitget_data, hyper_data, bitget_slippage, hyper_slippage
                    )
                    
                    if exit_calc:
                        for direction, spread in exit_calc.items():
                            dir_key = direction.value if hasattr(direction, 'value') else str(direction)
                            exit_spreads[dir_key] = spread
        except Exception as e:
            logger.debug(f"Error calculating exit spreads: {e}")
        
        # Portfolio
        portfolio = self.bot.paper_executor.get_portfolio() if hasattr(self.bot, 'paper_executor') else {}
        
        # Total value and PnL
        total_value = 0
        pnl = 0
        try:
            bitget_data = self.bot.bitget_ws.get_latest_data() if self.bot.bitget_ws else None
            usdt = portfolio.get('USDT', 0)
            nvda = portfolio.get('NVDA', 0)
            price = bitget_data.get('bid', 170) if bitget_data else 170
            total_value = usdt + nvda * price
            pnl = total_value - 1000.0
        except Exception:
            pass
        
        # Positions
        positions = []
        try:
            open_positions = self.bot.arb_engine.get_open_positions() if hasattr(self.bot, 'arb_engine') else []
            for pos in open_positions:
                positions.append({
                    'id': pos.id,
                    'direction': pos.direction.value if hasattr(pos.direction, 'value') else str(pos.direction),
                    'exit_spread': pos.current_exit_spread,
                    'exit_target': pos.exit_target,
                    'age': pos.get_age_formatted() if hasattr(pos, 'get_age_formatted') else '--',
                    'should_close': pos.should_close() if hasattr(pos, 'should_close') else False
                })
        except Exception:
            pass
        
        return {
            'timestamp': datetime.now().strftime('%H:%M:%S'),
            'runtime': runtime,
            'trading_mode': mode,
            'bitget_healthy': self.bot.bitget_healthy,
            'hyper_healthy': self.bot.hyper_healthy,
            'session_stats': self.bot.session_stats,
            'bitget_data': self.bot.bitget_ws.get_latest_data() if self.bot.bitget_ws else None,
            'hyper_data': self.bot.hyper_ws.get_latest_data() if self.bot.hyper_ws else None,
            'spreads': spreads,
            'exit_spreads': exit_spreads,
            'best_entry_spread': self.bot.best_spreads_session.get('best_entry_spread', 0),
            'best_entry_direction': self.bot.best_spreads_session.get('best_entry_direction'),
            'best_entry_time': self.bot.best_spreads_session.get('best_entry_time'),
            'best_exit_overall': self.bot.best_spreads_session.get('best_exit_spread_overall', float('inf')),
            'best_exit_direction': self.bot.best_spreads_session.get('best_exit_direction'),
            'best_exit_time': self.bot.best_spreads_session.get('best_exit_time'),
            'portfolio': portfolio,
            'total_value': total_value,
            'pnl': pnl,
            'positions': positions,
            'config': self.bot.config
        }
    
    async def send_to_client(self, ws, msg_type, payload):
        """Send message to a specific WebSocket client"""
        if not ws.closed:
            try:
                message = json.dumps({'type': msg_type, 'payload': payload}, cls=DateTimeEncoder)
                await ws.send_str(message)
            except Exception as e:
                logger.error(f"Error sending to client: {e}")
    
    async def broadcast(self, msg_type, payload):
        """Broadcast message to all connected clients"""
        message = json.dumps({'type': msg_type, 'payload': payload}, cls=DateTimeEncoder)
        
        disconnected = set()
        for ws in self.ws_clients:
            if not ws.closed:
                try:
                    await ws.send_str(message)
                except Exception as e:
                    logger.error(f"Error broadcasting to client: {e}")
                    disconnected.add(ws)
        
        # Clean up disconnected clients
        for ws in disconnected:
            self.ws_clients.discard(ws)
    
    async def start_updates(self):
        """Start periodic updates to all clients"""
        if self.update_task is None or self.update_task.done():
            self.update_task = asyncio.create_task(self._periodic_updates())
    
    async def _periodic_updates(self):
        """Send periodic updates to all connected clients"""
        while True:
            try:
                if self.ws_clients:
                    payload = self.collect_dashboard_data()
                    await self.broadcast('full_update', payload)
                await asyncio.sleep(1.0)  # Update every second
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in periodic updates: {e}")
                await asyncio.sleep(5.0)
    
    async def start(self):
        """Start the web server"""
        if web is None:
            logger.error("aiohttp not installed. Cannot start web server.")
            return False
        
        self.setup_routes()
        
        self.runner = web.AppRunner(self.app)
        await self.runner.setup()
        
        self.site = web.TCPSite(self.runner, self.host, self.port)
        await self.site.start()
        
        logger.info(f"🌐 Web Dashboard available at http://{self.host}:{self.port}")
        logger.info(f"📊 Open http://{self.host}:{self.port} in your browser")
        
        # Start periodic updates
        await self.start_updates()
        
        return True
    
    async def stop(self):
        """Stop the web server"""
        if self.runner:
            await self.runner.cleanup()
            logger.info("Web Dashboard server stopped")
    
    # API Handlers
    async def handle_api_status(self, request):
        """API endpoint for status"""
        data = self.collect_dashboard_data()
        return web.json_response({'status': 'ok', 'data': data})
    
    async def handle_api_spreads(self, request):
        """API endpoint for spreads"""
        spreads = {}
        try:
            if self.bot.bitget_ws and self.bot.hyper_ws:
                bitget_data = self.bot.bitget_ws.get_latest_data()
                hyper_data = self.bot.hyper_ws.get_latest_data()
                
                if bitget_data and hyper_data:
                    calc_spreads = self.bot.arb_engine.calculate_spreads(bitget_data, hyper_data)
                    if calc_spreads:
                        for direction, spread_data in calc_spreads.items():
                            dir_key = direction.value if hasattr(direction, 'value') else str(direction)
                            spreads[dir_key] = spread_data
        except Exception as e:
            return web.json_response({'error': str(e)}, status=500)
        
        return web.json_response({'spreads': spreads})
    
    async def handle_api_positions(self, request):
        """API endpoint for positions"""
        positions = []
        try:
            open_positions = self.bot.arb_engine.get_open_positions() if hasattr(self.bot, 'arb_engine') else []
            for pos in open_positions:
                positions.append({
                    'id': pos.id,
                    'direction': pos.direction.value if hasattr(pos.direction, 'value') else str(pos.direction),
                    'size': pos.size,
                    'entry_price': pos.entry_price,
                    'current_exit_spread': pos.current_exit_spread,
                    'exit_target': pos.exit_target,
                    'age': pos.get_age_formatted() if hasattr(pos, 'get_age_formatted') else None,
                    'statistics': pos.get_statistics() if hasattr(pos, 'get_statistics') else {}
                })
        except Exception as e:
            return web.json_response({'error': str(e)}, status=500)
        
        return web.json_response({'positions': positions})
    
    async def handle_api_portfolio(self, request):
        """API endpoint for portfolio"""
        portfolio = self.bot.paper_executor.get_portfolio() if hasattr(self.bot, 'paper_executor') else {}
        return web.json_response({'portfolio': portfolio})
    
    async def handle_api_stats(self, request):
        """API endpoint for session stats"""
        return web.json_response({'session_stats': self.bot.session_stats})


def integrate_web_dashboard(bot, host='0.0.0.0', port=8080):
    """
    Integrate web dashboard with the trading bot.
    Call this after bot initialization to add web server capability.
    
    Args:
        bot: NVDAFuturesArbitrageBot instance
        host: Web server host (default: 0.0.0.0)
        port: Web server port (default: 8080)
    
    Returns:
        WebDashboardServer instance or None if aiohttp not available
    """
    if web is None:
        logger.warning("Web dashboard requires aiohttp. Install with: pip install aiohttp")
        return None
    
    server = WebDashboardServer(bot, host, port)
    
    # Store reference in bot for access from other modules
    bot.web_dashboard = server
    
    return server
