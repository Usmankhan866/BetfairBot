# Betfair Bot Dashboard

A Flask-based web dashboard for automated Betfair place betting.

## Project Structure

```
BETFAIRBOT/
│── app.py              # Main Flask application
│── bet_manager.py      # Manages betting operations and tracking
│── betfair_client.py   # Betfair API client wrapper
│── calculator.py       # Betting calculations and strategy
│── config.json         # Configuration settings
│── requirements.txt    # Python dependencies
└── templates/
    └── dashboard.html  # Web dashboard template
```

## Installation

1. Install Python dependencies:
```bash
pip install -r requirements.txt
```

2. Update your `config.json` with your Betfair credentials:
```json
{
    "app_key": "your_betfair_app_key",
    "session_token": "your_session_token",
    "betting": {
        "stake": 10,
        "min_odds": 2,
        "max_odds": 10
    }
}
```

## Running the Application

```bash
python app.py
```

Then open your browser to: `http://localhost:5000`

## Features

- **Live Dashboard**: Real-time betting statistics and logs
- **Configuration Management**: Update settings through web interface
- **Secure**: Session tokens are masked in the frontend
- **Responsive**: Works on desktop and mobile devices

## API Endpoints

- `GET /` - Serve dashboard
- `GET /api/status` - Get bot status and stats
- `POST /api/start` - Start the bot
- `POST /api/stop` - Stop the bot
- `POST /api/config` - Update configuration

## Safety Features

- Live trading confirmation dialog
- Per-race stop loss limits
- Connection status monitoring
- Real-time error logging

## Configuration Options

| Setting | Description | Default |
|---------|-------------|---------|
| `stake` | Amount to bet per selection | 10 |
| `per_race_stop_loss` | Maximum loss per race | 50 |
| `min_odds` | Minimum odds threshold | 2.0 |
| `max_odds` | Maximum odds threshold | 10.0 |
| `min_runners` | Minimum runners in race | 8 |
| `max_runners` | Maximum runners in race | 14 |

⚠️ **Warning**: This bot places real bets with real money. Always test thoroughly and understand the risks before use.
