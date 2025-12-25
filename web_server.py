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
    from aiohttp import web, WSMsgType
except ImportError:
    logging.warning("aiohttp not installed. Web dashboard will not be available.")
    web = None

logger = logging.getLogger(__name__)


# Content Security Policy Middleware
@web.middleware
async def csp_middleware(request, handler):
    """Add Content Security Policy headers to all responses"""
    response = await handler(request)
    
    # CSP policy configuration
    # Strict CSP without unsafe-eval to prevent code injection
    # unsafe-inline is still needed for inline styles in the HTML
    csp_policy = (
        "default-src 'self'; "
        "script-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; "
        "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
        "img-src 'self' data:; "
        "font-src 'self' https://fonts.gstatic.com; "
        "connect-src 'self' ws: wss:; "
        "frame-ancestors 'none'; "
        "base-uri 'self'; "
        "form-action 'self'"
    )
    
    response.headers['Content-Security-Policy'] = csp_policy
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['X-Frame-Options'] = 'DENY'
    response.headers['X-XSS-Protection'] = '1; mode=block'
    
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
            'MAX_POSITION_SIZE': (
                r"(\"MAX_POSITION_CONTRACTS\"\s*:\s*)([0-9.-]+)",
                r"\g<1>{value}",
                "RISK_CONFIG"
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
        
        # Web directory path
        self.web_dir = Path(__file__).parent / "web"

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
                await self.send_to_client(ws, 'command_result', {
                    'success': success,
                    'message': f'Position #{position_id} closed successfully' if success else f'Failed to close position #{position_id}',
                    'error': None if success else 'Position not found or could not be closed'
                })
        
        elif msg_type == 'bot_command':
            # Handle bot control commands (start/pause/stop)
            command = data.get('command', '').lower()
            result = await self.handle_bot_command(command)
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
    
    async def close_position(self, position_id):
        """Close a specific position"""
        try:
            arb_engine = getattr(self.bot, 'arb_engine', None)
            if not arb_engine or not hasattr(arb_engine, 'get_open_positions'):
                return False

            positions = arb_engine.get_open_positions()
            for pos in positions:
                if pos.id == position_id:
                    # Execute close logic
                    if hasattr(arb_engine, 'close_position'):
                        await arb_engine.close_position(pos)
                        return True
            return False
        except Exception as e:
            logger.error(f"Error closing position {position_id}: {e}")
            return False
    
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
                if -0.01 <= value <= 0.0001:  # -1.0% to 0.01%
                    if isinstance(bot_config, dict):
                        bot_config['MIN_SPREAD_EXIT'] = value
                    config_to_save['MIN_SPREAD_EXIT'] = value
                    updated_fields.append(f"MIN_SPREAD_EXIT={value*100:.2f}%")
                else:
                    return {
                        'success': False,
                        'error': 'MIN_SPREAD_EXIT must be between -1.0% and 0.01%'
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
                    # Note: This field is not in config.py, only in memory
                    updated_fields.append(f"MAX_CONCURRENT_POSITIONS={value}")
                else:
                    return {
                        'success': False,
                        'error': 'MAX_CONCURRENT_POSITIONS must be between 1 and 10'
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
                    config_to_save['DAILY_LOSS_LIMIT'] = value
                    updated_fields.append(f"DAILY_LOSS_LIMIT=${value}")
                else:
                    return {
                        'success': False,
                        'error': 'DAILY_LOSS_LIMIT must be between 10 and 10000'
                    }

            if 'MAX_POSITION_SIZE' in config:
                value = float(config['MAX_POSITION_SIZE'])
                if 0.1 <= value <= 100:
                    if isinstance(bot_config, dict):
                        bot_config['MAX_POSITION_SIZE'] = value
                    config_to_save['MAX_POSITION_SIZE'] = value
                    updated_fields.append(f"MAX_POSITION_SIZE={value}")
                else:
                    return {
                        'success': False,
                        'error': 'MAX_POSITION_SIZE must be between 0.1 and 100'
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

                positions.append({
                    'id': pos.id,
                    'direction': direction_code or str(direction_obj),
                    'direction_label': direction_label,
                    'exit_spread': pos.current_exit_spread,
                    'current_exit_spread': pos.current_exit_spread,
                    'exit_target': pos.exit_target,
                    'age': pos.get_age_formatted() if hasattr(pos, 'get_age_formatted') else '--',
                    'should_close': pos.should_close() if hasattr(pos, 'should_close') else False
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

        return {
            'timestamp': datetime.now().strftime('%H:%M:%S'),
            'runtime': runtime,
            'trading_mode': mode,
            'bitget_healthy': getattr(self.bot, 'bitget_healthy', False),
            'hyper_healthy': getattr(self.bot, 'hyper_healthy', False),
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
            'config': bot_config,
            'spread_chart_data': self._get_spread_chart_data()
        }
    
    def _get_spread_chart_data(self) -> Dict:
        """Получение данных для графика спредов"""
        try:
            # Получаем историю спредов из arb_engine или создаем из текущих данных
            if hasattr(self.bot, 'arb_engine') and hasattr(self.bot.arb_engine, 'get_spread_history'):
                # Если есть менеджер истории
                history_data = self.bot.arb_engine.get_spread_history(100)
                if history_data:
                    return history_data

            # Иначе создаем из текущих данных
            bitget_ws = getattr(self.bot, 'bitget_ws', None)
            hyper_ws = getattr(self.bot, 'hyper_ws', None)
            arb_engine = getattr(self.bot, 'arb_engine', None)

            if not bitget_ws or not hyper_ws or not arb_engine:
                return self._empty_chart_data()

            bitget_data = bitget_ws.get_latest_data() if hasattr(bitget_ws, 'get_latest_data') else None
            hyper_data = hyper_ws.get_latest_data() if hasattr(hyper_ws, 'get_latest_data') else None

            if bitget_data and hyper_data:
                bitget_slippage = bitget_ws.get_estimated_slippage() if hasattr(bitget_ws, 'get_estimated_slippage') else None
                hyper_slippage = hyper_ws.get_estimated_slippage() if hasattr(hyper_ws, 'get_estimated_slippage') else None

                spreads = arb_engine.calculate_spreads(
                    bitget_data, hyper_data, bitget_slippage, hyper_slippage
                ) if hasattr(arb_engine, 'calculate_spreads') else {}

                exit_spreads = arb_engine.calculate_exit_spread_for_market(
                    bitget_data, hyper_data, bitget_slippage, hyper_slippage
                ) if hasattr(arb_engine, 'calculate_exit_spread_for_market') else {}

                if spreads and exit_spreads:
                    entry_bh = 0.0
                    entry_hb = 0.0
                    for direction, spread_data in spreads.items():
                        code = self._normalize_direction_code(direction)
                        if not code or not isinstance(spread_data, dict):
                            continue
                        if code == 'B_TO_H':
                            entry_bh = float(spread_data.get('gross_spread', 0) or 0)
                        elif code == 'H_TO_B':
                            entry_hb = float(spread_data.get('gross_spread', 0) or 0)

                    exit_bh = 0.0
                    exit_hb = 0.0
                    for direction, spread_value in exit_spreads.items():
                        code = self._normalize_direction_code(direction)
                        if not code:
                            continue
                        if code == 'B_TO_H':
                            exit_bh = float(spread_value or 0)
                        elif code == 'H_TO_B':
                            exit_hb = float(spread_value or 0)

                    now = datetime.now().strftime('%H:%M:%S')
                    return {
                        'labels': [now],
                        'datasets': {
                            'entry_bh': [entry_bh],
                            'entry_hb': [entry_hb],
                            'exit_bh': [exit_bh],
                            'exit_hb': [exit_hb],
                        },
                        'timestamps': [time.time()],
                        'health': {
                            'bitget': [getattr(self.bot, 'bitget_healthy', False)],
                            'hyper': [getattr(self.bot, 'hyper_healthy', False)],
                        }
                    }
        except Exception as e:
            logger.debug(f"Error getting spread chart data: {e}")

        return self._empty_chart_data()

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
                    logger.debug(
                        "_periodic_updates(): broadcasting full_update to %s client(s)",
                        len(self.ws_clients),
                    )
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
                    'size': getattr(pos, 'size', 0),
                    'entry_price': pos.entry_prices if hasattr(pos, 'entry_prices') else {},
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
        portfolio = {}
        try:
            paper_executor = getattr(self.bot, 'paper_executor', None)
            if paper_executor and hasattr(paper_executor, 'get_portfolio'):
                portfolio = paper_executor.get_portfolio()
        except Exception as e:
            return web.json_response({'error': str(e)}, status=500)

        return web.json_response({'portfolio': portfolio})

    async def handle_api_stats(self, request):
        """API endpoint for session stats"""
        session_stats = getattr(self.bot, 'session_stats', {})
        best_spreads_session = getattr(self.bot, 'best_spreads_session', {})
        return web.json_response({
            'session_stats': session_stats,
            'best_spreads_session': best_spreads_session
        })


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
