# Configuration Persistence Feature

## Overview

Configuration changes made through the web dashboard are now automatically saved to `config.py`, ensuring they persist across bot restarts.

## Supported Parameters

### Trading Configuration
- **MIN_SPREAD_ENTER**: Minimum gross spread required to enter a position (saved to `TRADING_CONFIG['MIN_SPREAD_ENTER']`)
- **MIN_SPREAD_EXIT**: Target gross spread to exit a position (saved to `TRADING_CONFIG['MIN_SPREAD_EXIT']`)

### Risk Configuration
- **DAILY_LOSS_LIMIT**: Maximum daily loss limit in USD (saved to `RISK_CONFIG["MAX_DAILY_LOSS"]`)
- **MAX_POSITION_SIZE**: Maximum position size in contracts (saved to `RISK_CONFIG["MAX_POSITION_CONTRACTS"]`)

### Runtime-Only Parameters
These parameters are updated in memory but NOT saved to config.py:
- **MAX_POSITION_AGE_HOURS**: Maximum age for positions before forced exit
- **MAX_CONCURRENT_POSITIONS**: Maximum number of concurrent positions

## How It Works

1. **User updates config** through web dashboard
2. **In-memory config is updated** immediately for the running bot
3. **save_config_to_file()** is called to persist changes
4. **Regex patterns** find and replace specific values in config.py
5. **Backup created** (.bak file) before modifying config.py
6. **Changes written** to config.py with proper Python syntax
7. **Success/error message** returned to web UI

## Implementation Details

### Function: `save_config_to_file(config_updates: Dict[str, Any])`

Located in `web_server.py`, this function:
- Accepts a dictionary of config updates
- Reads current config.py
- Uses regex patterns to find and replace values
- Creates automatic backup before writing
- Logs all changes
- Returns success/error status

### Regex Patterns

The function uses different quote styles based on the config section:
- **TRADING_CONFIG**: Uses single quotes (`'MIN_SPREAD_ENTER'`)
- **RISK_CONFIG**: Uses double quotes (`"MAX_DAILY_LOSS"`)

Pattern examples:
```python
'MIN_SPREAD_ENTER': r"('MIN_SPREAD_ENTER'\s*:\s*)([0-9.-]+)"
'MAX_DAILY_LOSS': r"(\"MAX_DAILY_LOSS\"\s*:\s*)([0-9.-]+)"
```

### Handler Integration

Both config handlers call `save_config_to_file()`:
- `handle_config_update()`: Trading parameters
- `handle_risk_config_update()`: Risk management parameters

## Error Handling

- If file save fails, in-memory config remains updated
- Error message is returned to web UI
- Original config.py is backed up before any modifications
- All operations are logged for debugging

## Testing

Run the test suite to verify functionality:

```bash
# Basic functionality test
python test_config_save.py

# Integration test with web server handlers
python test_integration_config_save.py
```

## Backup Files

Each time config.py is modified:
- A backup is created: `config.py.bak`
- Previous backup is overwritten
- Backup contains the state BEFORE the current change

To restore from backup:
```bash
cp config.py.bak config.py
```

## Logging

All config changes are logged with emojis for easy identification:
- ✅ Configuration saved successfully
- 📝 Updated fields listed
- 💾 Backup location
- ❌ Errors with full traceback

## Example Usage

### Via Web Dashboard

1. Open dashboard at `http://localhost:8080`
2. Navigate to Settings section
3. Modify MIN_SPREAD_ENTER value
4. Click "Save" button
5. Changes are applied immediately and saved to file
6. Success message displayed: "Configuration updated in memory: MIN_SPREAD_ENTER=0.25% | Configuration saved to file: MIN_SPREAD_ENTER=0.0025"

### Programmatically

```python
from web_server import save_config_to_file

result = save_config_to_file({
    'MIN_SPREAD_ENTER': 0.002,
    'MIN_SPREAD_EXIT': -0.0004,
    'DAILY_LOSS_LIMIT': 500.0,
    'MAX_POSITION_SIZE': 3.0
})

if result['success']:
    print(result['message'])
else:
    print(f"Error: {result['error']}")
```

## Future Enhancements

Potential improvements:
- Support for more config parameters
- Config versioning with multiple backups
- Rollback functionality
- Config validation before save
- Diff view showing changes
- Config history tracking
