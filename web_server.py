# web_server.py
# Web Dashboard Server for NVDA Arbitrage Bot
import asyncio
import json
import logging
import math
import re
from pathlib import Path
from datetime import datetime
from typing import Dict, Optional, Any
import time

try:
    from aiohttp import web, WSMsgType, ClientSession
except ImportError:
    logging.warning("aiohttp not installed. Web dashboard will not be available.")
    web = None
    ClientSession = None

logger = logging.getLogger(__name__)

_bitget_market_status_cache = {
    'status': 'unknown',
    'last_check': 0,
    'off_time': None,
    'open_time': None
}

async def check_bitget_market_status() -> dict:
    """Check Bitget NVDA futures market status (normal/maintain)"""
    global _bitget_market_status_cache
    
    now = time.time()
    if now - _bitget_market_status_cache['last_check'] < 60:
        return _bitget_market_status_cache
    
    try:
        if ClientSession is None:
            return _bitget_market_status_cache
            
        async with ClientSession() as session:
            url = "https://api.bitget.com/api/v2/mix/market/contracts"
            params = {"productType": "USDT-FUTURES", "symbol": "NVDAUSDT"}
            
            async with session.get(url, params=params, timeout=5) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    if data.get('code') == '00000' and data.get('data'):
                        contract = data['data'][0]
                        _bitget_market_status_cache = {
                            'status': contract.get('symbolStatus', 'unknown'),
                            'last_check': now,
                            'off_time': contract.get('offTime'),
                            'open_time': contract.get('openTime')
                        }
    except Exception as e:
        logger.debug(f"Error checking Bitget market status: {e}")
    
    return _bitget_market_status_cache


# Content Security Policy Middleware
@web.middleware
async def csp_middleware(request, handler):
    """Add Content Security Policy headers to all responses"""
    response = await handler(request)
    
    # CSP policy configuration
    # unsafe-eval is required for Chart.js and chartjs-plugin-zoom which use eval internally
    # chartjs-plugin-zoom uses Function constructor for dynamic function creation
    csp_policy = (
        "default-src 'self'; "
        "script-src 'self' 'unsafe-inline' 'unsafe-eval' https://cdn.jsdelivr.net blob:; "
        "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
        "img-src 'self' data: blob:; "
        "font-src 'self' https://fonts.gstatic.com; "
        "connect-src 'self' ws: wss: https://cdn.jsdelivr.net https://fonts.googleapis.com https://fonts.gstatic.com; "
        "worker-src 'self' blob:; "
        "base-uri 'self'; "
        "form-action 'self'"
    )
    
    response.headers['Content-Security-Policy'] = csp_policy
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['X-XSS-Protection'] = '1; mode=block'
    
    # Disable caching for ALL responses to ensure updates are visible immediately
    response.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate, max-age=0'
    response.headers['Pragma'] = 'no-cache'
    response.headers['Expires'] = '0'
    response.headers['ETag'] = ''
    response.headers['Last-Modified'] = ''
    
    return response


class DateTimeEncoder(json.JSONEncoder):
    """JSON encoder that handles datetime objects"""
    def default(self, obj):
        if isinstance(obj, datetime):
            return obj.isoformat()
        if hasattr(obj, 'isoformat'):
            return obj.isoformat()
        return super().default(obj)


def save_config_to_file(config_updates: Dict[str, Any]) -> Dict[str, Any]:
    """
    Save configuration updates to config.py file.
    
    Args:
        config_updates: Dictionary with keys like 'MIN_SPREAD_ENTER', 'MIN_SPREAD_EXIT', etc.
    
    Returns:
        Dictionary with 'success' boolean and 'message' or 'error' string
    """
    try:
        # Get the config file path
        config_path = Path(__file__).parent / "config.py"
        
        if not config_path.exists():
            return {
                'success': False,
                'error': 'config.py file not found'
            }
        
        # Read the current config file
        with open(config_path, 'r', encoding='utf-8') as f:
            config_content = f.read()
        
        original_content = config_content
        updated_fields = []
        
        # Map of config keys to their regex patterns and replacement templates
        # Format: key -> (pattern, replacement_template, config_section)
        config_mappings = {
            'MIN_SPREAD_ENTER': (
                r"('MIN_SPREAD_ENTER'\s*:\s*)([0-9.-]+)",
                r"\g<1>{value}",
                "TRADING_CONFIG"
            ),
            'MIN_SPREAD_EXIT': (
                r"('MIN_SPREAD_EXIT'\s*:\s*)([0-9.-]+)",
                r"\g<1>{value}",
                "TRADING_CONFIG"
            ),
            'DAILY_LOSS_LIMIT': (
                r"(\"MAX_DAILY_LOSS\"\s*:\s*)([0-9.-]+)",
                r"\g<1>{value}",
                "RISK_CONFIG"
            ),
            'MAX_POSITION_CONTRACTS': (
                r"(\"MAX_POSITION_CONTRACTS\"\s*:\s*)([0-9.-]+)",
                r"\g<1>{value}",
                "RISK_CONFIG"
            ),
            'MIN_ORDER_CONTRACTS': (
                r"(\"MIN_ORDER_CONTRACTS\"\s*:\s*)([0-9.-]+)",
                r"\g<1>{value}",
                "RISK_CONFIG"
            ),
            'MAX_SLIPPAGE': (
                r"(\"MAX_SLIPPAGE\"\s*:\s*)([0-9.-]+)",
                r"\g<1>{value}",
                "RISK_CONFIG"
            ),
            'MIN_ORDER_INTERVAL': (
                r"('MIN_ORDER_INTERVAL'\s*:\s*)([0-9.-]+)",
                r"\g<1>{value}",
                "TRADING_CONFIG"
            ),
        }
        
        # Process each update
        for key, value in config_updates.items():
            if key not in config_mappings:
                logger.warning(f"Config key '{key}' not supported for file persistence")
                continue
            
            pattern, replacement_template, section = config_mappings[key]
            replacement = replacement_template.format(value=value)
            
            # Check if pattern exists in config
            if not re.search(pattern, config_content):
                logger.warning(f"Pattern for '{key}' not found in config.py")
                continue
            
            # Replace the value
            new_content, count = re.subn(pattern, replacement, config_content)
            
            if count > 0:
                config_content = new_content
                updated_fields.append(f"{key}={value}")
                logger.info(f"Updated {section}['{key}'] = {value} in config.py")
        
        # Only write if changes were made
        if config_content != original_content:
            # Create backup
            backup_path = config_path.with_suffix('.py.bak')
            with open(backup_path, 'w', encoding='utf-8') as f:
                f.write(original_content)
            
            # Write updated config
            with open(config_path, 'w', encoding='utf-8') as f:
                f.write(config_content)
            
            logger.info(f"✅ Configuration saved to {config_path}")
            logger.info(f"📝 Updated fields: {', '.join(updated_fields)}")
            logger.info(f"💾 Backup saved to {backup_path}")
            
            return {
                'success': True,
                'message': f'Configuration saved to file: {", ".join(updated_fields)}'
            }
        else:
            return {
                'success': True,
                'message': 'No changes to save'
            }
            
    except Exception as e:
        logger.error(f"❌ Error saving config to file: {e}", exc_info=True)
        return {
            'success': False,
            'error': f'Failed to save config to file: {str(e)}'
        }


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
        self.live_portfolio_task = None
        self.live_mode_active = False
        self.market_status = {'status': 'unknown', 'last_check': 0}
        
        self.web_dir = Path(__file__).parent / "web"
        
        from core.spread_history import SpreadHistoryManager
        self.spread_history = SpreadHistoryManager(max_points=1000, save_interval=60)

    @staticmethod
    def _normalize_direction_code(direction: Any) -> Optional[str]:
        """Normalize direction value coming from enums/strings to 'B_TO_H' / 'H_TO_B'."""
        if direction is None:
            return None

        if hasattr(direction, 'name'):
            name = str(getattr(direction, 'name') or '').strip().upper()
            if name in {'B_TO_H', 'H_TO_B'}:
                return name

        raw = str(direction).strip()
        normalized = raw.replace(' ', '').upper()

        if raw in {'B→H', 'B->H', 'B_TO_H', 'B2H'} or normalized in {'B→H', 'B->H', 'B_TO_H', 'B2H'}:
            return 'B_TO_H'
        if raw in {'H→B', 'H->B', 'H_TO_B', 'H2B'} or normalized in {'H→B', 'H->B', 'H_TO_B', 'H2B'}:
            return 'H_TO_B'

        return None

    def setup_routes(self):
        """Setup HTTP and WebSocket routes"""
        if web is None:
            return
        
        # Create application with CSP middleware
        self.app = web.Application(middlewares=[csp_middleware])
        
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
        self.app.router.add_get('/api/heatmap', self.handle_api_heatmap)
        self.app.router.add_get('/api/export-csv', self.handle_api_export_csv)
        self.app.router.add_post('/api/clear-heatmap', self.handle_api_clear_heatmap)
        self.app.router.add_get('/api/live-portfolio', self.handle_api_live_portfolio)
    
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
        
        # Send initial config to the new client
        await self.send_initial_config(ws)
        
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
                await self.send_to_client(ws, 'command_result', {
                    'success': success,
                    'message': f'Position #{position_id} closed successfully' if success else f'Failed to close position #{position_id}',
                    'error': None if success else 'Position not found or could not be closed'
                })
        
        elif msg_type == 'bot_command':
            # Handle bot control commands (start/pause/stop)
            command = data.get('command', '').lower()
            logger.info(f"[WS] Received bot_command: {command}")
            result = await self.handle_bot_command(command)
            logger.info(f"[WS] bot_command result: {result}")
            await self.send_to_client(ws, 'command_result', result)
        
        elif msg_type == 'update_config':
            # Update bot configuration
            config = data.get('config', {})
            result = await self.handle_config_update(config)
            await self.send_to_client(ws, 'command_result', result)
        
        elif msg_type == 'update_risk_config':
            # Update risk management configuration
            config = data.get('config', {})
            result = await self.handle_risk_config_update(config)
            await self.send_to_client(ws, 'command_result', result)
        
        elif msg_type == 'toggle_trading':
            # Toggle trading mode (legacy support)
            self.bot.trading_enabled = not getattr(self.bot, 'trading_enabled', True)
            await self.send_to_client(ws, 'trading_status', {
                'enabled': getattr(self.bot, 'trading_enabled', True)
            })
        
        elif msg_type == 'set_trading_mode':
            # Set trading mode (paper/live)
            mode = data.get('mode', 'paper')
            result = await self.handle_trading_mode_change(mode)
            await self.send_to_client(ws, 'command_result', result)
            await self.send_to_client(ws, 'trading_mode', {
                'mode': mode,
                'live_executor_status': result.get('live_executor_status', {})
            })
            
            if mode == 'live':
                self.live_mode_active = True
                await self.start_live_portfolio_updates()
            else:
                self.live_mode_active = False
                await self.stop_live_portfolio_updates()
        
        elif msg_type == 'update_position_exit_spread':
            # Update exit_target for a specific position
            position_id = data.get('position_id')
            new_exit_spread = data.get('new_exit_spread')
            if position_id is not None and new_exit_spread is not None:
                result = await self.update_position_exit_spread(position_id, float(new_exit_spread))
                await self.send_to_client(ws, 'command_result', result)
    
    async def close_position(self, position_id):
        """Close a specific position"""
        try:
            arb_engine = getattr(self.bot, 'arb_engine', None)
            if not arb_engine or not hasattr(arb_engine, 'get_open_positions'):
                return False

            positions = arb_engine.get_open_positions()
            for pos in positions:
                if pos.id == position_id:
                    if hasattr(arb_engine, 'force_close_position'):
                        await arb_engine.force_close_position(pos, "Manual close via dashboard")
                        return True
                    elif hasattr(arb_engine, 'close_position'):
                        current_spread = getattr(pos, 'current_exit_spread', 0.0)
                        await arb_engine.close_position(pos, current_spread, "Manual close via dashboard")
                        return True
            return False
        except Exception as e:
            logger.error(f"Error closing position {position_id}: {e}")
            return False
    
    async def update_position_exit_spread(self, position_id, new_exit_spread):
        """Update exit_target for a specific position"""
        try:
            arb_engine = getattr(self.bot, 'arb_engine', None)
            if not arb_engine or not hasattr(arb_engine, 'get_open_positions'):
                return {
                    'success': False,
                    'error': 'Arbitrage engine not available'
                }

            positions = arb_engine.get_open_positions()
            for pos in positions:
                if pos.id == position_id:
                    old_value = pos.exit_target
                    pos.exit_target = new_exit_spread
                    logger.info(f"Position {position_id}: exit_target changed from {old_value:.3f}% to {new_exit_spread:.3f}%")
                    return {
                        'success': True,
                        'message': f'Position #{position_id} exit spread updated to {new_exit_spread:.3f}%',
                        'event_type': 'success'
                    }
            
            return {
                'success': False,
                'error': f'Position #{position_id} not found'
            }
        except Exception as e:
            logger.error(f"Error updating position exit spread {position_id}: {e}")
            return {
                'success': False,
                'error': str(e)
            }
    
    async def handle_bot_command(self, command):
        """Handle bot control commands (start/pause/stop)"""
        try:
            if command == 'start':
                # Logic to start/resume the bot
                if hasattr(self.bot, 'trading_enabled'):
                    self.bot.trading_enabled = True
                return {
                    'success': True,
                    'message': 'Bot started successfully'
                }
            elif command == 'pause' or command == 'stop':
                # Logic to pause/stop the bot
                if hasattr(self.bot, 'trading_enabled'):
                    self.bot.trading_enabled = False
                return {
                    'success': True,
                    'message': f'Bot {command}ped successfully'
                }
            elif command == 'restart':
                # Restart bot - reset session and re-enable trading
                if hasattr(self.bot, 'trading_enabled'):
                    self.bot.trading_enabled = True
                if hasattr(self.bot, 'session_start'):
                    self.bot.session_start = time.time()
                if hasattr(self.bot, 'arb_engine') and hasattr(self.bot.arb_engine, 'reset_session_records'):
                    self.bot.arb_engine.reset_session_records()
                return {
                    'success': True,
                    'message': 'Bot restarted successfully'
                }
            else:
                return {
                    'success': False,
                    'error': f'Unknown command: {command}'
                }
        except Exception as e:
            logger.error(f"Error handling bot command {command}: {e}")
            return {
                'success': False,
                'error': str(e)
            }
    
    async def handle_config_update(self, config):
        """Handle configuration updates"""
        try:
            # Validate and update configuration
            updated_fields = []
            bot_config = getattr(self.bot, 'config', {})
            config_to_save = {}

            if 'MIN_SPREAD_ENTER' in config:
                value = float(config['MIN_SPREAD_ENTER'])
                if 0.0001 <= value <= 0.01:  # 0.01% to 1.0%
                    if isinstance(bot_config, dict):
                        bot_config['MIN_SPREAD_ENTER'] = value
                    config_to_save['MIN_SPREAD_ENTER'] = value
                    updated_fields.append(f"MIN_SPREAD_ENTER={value*100:.2f}%")
                else:
                    return {
                        'success': False,
                        'error': 'MIN_SPREAD_ENTER must be between 0.01% and 1.0%'
                    }

            if 'MIN_SPREAD_EXIT' in config:
                value = float(config['MIN_SPREAD_EXIT'])
                if -0.01 <= value <= 0.002:  # -1.0% to 0.2%
                    if isinstance(bot_config, dict):
                        bot_config['MIN_SPREAD_EXIT'] = value
                    config_to_save['MIN_SPREAD_EXIT'] = value
                    updated_fields.append(f"MIN_SPREAD_EXIT={value*100:.2f}%")
                else:
                    return {
                        'success': False,
                        'error': 'MIN_SPREAD_EXIT must be between -1.0% and 0.2%'
                    }

            if 'MAX_POSITION_AGE_HOURS' in config:
                value = float(config['MAX_POSITION_AGE_HOURS'])
                if 0.5 <= value <= 24:
                    if isinstance(bot_config, dict):
                        bot_config['MAX_POSITION_AGE_HOURS'] = value
                    # Note: This field is not in config.py, only in memory
                    updated_fields.append(f"MAX_POSITION_AGE_HOURS={value}")
                else:
                    return {
                        'success': False,
                        'error': 'MAX_POSITION_AGE_HOURS must be between 0.5 and 24'
                    }

            if 'MAX_CONCURRENT_POSITIONS' in config:
                value = int(config['MAX_CONCURRENT_POSITIONS'])
                if 1 <= value <= 10:
                    if isinstance(bot_config, dict):
                        bot_config['MAX_CONCURRENT_POSITIONS'] = value
                    updated_fields.append(f"MAX_CONCURRENT_POSITIONS={value}")
                else:
                    return {
                        'success': False,
                        'error': 'MAX_CONCURRENT_POSITIONS must be between 1 and 10'
                    }

            if 'MIN_ORDER_INTERVAL' in config:
                value = float(config['MIN_ORDER_INTERVAL'])
                if 0 <= value <= 60:
                    if isinstance(bot_config, dict):
                        bot_config['MIN_ORDER_INTERVAL'] = value
                    # Update arbitrage_engine config
                    arb_engine = getattr(self.bot, 'arbitrage_engine', None)
                    if arb_engine:
                        arb_engine.config['MIN_ORDER_INTERVAL'] = value
                    config_to_save['MIN_ORDER_INTERVAL'] = value
                    updated_fields.append(f"MIN_ORDER_INTERVAL={value}s")
                else:
                    return {
                        'success': False,
                        'error': 'MIN_ORDER_INTERVAL must be between 0 and 60 seconds'
                    }

            if updated_fields:
                # Save persistent config fields to file
                save_result = {'success': True}
                if config_to_save:
                    save_result = save_config_to_file(config_to_save)
                
                # Build response message
                messages = [f'Configuration updated in memory: {", ".join(updated_fields)}']
                if save_result.get('success'):
                    if save_result.get('message') and 'saved to file' in save_result['message'].lower():
                        messages.append(save_result['message'])
                else:
                    messages.append(f"⚠️ Warning: {save_result.get('error', 'Failed to save to file')}")
                
                return {
                    'success': True,
                    'message': ' | '.join(messages)
                }
            else:
                return {
                    'success': False,
                    'error': 'No valid configuration fields provided'
                }
        except Exception as e:
            logger.error(f"Error updating configuration: {e}")
            return {
                'success': False,
                'error': str(e)
            }
    
    async def handle_risk_config_update(self, config):
        """Handle risk management configuration updates"""
        try:
            updated_fields = []
            bot_config = getattr(self.bot, 'config', {})
            config_to_save = {}

            if 'DAILY_LOSS_LIMIT' in config:
                value = float(config['DAILY_LOSS_LIMIT'])
                if 10 <= value <= 10000:
                    if isinstance(bot_config, dict):
                        bot_config['DAILY_LOSS_LIMIT'] = value
                    # Update risk_manager config
                    risk_manager = getattr(self.bot, 'risk_manager', None)
                    if risk_manager:
                        risk_manager.config['MAX_DAILY_LOSS'] = value
                    config_to_save['DAILY_LOSS_LIMIT'] = value
                    updated_fields.append(f"DAILY_LOSS_LIMIT=${value}")
                else:
                    return {
                        'success': False,
                        'error': 'DAILY_LOSS_LIMIT must be between 10 and 10000'
                    }

            if 'MAX_POSITION_CONTRACTS' in config:
                value = float(config['MAX_POSITION_CONTRACTS'])
                if 0.01 <= value <= 100:
                    if isinstance(bot_config, dict):
                        bot_config['MAX_POSITION_CONTRACTS'] = value
                    # Update risk_manager config
                    risk_manager = getattr(self.bot, 'risk_manager', None)
                    if risk_manager:
                        risk_manager.config['MAX_POSITION_CONTRACTS'] = value
                    config_to_save['MAX_POSITION_CONTRACTS'] = value
                    updated_fields.append(f"MAX_POSITION_CONTRACTS={value}")
                else:
                    return {
                        'success': False,
                        'error': 'MAX_POSITION_CONTRACTS must be between 0.01 and 100'
                    }
            
            if 'MIN_ORDER_CONTRACTS' in config:
                value = float(config['MIN_ORDER_CONTRACTS'])
                if 0.001 <= value <= 10:
                    if isinstance(bot_config, dict):
                        bot_config['MIN_ORDER_CONTRACTS'] = value
                    # Update risk_manager config
                    risk_manager = getattr(self.bot, 'risk_manager', None)
                    if risk_manager:
                        risk_manager.config['MIN_ORDER_CONTRACTS'] = value
                    config_to_save['MIN_ORDER_CONTRACTS'] = value
                    updated_fields.append(f"MIN_ORDER_CONTRACTS={value}")
                else:
                    return {
                        'success': False,
                        'error': 'MIN_ORDER_CONTRACTS must be between 0.001 and 10'
                    }
            
            if 'MAX_SLIPPAGE' in config:
                value = float(config['MAX_SLIPPAGE'])
                if 0.0001 <= value <= 0.05:  # 0.01% to 5%
                    if isinstance(bot_config, dict):
                        bot_config['MAX_SLIPPAGE'] = value
                    # Update risk_manager config
                    risk_manager = getattr(self.bot, 'risk_manager', None)
                    if risk_manager:
                        risk_manager.config['MAX_SLIPPAGE'] = value
                    config_to_save['MAX_SLIPPAGE'] = value
                    updated_fields.append(f"MAX_SLIPPAGE={value*100:.3f}%")
                else:
                    return {
                        'success': False,
                        'error': 'MAX_SLIPPAGE must be between 0.01% and 5%'
                    }

            if updated_fields:
                # Save persistent config fields to file
                save_result = {'success': True}
                if config_to_save:
                    save_result = save_config_to_file(config_to_save)
                
                # Build response message
                messages = [f'Risk configuration updated in memory: {", ".join(updated_fields)}']
                if save_result.get('success'):
                    if save_result.get('message') and 'saved to file' in save_result['message'].lower():
                        messages.append(save_result['message'])
                else:
                    messages.append(f"⚠️ Warning: {save_result.get('error', 'Failed to save to file')}")
                
                return {
                    'success': True,
                    'message': ' | '.join(messages)
                }
            else:
                return {
                    'success': False,
                    'error': 'No valid risk configuration fields provided'
                }
        except Exception as e:
            logger.error(f"Error updating risk configuration: {e}")
            return {
                'success': False,
                'error': str(e)
            }
    
    async def handle_trading_mode_change(self, mode):
        """Handle trading mode change (paper/live)"""
        try:
            from config import TRADING_MODE, save_trading_mode
            
            old_mode = TRADING_MODE.get('MODE', 'paper')
            TRADING_MODE['MODE'] = mode
            
            live_executor_status = {}
            
            if mode == 'live':
                TRADING_MODE['LIVE_ENABLED'] = True
                save_trading_mode()
                
                if hasattr(self.bot, 'live_executor'):
                    live_exec = self.bot.live_executor
                    if live_exec and hasattr(live_exec, 'initialize'):
                        if not live_exec.initialized:
                            await live_exec.initialize()
                        live_executor_status = live_exec.get_status() if hasattr(live_exec, 'get_status') else {}
                else:
                    from core.live_executor import LiveTradeExecutor
                    self.bot.live_executor = LiveTradeExecutor()
                    await self.bot.live_executor.initialize()
                    live_executor_status = self.bot.live_executor.get_status()
                
                logger.warning(f"Trading mode changed from {old_mode} to LIVE")
                return {
                    'success': True,
                    'message': f'Trading mode changed to LIVE. API Status: HL={live_executor_status.get("hyperliquid_connected", False)}, BG={live_executor_status.get("bitget_connected", False)}',
                    'event_type': 'warning',
                    'live_executor_status': live_executor_status
                }
            else:
                TRADING_MODE['LIVE_ENABLED'] = False
                save_trading_mode()
                logger.info(f"Trading mode changed from {old_mode} to paper")
                return {
                    'success': True,
                    'message': 'Trading mode changed to Paper',
                    'event_type': 'success',
                    'live_executor_status': {}
                }
                
        except Exception as e:
            logger.error(f"Error changing trading mode: {e}")
            return {
                'success': False,
                'error': str(e),
                'live_executor_status': {}
            }
    
    def collect_dashboard_data(self):
        """Collect all data needed for dashboard display"""
        session_start = getattr(self.bot, 'session_start', time.time())
        runtime = time.time() - session_start

        # Trading mode
        mode = 'stopped'
        trading_mode = getattr(self.bot, 'trading_mode', None)
        if trading_mode:
            if hasattr(trading_mode, 'value'):
                if trading_mode.value == 'ACTIVE':
                    mode = 'active'
                elif trading_mode.value == 'PARTIAL':
                    mode = 'partial'
        
        # Collect spreads
        spreads: Dict[str, Dict[str, float]] = {}
        exit_spreads: Dict[str, float] = {}

        bitget_ws = getattr(self.bot, 'bitget_ws', None)
        hyper_ws = getattr(self.bot, 'hyper_ws', None)
        arb_engine = getattr(self.bot, 'arb_engine', None)

        try:
            if bitget_ws and hyper_ws and arb_engine:
                bitget_data = bitget_ws.get_latest_data() if hasattr(bitget_ws, 'get_latest_data') else None
                hyper_data = hyper_ws.get_latest_data() if hasattr(hyper_ws, 'get_latest_data') else None

                if bitget_data and hyper_data:
                    bitget_slippage = bitget_ws.get_estimated_slippage() if hasattr(bitget_ws, 'get_estimated_slippage') else None
                    hyper_slippage = hyper_ws.get_estimated_slippage() if hasattr(hyper_ws, 'get_estimated_slippage') else None

                    if hasattr(arb_engine, 'calculate_spreads'):
                        calc_spreads = arb_engine.calculate_spreads(
                            bitget_data, hyper_data, bitget_slippage, hyper_slippage
                        )

                        if calc_spreads:
                            for direction, spread_data in calc_spreads.items():
                                code = self._normalize_direction_code(direction)
                                if not code:
                                    continue

                                entry_payload = {
                                    'gross_spread': float(spread_data.get('gross_spread', 0) or 0)
                                }
                                spreads[code] = entry_payload
                                spreads[code.lower()] = entry_payload

                    if hasattr(arb_engine, 'calculate_exit_spread_for_market'):
                        exit_calc = arb_engine.calculate_exit_spread_for_market(
                            bitget_data, hyper_data, bitget_slippage, hyper_slippage
                        )

                        if exit_calc:
                            for direction, spread in exit_calc.items():
                                code = self._normalize_direction_code(direction)
                                if not code:
                                    continue

                                value = float(spread or 0)
                                exit_spreads[code] = value
                                exit_spreads[code.lower()] = value

            logger.debug(
                "collect_dashboard_data(): spreads=%s exit_spreads=%s",
                {k: v.get('gross_spread') for k, v in spreads.items() if k in {'B_TO_H', 'H_TO_B'}},
                {k: v for k, v in exit_spreads.items() if k in {'B_TO_H', 'H_TO_B'}},
            )
        except Exception as e:
            logger.debug(f"collect_dashboard_data(): error calculating spreads: {e}", exc_info=True)

        # Portfolio
        portfolio = {}
        paper_executor = getattr(self.bot, 'paper_executor', None)
        if paper_executor and hasattr(paper_executor, 'get_portfolio'):
            portfolio = paper_executor.get_portfolio()
            logger.debug(f"collect_dashboard_data(): portfolio={portfolio}")

        # Total value and PnL
        total_value = 0
        pnl = 0
        try:
            bitget_data = bitget_ws.get_latest_data() if bitget_ws and hasattr(bitget_ws, 'get_latest_data') else None
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
            open_positions = arb_engine.get_open_positions() if arb_engine and hasattr(arb_engine, 'get_open_positions') else []
            for pos in open_positions:
                direction_obj = getattr(pos, 'direction', None)
                direction_code = self._normalize_direction_code(direction_obj)
                direction_label = getattr(direction_obj, 'value', None)

                entry_prices = getattr(pos, 'entry_prices', {})
                entry_spread = getattr(pos, 'entry_spread', None)
                size = getattr(pos, 'contracts', 0)
                
                positions.append({
                    'id': pos.id,
                    'direction': direction_code or str(direction_obj),
                    'direction_label': direction_label,
                    'size': size,
                    'entry_prices': entry_prices,
                    'entry_spread': entry_spread,
                    'exit_spread': pos.current_exit_spread,
                    'current_exit_spread': pos.current_exit_spread,
                    'exit_target': pos.exit_target,
                    'age': pos.get_age_formatted() if hasattr(pos, 'get_age_formatted') else '--',
                    'should_close': pos.should_close() if hasattr(pos, 'should_close') else False,
                    'mode': getattr(pos, 'mode', 'paper')
                })
        except Exception:
            pass

        # Calculate latency (mock values, can be enhanced with real measurements)
        bitget_latency = 0
        hyper_latency = 0
        try:
            if bitget_ws and hasattr(bitget_ws, 'last_message_time') and bitget_ws.last_message_time:
                bitget_latency = int((time.time() - bitget_ws.last_message_time) * 1000)
            if hyper_ws and hasattr(hyper_ws, 'last_message_time') and hyper_ws.last_message_time:
                hyper_latency = int((time.time() - hyper_ws.last_message_time) * 1000)
        except Exception:
            pass
        
        # Get daily loss
        daily_loss = 0
        try:
            risk_manager = getattr(self.bot, 'risk_manager', None)
            if risk_manager and hasattr(risk_manager, 'daily_loss'):
                daily_loss = risk_manager.daily_loss
        except Exception:
            pass

        # Get best spreads session data safely
        best_spreads_session = getattr(self.bot, 'best_spreads_session', {})
        session_stats = getattr(self.bot, 'session_stats', {})
        bot_config = getattr(self.bot, 'config', {})

        best_entry_spread = 0.0
        best_entry_direction = None
        best_entry_time = None
        best_exit_overall = None
        best_exit_direction = None
        best_exit_time = None

        if isinstance(best_spreads_session, dict):
            best_entry_spread = float(best_spreads_session.get('best_entry_spread', 0) or 0)
            best_entry_direction = self._normalize_direction_code(best_spreads_session.get('best_entry_direction'))
            best_entry_time = best_spreads_session.get('best_entry_time')

            raw_best_exit_overall = best_spreads_session.get('best_exit_spread_overall')
            try:
                raw_best_exit_overall = float(raw_best_exit_overall)
            except Exception:
                raw_best_exit_overall = None

            if raw_best_exit_overall is not None and math.isfinite(raw_best_exit_overall):
                best_exit_overall = raw_best_exit_overall

            best_exit_direction = self._normalize_direction_code(best_spreads_session.get('best_exit_direction'))
            best_exit_time = best_spreads_session.get('best_exit_time')

        # Collect pending warnings from arb_engine
        warnings = []
        if arb_engine and hasattr(arb_engine, 'get_pending_warnings'):
            warnings = arb_engine.get_pending_warnings()
        
        # Get live portfolio from WebSocket cache (sync, for quick access)
        live_portfolio = None
        if hasattr(self.bot, 'live_executor') and self.bot.live_executor:
            live_exec = self.bot.live_executor
            if hasattr(live_exec, 'get_ws_portfolio'):
                live_portfolio = live_exec.get_ws_portfolio()
        
        # Check for position mismatch between bot and exchanges
        if live_portfolio and positions:
            hl_pos = live_portfolio.get('hyperliquid', {}).get('nvda_position')
            bg_pos = live_portfolio.get('bitget', {}).get('nvda_position')
            hl_size = abs(hl_pos.get('size', 0)) if hl_pos else 0
            bg_size = abs(bg_pos.get('size', 0)) if bg_pos else 0
            bot_size = sum(p.get('size', 0) for p in positions)
            
            if abs(hl_size - bot_size) > 0.001 or abs(bg_size - bot_size) > 0.001:
                warnings.append({
                    'type': 'position_mismatch',
                    'message': f'Расхождение позиций: Бот={bot_size:.3f}, HL={hl_size:.3f}, BG={bg_size:.3f}'
                })
        
        # Get total position size in contracts
        total_position_contracts = 0.0
        if arb_engine and hasattr(arb_engine, 'get_total_position_contracts'):
            total_position_contracts = arb_engine.get_total_position_contracts()
        
        # Get live executor status
        live_executor_status = {}
        if hasattr(self.bot, 'live_executor') and self.bot.live_executor:
            live_exec = self.bot.live_executor
            if hasattr(live_exec, 'get_status'):
                live_executor_status = live_exec.get_status()
        
        # Get paper/live trading mode from config
        from config import TRADING_MODE
        paper_or_live = 'live' if TRADING_MODE.get('LIVE_ENABLED', False) else 'paper'
        
        return {
            'timestamp': datetime.now().strftime('%H:%M:%S'),
            'runtime': runtime,
            'trading_mode': mode,
            'paper_or_live': paper_or_live,
            'trading_enabled': getattr(self.bot, 'trading_enabled', True),
            'bitget_healthy': getattr(self.bot, 'bitget_healthy', False),
            'hyper_healthy': getattr(self.bot, 'hyper_healthy', False),
            'live_executor_status': live_executor_status,
            'bitget_latency': max(0, min(bitget_latency, 999)),  # Cap at 999ms
            'hyper_latency': max(0, min(hyper_latency, 999)),
            'session_stats': session_stats,
            'bitget_data': bitget_ws.get_latest_data() if bitget_ws and hasattr(bitget_ws, 'get_latest_data') else None,
            'hyper_data': hyper_ws.get_latest_data() if hyper_ws and hasattr(hyper_ws, 'get_latest_data') else None,
            'spreads': spreads,
            'exit_spreads': exit_spreads,
            'best_entry_spread': best_entry_spread,
            'best_entry_direction': best_entry_direction,
            'best_entry_time': best_entry_time,
            'best_exit_overall': best_exit_overall,
            'best_exit_direction': best_exit_direction,
            'best_exit_time': best_exit_time,
            'portfolio': portfolio,
            'total_value': total_value,
            'pnl': pnl,
            'daily_loss': daily_loss,
            'positions': positions,
            'total_position_contracts': total_position_contracts,
            'config': bot_config,
            'spread_chart_data': self._get_spread_chart_data(),
            'warnings': warnings,
            'market_status': self.market_status.get('status', 'unknown'),
            'live_portfolio': live_portfolio
        }
    
    def _get_spread_chart_data(self) -> Dict:
        """Получение данных для графика спредов из истории"""
        try:
            return self.spread_history.get_chart_data(limit=500)
        except Exception as e:
            logger.debug(f"Error getting spread chart data: {e}")
            return self._empty_chart_data()
    
    def _record_current_spreads(self):
        """Записать текущие спреды в историю"""
        try:
            bitget_ws = getattr(self.bot, 'bitget_ws', None)
            hyper_ws = getattr(self.bot, 'hyper_ws', None)
            arb_engine = getattr(self.bot, 'arb_engine', None)

            if not bitget_ws or not hyper_ws or not arb_engine:
                return

            bitget_data = bitget_ws.get_latest_data() if hasattr(bitget_ws, 'get_latest_data') else None
            hyper_data = hyper_ws.get_latest_data() if hasattr(hyper_ws, 'get_latest_data') else None

            if not bitget_data or not hyper_data:
                return

            bitget_slippage = bitget_ws.get_estimated_slippage() if hasattr(bitget_ws, 'get_estimated_slippage') else None
            hyper_slippage = hyper_ws.get_estimated_slippage() if hasattr(hyper_ws, 'get_estimated_slippage') else None

            spreads = arb_engine.calculate_spreads(
                bitget_data, hyper_data, bitget_slippage, hyper_slippage
            ) if hasattr(arb_engine, 'calculate_spreads') else {}

            exit_spreads_raw = arb_engine.calculate_exit_spread_for_market(
                bitget_data, hyper_data, bitget_slippage, hyper_slippage
            ) if hasattr(arb_engine, 'calculate_exit_spread_for_market') else {}

            if spreads and exit_spreads_raw:
                entry_spreads = {}
                exit_spreads = {}
                
                for direction, spread_data in spreads.items():
                    code = self._normalize_direction_code(direction)
                    if code and isinstance(spread_data, dict):
                        entry_spreads[code] = float(spread_data.get('gross_spread', 0) or 0)
                
                for direction, spread_value in exit_spreads_raw.items():
                    code = self._normalize_direction_code(direction)
                    if code:
                        exit_spreads[code] = float(spread_value or 0)

                bitget_healthy = getattr(self.bot, 'bitget_healthy', False)
                hyper_healthy = getattr(self.bot, 'hyper_healthy', False)
                
                self.spread_history.add_spreads(entry_spreads, exit_spreads, bitget_healthy, hyper_healthy)
        except Exception as e:
            logger.debug(f"Error recording spreads: {e}")

    def _empty_chart_data(self) -> Dict:
        """Return empty chart data structure"""
        return {
            'labels': [],
            'datasets': {
                'entry_bh': [],
                'entry_hb': [],
                'exit_bh': [],
                'exit_hb': [],
            },
            'timestamps': [],
            'health': {
                'bitget': [],
                'hyper': [],
            }
        }
    
    async def send_to_client(self, ws, msg_type, payload):
        """Send message to a specific WebSocket client"""
        if not ws.closed:
            try:
                message = json.dumps({'type': msg_type, 'payload': payload}, cls=DateTimeEncoder)
                await ws.send_str(message)
            except Exception as e:
                logger.error(f"Error sending to client: {e}")
    
    async def send_initial_config(self, ws):
        """Send initial configuration to newly connected client"""
        try:
            from config import TRADING_CONFIG
            
            config_data = {
                'MIN_SPREAD_ENTER': TRADING_CONFIG.get('MIN_SPREAD_ENTER', 0.0007),
                'MIN_SPREAD_EXIT': TRADING_CONFIG.get('MIN_SPREAD_EXIT', 0.0006),
                'MAX_POSITION_CONTRACTS': TRADING_CONFIG.get('MAX_POSITION_CONTRACTS', 0.05),
                'MIN_ORDER_CONTRACTS': TRADING_CONFIG.get('MIN_ORDER_CONTRACTS', 0.01),
                'MAX_SLIPPAGE': TRADING_CONFIG.get('MAX_SLIPPAGE', 0.001),
                'MIN_ORDER_INTERVAL': TRADING_CONFIG.get('MIN_ORDER_INTERVAL', 5),
                'DAILY_LOSS_LIMIT': TRADING_CONFIG.get('MAX_DAILY_LOSS', 100.0),
                'MAX_CONCURRENT_POSITIONS': TRADING_CONFIG.get('MAX_CONCURRENT_POSITIONS', 5),
            }
            
            await self.send_to_client(ws, 'config', {'config': config_data})
            logger.debug(f"Sent initial config to client: {config_data}")
        except Exception as e:
            logger.error(f"Error sending initial config: {e}")
    
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
    
    async def start_live_portfolio_updates(self):
        """Start live portfolio updates (0.5s interval)"""
        if self.live_portfolio_task is None or self.live_portfolio_task.done():
            self.live_portfolio_task = asyncio.create_task(self._live_portfolio_updates())
            logger.info("Started live portfolio updates (0.5s interval)")
    
    async def stop_live_portfolio_updates(self):
        """Stop live portfolio updates"""
        if self.live_portfolio_task and not self.live_portfolio_task.done():
            self.live_portfolio_task.cancel()
            try:
                await self.live_portfolio_task
            except asyncio.CancelledError:
                pass
            self.live_portfolio_task = None
            logger.info("Stopped live portfolio updates")
    
    async def _live_portfolio_updates(self):
        """Send live portfolio updates - uses WebSocket streaming when available"""
        live_exec = getattr(self.bot, 'live_executor', None)
        
        if live_exec and live_exec.private_ws_manager:
            live_exec.set_portfolio_callback(self._on_ws_portfolio_update)
            logger.info("Live portfolio: Using WebSocket streaming")
            
            while self.live_mode_active:
                try:
                    await asyncio.sleep(1.0)
                except asyncio.CancelledError:
                    break
            
            live_exec.set_portfolio_callback(None)
        else:
            logger.info(f"Live portfolio: Using REST polling (0.5s), live_exec={live_exec}, initialized={getattr(live_exec, 'initialized', None) if live_exec else None}")
            iteration = 0
            while self.live_mode_active:
                try:
                    iteration += 1
                    portfolio_data = None
                    
                    # Re-check live_exec each iteration in case it was initialized after start
                    if live_exec is None:
                        live_exec = getattr(self.bot, 'live_executor', None)
                    
                    if live_exec and live_exec.initialized:
                        portfolio_data = await live_exec.get_live_portfolio()
                    
                    if iteration <= 3:
                        print(f"[PORTFOLIO] iter={iteration}, live_exec={live_exec is not None}, init={getattr(live_exec, 'initialized', None) if live_exec else None}, data={portfolio_data is not None}, clients={len(self.ws_clients)}")
                    
                    # Fallback to paper portfolio if live data unavailable
                    use_fallback = False
                    if portfolio_data is None:
                        use_fallback = True
                    elif (not portfolio_data.get('hyperliquid', {}).get('connected') and 
                          not portfolio_data.get('bitget', {}).get('connected')):
                        use_fallback = True
                    
                    if use_fallback:
                        paper_exec = getattr(self.bot, 'paper_executor', None)
                        if paper_exec and hasattr(paper_exec, 'get_portfolio'):
                            paper_portfolio = paper_exec.get_portfolio()
                            usdt = paper_portfolio.get('USDT', 0)
                            portfolio_data = {
                                'hyperliquid': {'connected': False, 'equity': 0, 'available': 0, 'margin_used': 0},
                                'bitget': {'connected': False, 'equity': 0, 'available': 0, 'margin_used': 0},
                                'combined': {
                                    'total_equity': usdt,
                                    'total_pnl': usdt - 1000.0,
                                    'note': 'Paper portfolio (live not connected)'
                                }
                            }
                    
                    if self.ws_clients and portfolio_data:
                        await self.broadcast('live_portfolio', portfolio_data)
                    await asyncio.sleep(0.5)
                except asyncio.CancelledError:
                    break
                except Exception as e:
                    logger.error(f"Error in live portfolio updates: {e}")
                    await asyncio.sleep(1.0)
    
    async def _on_ws_portfolio_update(self, portfolio_data: dict):
        """Callback when WebSocket receives portfolio update"""
        if self.ws_clients and self.live_mode_active:
            await self.broadcast('live_portfolio', portfolio_data)
    
    async def _periodic_updates(self):
        """Send periodic updates to all connected clients"""
        from config import TRADING_MODE
        while True:
            try:
                self.market_status = await check_bitget_market_status()
                
                self._record_current_spreads()
                
                if self.ws_clients:
                    payload = self.collect_dashboard_data()
                    logger.debug(
                        "_periodic_updates(): broadcasting full_update to %s client(s)",
                        len(self.ws_clients),
                    )
                    await self.broadcast('full_update', payload)
                
                await asyncio.sleep(1.0)
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
        
        # Enable SO_REUSEADDR to allow immediate port reuse
        # This prevents "address already in use" errors on Windows when restarting
        self.site = web.TCPSite(self.runner, self.host, self.port, reuse_address=True)
        await self.site.start()
        
        logger.info(f"🌐 Web Dashboard available at http://{self.host}:{self.port}")
        logger.info(f"📊 Open http://{self.host}:{self.port} in your browser")
        
        # Start periodic updates
        await self.start_updates()
        
        # If live mode is enabled on startup, start live portfolio updates
        from config import TRADING_MODE
        live_exec = getattr(self.bot, 'live_executor', None)
        print(f"[WEB] Startup check: LIVE_ENABLED={TRADING_MODE.get('LIVE_ENABLED', False)}, live_exec={live_exec is not None}, initialized={getattr(live_exec, 'initialized', None) if live_exec else None}")
        if TRADING_MODE.get('LIVE_ENABLED', False):
            self.live_mode_active = True
            await self.start_live_portfolio_updates()
            logger.info("Live mode enabled on startup, started live portfolio updates")
        
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
        spreads: Dict[str, Dict] = {}
        try:
            bitget_ws = getattr(self.bot, 'bitget_ws', None)
            hyper_ws = getattr(self.bot, 'hyper_ws', None)
            arb_engine = getattr(self.bot, 'arb_engine', None)

            if bitget_ws and hyper_ws and arb_engine:
                bitget_data = bitget_ws.get_latest_data() if hasattr(bitget_ws, 'get_latest_data') else None
                hyper_data = hyper_ws.get_latest_data() if hasattr(hyper_ws, 'get_latest_data') else None

                if bitget_data and hyper_data and hasattr(arb_engine, 'calculate_spreads'):
                    bitget_slippage = bitget_ws.get_estimated_slippage() if hasattr(bitget_ws, 'get_estimated_slippage') else None
                    hyper_slippage = hyper_ws.get_estimated_slippage() if hasattr(hyper_ws, 'get_estimated_slippage') else None

                    calc_spreads = arb_engine.calculate_spreads(bitget_data, hyper_data, bitget_slippage, hyper_slippage)
                    if calc_spreads:
                        for direction, spread_data in calc_spreads.items():
                            code = self._normalize_direction_code(direction)
                            if not code:
                                continue
                            spreads[code] = spread_data
                            spreads[code.lower()] = spread_data
        except Exception as e:
            return web.json_response({'error': str(e)}, status=500)

        return web.json_response({'spreads': spreads})

    async def handle_api_positions(self, request):
        """API endpoint for positions"""
        positions = []
        try:
            arb_engine = getattr(self.bot, 'arb_engine', None)
            open_positions = arb_engine.get_open_positions() if arb_engine and hasattr(arb_engine, 'get_open_positions') else []
            for pos in open_positions:
                direction_obj = getattr(pos, 'direction', None)
                positions.append({
                    'id': pos.id,
                    'direction': self._normalize_direction_code(direction_obj) or str(direction_obj),
                    'direction_label': getattr(direction_obj, 'value', None),
                    'size': getattr(pos, 'contracts', 0),
                    'entry_price': pos.entry_prices if hasattr(pos, 'entry_prices') else {},
                    'entry_spread': getattr(pos, 'entry_spread', 0),
                    'current_exit_spread': pos.current_exit_spread,
                    'exit_target': pos.exit_target,
                    'age': pos.get_age_formatted() if hasattr(pos, 'get_age_formatted') else None,
                    'statistics': pos.get_statistics() if hasattr(pos, 'get_statistics') else {},
                    'mode': getattr(pos, 'mode', 'paper')
                })
        except Exception as e:
            return web.json_response({'error': str(e)}, status=500)
        
        return web.json_response({'positions': positions})
    
    async def handle_api_portfolio(self, request):
        """API endpoint for portfolio"""
        portfolio = {}
        try:
            paper_executor = getattr(self.bot, 'paper_executor', None)
            if paper_executor and hasattr(paper_executor, 'get_portfolio'):
                portfolio = paper_executor.get_portfolio()
        except Exception as e:
            return web.json_response({'error': str(e)}, status=500)

        return web.json_response({'portfolio': portfolio})

    async def handle_api_live_portfolio(self, request):
        """API endpoint for live portfolio - diagnostic"""
        from config import TRADING_MODE
        try:
            live_exec = getattr(self.bot, 'live_executor', None)
            debug_info = {
                'live_enabled': TRADING_MODE.get('LIVE_ENABLED', False),
                'live_executor_exists': live_exec is not None,
                'live_executor_initialized': getattr(live_exec, 'initialized', None) if live_exec else None,
                'hl_connected': getattr(live_exec, 'hyperliquid_connected', None) if live_exec else None,
                'bg_connected': getattr(live_exec, 'bitget_connected', None) if live_exec else None,
            }
            
            if live_exec:
                portfolio_data = await live_exec.get_live_portfolio()
                return web.json_response({'debug': debug_info, 'portfolio': portfolio_data})
            else:
                return web.json_response({'debug': debug_info, 'error': 'live_executor not found'})
        except Exception as e:
            return web.json_response({'error': str(e)}, status=500)

    async def handle_api_stats(self, request):
        """API endpoint for session stats"""
        session_stats = getattr(self.bot, 'session_stats', {})
        best_spreads_session = getattr(self.bot, 'best_spreads_session', {})
        return web.json_response({
            'session_stats': session_stats,
            'best_spreads_session': best_spreads_session
        })

    async def handle_api_heatmap(self, request):
        """API endpoint for spread heatmap data by hour"""
        try:
            heatmap_data = self.spread_history.get_heatmap_data()
            return web.json_response({
                'heatmap': heatmap_data,
                'stats': self.spread_history.get_statistics()
            })
        except Exception as e:
            logger.error(f"Error getting heatmap data: {e}")
            return web.json_response({'error': str(e)}, status=500)

    async def handle_api_export_csv(self, request):
        """API endpoint for exporting spread history as CSV"""
        try:
            csv_data = self.spread_history.get_csv_export()
            return web.Response(
                text=csv_data,
                content_type='text/csv',
                headers={
                    'Content-Disposition': 'attachment; filename="spread_history.csv"'
                }
            )
        except Exception as e:
            logger.error(f"Error exporting CSV: {e}")
            return web.json_response({'error': str(e)}, status=500)

    async def handle_api_clear_heatmap(self, request):
        """API endpoint for clearing heatmap statistics"""
        try:
            self.spread_history.clear_hourly_stats()
            return web.json_response({'success': True, 'message': 'Heatmap stats cleared'})
        except Exception as e:
            logger.error(f"Error clearing heatmap stats: {e}")
            return web.json_response({'error': str(e)}, status=500)


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
