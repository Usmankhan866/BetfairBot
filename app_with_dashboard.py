"""
Complete Betfair Bot Dashboard with Live Betting Integration
"""

from flask import Flask, render_template_string, jsonify, request
from flask_cors import CORS
import json
import threading
import time
from datetime import datetime
from collections import deque
import logging

# Import your bot components
try:
    from betfair_client import BetfairClient
    from calculator import BettingCalculator
    from bet_manager import BetManager
    BETFAIR_AVAILABLE = True
except ImportError:
    BETFAIR_AVAILABLE = False
    print("⚠️ Betfair modules not available - running in demo mode")

app = Flask(__name__)
CORS(app)

# Global state
bot_running = False
bot_thread = None
bot_logs = deque(maxlen=100)
bot_stats = {
    "total_bets": 0,
    "total_stake": 0,
    "total_exposure": 0,
    "successful_bets": 0,
    "failed_bets": 0,
    "last_bet_time": None
}
bot_instance = None
processed_races = set()

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def add_log(message):
    """Add timestamped log entry"""
    timestamp = datetime.now().strftime("%H:%M:%S")
    bot_logs.append(f"[{timestamp}] {message}")
    logger.info(message)

def get_recent_logs(count=50):
    """Get recent log entries"""
    return list(bot_logs)[-count:]

class BotRunner:
    """Wrapper for bot execution"""
    
    def __init__(self, config):
        self.config = config
        self.client = None
        self.calculator = BettingCalculator() if BETFAIR_AVAILABLE else None
        self.bet_manager = None
        self.running = False
        self.processed_races = set()
        
    def initialize(self):
        """Initialize bot connection"""
        if not BETFAIR_AVAILABLE:
            add_log("⚠️ Betfair modules not available - Demo mode")
            return False
            
        try:
            add_log("🔌 Connecting to Betfair...")
            self.client = BetfairClient(
                app_key=self.config['app_key'],
                session_token=self.config['session_token']
            )
            
            if not self.client.connect():
                add_log("❌ Failed to connect to Betfair")
                add_log("💡 Check: Session token, App key, Internet")
                return False
            
            add_log("✅ Connected to Betfair successfully")
            
            # Initialize bet manager
            self.bet_manager = BetManager(
                stake=self.config['betting']['stake'],
                per_race_stop_loss=self.config['betting'].get('per_race_stop_loss', 20.0)
            )
            
            # Check balance
            balance = self.client.get_account_balance()
            if balance:
                add_log(f"💰 Account balance: ${balance:.2f}")
                global bot_stats
                bot_stats['balance'] = balance
            
            return True
            
        except Exception as e:
            add_log(f"❌ Initialization error: {str(e)}")
            return False
    
    def process_race(self, market_catalogue):
        """Process a single race"""
        try:
            market_id = market_catalogue.market_id
            event_name = market_catalogue.event.name
            
            # Skip if already processed
            if market_id in self.processed_races:
                return
            
            num_runners = len(market_catalogue.runners)
            min_runners = self.config['betting'].get('min_runners', 8)
            max_runners = self.config['betting'].get('max_runners', 14)
            
            # Check runner count
            if num_runners < min_runners or num_runners > max_runners:
                add_log(f"⏭️ {event_name}: {num_runners} runners (need {min_runners}-{max_runners})")
                self.processed_races.add(market_id)
                return
            
            add_log(f"🏇 Analyzing: {event_name} ({num_runners} runners)")
            
            # Get market data
            win_market = self.client.get_market_prices(market_id)
            if not win_market:
                add_log(f"⚠️ No win market data for {event_name}")
                return
            
            place_market_id = self.client.get_place_market_id(market_id)
            if not place_market_id:
                add_log(f"⚠️ No place market for {event_name}")
                self.processed_races.add(market_id)
                return
            
            place_market = self.client.get_market_prices(place_market_id)
            if not place_market:
                add_log(f"⚠️ No place market prices for {event_name}")
                return
            
            # Process runners
            bets_placed = 0
            for runner_cat in market_catalogue.runners:
                if not self.running:
                    break
                
                runner_name = runner_cat.runner_name
                selection_id = runner_cat.selection_id
                
                # Get prices
                win_runner = next((r for r in win_market.runners if r.selection_id == selection_id), None)
                if not win_runner:
                    continue
                
                win_lay_price = self.client.get_win_lay_price(win_runner)
                if not win_lay_price:
                    continue
                
                place_runner = next((r for r in place_market.runners if r.selection_id == selection_id), None)
                if not place_runner:
                    continue
                
                place_back_price = self.client.get_place_back_price(place_runner)
                if not place_back_price:
                    continue
                
                # Calculate if should bet
                should_bet, details = self.calculator.should_bet(
                    win_lay_price=win_lay_price,
                    actual_place_price=place_back_price,
                    num_runners=num_runners
                )
                
                if should_bet:
                    add_log(f"💡 BET SIGNAL: {runner_name} @ {place_back_price} (Edge: {details['edge']})")
                    
                    # Check stop loss
                    if not self.bet_manager.can_bet_on_race(market_id):
                        add_log(f"🛑 Stop loss reached for {event_name}")
                        break
                    
                    # Place bet
                    stake = self.config['betting']['stake']
                    add_log(f"🎯 Placing bet: ${stake} on {runner_name} @ {place_back_price}")
                    
                    bet_result = self.client.place_bet(
                        market_id=place_market_id,
                        selection_id=selection_id,
                        stake=stake,
                        price=place_back_price
                    )
                    
                    # Record bet
                    self.bet_manager.record_bet(
                        market_id=market_id,
                        runner_name=runner_name,
                        selection_id=selection_id,
                        stake=stake,
                        price=place_back_price,
                        bet_result=bet_result
                    )
                    
                    # Update stats
                    global bot_stats
                    if bet_result['success']:
                        add_log(f"✅ BET PLACED: {runner_name} - ID: {bet_result.get('bet_id')}")
                        bot_stats['successful_bets'] += 1
                        bets_placed += 1
                    else:
                        add_log(f"❌ BET FAILED: {bet_result.get('error')}")
                        bot_stats['failed_bets'] += 1
                    
                    bot_stats['total_bets'] += 1
                    bot_stats['total_stake'] += stake
                    bot_stats['last_bet_time'] = datetime.now().strftime("%H:%M:%S")
            
            if bets_placed == 0:
                add_log(f"ℹ️ No opportunities in {event_name}")
            else:
                add_log(f"✅ Placed {bets_placed} bet(s) in {event_name}")
            
            self.processed_races.add(market_id)
            
        except Exception as e:
            add_log(f"❌ Error processing race: {str(e)}")
    
    def run(self):
        """Main bot loop"""
        self.running = True
        add_log("🤖 Bot started")
        
        check_interval = self.config['betting'].get('check_interval_seconds', 60)
        
        while self.running:
            try:
                add_log("🔍 Scanning for races...")
                
                # Get races
                races = self.client.get_australian_thoroughbred_races(hours_ahead=2)
                
                if races:
                    add_log(f"📋 Found {len(races)} upcoming races")
                    for race in races:
                        if not self.running:
                            break
                        self.process_race(race)
                else:
                    add_log("ℹ️ No upcoming races found")
                
                # Wait
                if self.running:
                    add_log(f"⏳ Waiting {check_interval} seconds...")
                    time.sleep(check_interval)
                
            except Exception as e:
                add_log(f"❌ Bot error: {str(e)}")
                time.sleep(30)
        
        add_log("🛑 Bot stopped")

def run_bot_thread(config):
    """Background thread for bot"""
    global bot_instance, bot_running
    
    if not BETFAIR_AVAILABLE:
        add_log("⚠️ Running in DEMO MODE - No Betfair connection")
        while bot_running:
            add_log("Demo mode: Waiting for Betfair modules...")
            time.sleep(10)
        return
    
    try:
        bot_instance = BotRunner(config)
        
        if bot_instance.initialize():
            bot_instance.run()
        else:
            add_log("❌ Bot initialization failed")
            bot_running = False
    except Exception as e:
        add_log(f"❌ Bot thread error: {str(e)}")
        bot_running = False

# Flask Routes
@app.route('/')
def index():
    """Serve dashboard HTML"""
    return render_template_string(DASHBOARD_HTML)

@app.route('/api/status')
def get_status():
    """Get current bot status"""
    try:
        with open('config.json', 'r') as f:
            config = json.load(f)
    except:
        config = {
            "account": {"balance": 0, "currency": "USD"},
            "betting": {"min_odds": 2.0, "max_odds": 10.0, "stake": 2.0},
            "session_token": "",
            "app_key": ""
        }
    
    # Don't send full session token to frontend for security
    display_config = config.copy()
    if 'session_token' in display_config and display_config['session_token']:
        display_config['session_token'] = display_config['session_token'][:10] + '...'
    
    return jsonify({
        "status": "running" if bot_running else "stopped",
        "balance": config.get('account', {}).get('balance', 0),
        "currency": config.get('account', {}).get('currency', 'USD'),
        "stats": bot_stats,
        "config": {
            **config.get('betting', {}),
            "session_token": display_config.get('session_token', ''),
            "app_key": config.get('app_key', '')
        },
        "logs": get_recent_logs(),
        "betfair_available": BETFAIR_AVAILABLE
    })

@app.route('/api/start', methods=['POST'])
def start_bot():
    """Start the bot"""
    global bot_thread, bot_running
    
    if bot_running:
        return jsonify({"success": False, "message": "Bot is already running"})
    
    try:
        # Load config
        with open('config.json', 'r') as f:
            config = json.load(f)
        
        add_log("🚀 Starting bot...")
        
        bot_running = True
        bot_thread = threading.Thread(target=run_bot_thread, args=(config,), daemon=True)
        bot_thread.start()
        
        return jsonify({"success": True, "message": "Bot started successfully"})
    except Exception as e:
        bot_running = False
        add_log(f"❌ Failed to start: {str(e)}")
        return jsonify({"success": False, "message": f"Failed to start bot: {str(e)}"})

@app.route('/api/stop', methods=['POST'])
def stop_bot():
    """Stop the bot"""
    global bot_running, bot_instance
    
    if not bot_running:
        return jsonify({"success": False, "message": "Bot is not running"})
    
    add_log("🛑 Stopping bot...")
    bot_running = False
    
    if bot_instance:
        bot_instance.running = False
    
    return jsonify({"success": True, "message": "Bot stopped successfully"})

@app.route('/api/config', methods=['POST'])
def update_config():
    """Update configuration"""
    try:
        new_config = request.json
        
        # Load existing config or create new one
        try:
            with open('config.json', 'r') as f:
                config = json.load(f)
        except:
            config = {
                "account": {"balance": 0, "currency": "USD"},
                "betting": {}
            }
        
        # Update session token and app key at root level
        if 'session_token' in new_config:
            config['session_token'] = new_config['session_token']
            add_log("🔑 Session token updated")
        
        if 'app_key' in new_config:
            config['app_key'] = new_config['app_key']
            add_log("🔐 App key updated")
        
        # Update betting config
        if 'betting' not in config:
            config['betting'] = {}
        
        if 'min_odds' in new_config:
            config['betting']['min_odds'] = new_config['min_odds']
        if 'max_odds' in new_config:
            config['betting']['max_odds'] = new_config['max_odds']
        if 'stake' in new_config:
            config['betting']['stake'] = new_config['stake']
        
        # Save config
        with open('config.json', 'w') as f:
            json.dump(config, f, indent=4)
        
        add_log("⚙️ Configuration saved successfully")
        return jsonify({"success": True, "message": "Configuration saved! Restart bot to apply changes."})
    except Exception as e:
        add_log(f"❌ Config save error: {str(e)}")
        return jsonify({"success": False, "message": str(e)})

# Dashboard HTML
DASHBOARD_HTML = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Betfair Bot Dashboard</title>
    <style>
        * {
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }
        
        body {
            font-family: 'Inter', 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
            background: #ffffff;
            color: #2c3e50;
            min-height: 100vh;
            padding: 20px;
        }
        
        .container {
            max-width: 1400px;
            margin: 0 auto;
        }
        
        .header {
            background: linear-gradient(135deg, #778873 0%, #A1BC98 100%);
            border-radius: 20px;
            padding: 30px;
            text-align: center;
            margin-bottom: 25px;
            box-shadow: 0 8px 24px rgba(119, 136, 115, 0.3);
        }
        
        .header h1 {
            font-size: 2.5em;
            margin-bottom: 10px;
            color: white;
            font-weight: 700;
        }
        
        .header p {
            color: rgba(255, 255, 255, 0.9);
            font-size: 1.1em;
            font-weight: 500;
        }
        
        .warning-banner {
            background: #fff3cd;
            border: 2px solid #ffc107;
            border-radius: 15px;
            padding: 20px;
            margin: 20px 0;
            text-align: center;
            box-shadow: 0 4px 12px rgba(255,193,7,0.2);
        }
        
        .warning-banner h3 {
            color: #856404;
            margin-bottom: 8px;
            font-size: 1.3em;
        }
        
        .warning-banner p {
            color: #664d03;
            font-weight: 500;
        }
        
        .controls {
            display: flex;
            gap: 15px;
            justify-content: center;
            margin-bottom: 30px;
            flex-wrap: wrap;
        }
        
        .btn {
            padding: 18px 45px;
            font-size: 18px;
            border: none;
            border-radius: 12px;
            cursor: pointer;
            font-weight: 600;
            transition: all 0.3s ease;
            box-shadow: 0 4px 12px rgba(0,0,0,0.15);
            font-family: inherit;
        }
        
        .btn:hover {
            transform: translateY(-3px);
            box-shadow: 0 8px 20px rgba(0,0,0,0.2);
        }
        
        .btn:active {
            transform: translateY(-1px);
        }
        
        .btn-start {
            background: #A1BC98;
            color: white;
        }
        
        .btn-start:hover {
            background: #8da884;
        }
        
        .btn-stop {
            background: #e74c3c;
            color: white;
        }
        
        .btn-stop:hover {
            background: #c0392b;
        }
        
        .stats-grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
            gap: 20px;
            margin-bottom: 30px;
        }
        
        .stat-card {
            background: white;
            border-radius: 15px;
            padding: 25px;
            text-align: center;
            box-shadow: 0 4px 12px rgba(119, 136, 115, 0.15);
            transition: all 0.3s ease;
            border-left: 4px solid #A1BC98;
            border: 1px solid #e9ecef;
        }
        
        .stat-card:hover {
            transform: translateY(-5px);
            box-shadow: 0 8px 20px rgba(119, 136, 115, 0.25);
            border-left: 4px solid #778873;
        }
        
        .stat-label {
            font-size: 13px;
            color: #778873;
            margin-bottom: 12px;
            text-transform: uppercase;
            font-weight: 600;
            letter-spacing: 0.5px;
        }
        
        .stat-value {
            font-size: 32px;
            font-weight: 700;
            color: #2c3e50;
        }
        
        .main-content {
            display: grid;
            grid-template-columns: 2fr 1fr;
            gap: 25px;
        }
        
        .card {
            background: white;
            border-radius: 20px;
            padding: 30px;
            box-shadow: 0 4px 12px rgba(119, 136, 115, 0.15);
            border: 1px solid #e9ecef;
        }
        
        .card h2 {
            margin-bottom: 20px;
            font-size: 1.6em;
            color: #778873;
            font-weight: 700;
            padding-bottom: 15px;
            border-bottom: 3px solid #A1BC98;
        }
        
        .logs-container {
            background: #f8f9fa;
            border: 2px solid #e9ecef;
            border-radius: 12px;
            padding: 20px;
            height: 450px;
            overflow-y: auto;
            font-family: 'Consolas', 'Monaco', 'Courier New', monospace;
            font-size: 13px;
            line-height: 1.6;
        }
        
        .logs-container::-webkit-scrollbar {
            width: 8px;
        }
        
        .logs-container::-webkit-scrollbar-track {
            background: #e9ecef;
            border-radius: 10px;
        }
        
        .logs-container::-webkit-scrollbar-thumb {
            background: #A1BC98;
            border-radius: 10px;
        }
        
        .log-entry {
            padding: 8px 0;
            border-bottom: 1px solid #e9ecef;
            color: #2c3e50;
        }
        
        .log-entry:last-child {
            border-bottom: none;
        }
        
        .config-form {
            display: grid;
            gap: 20px;
        }
        
        .form-group {
            display: grid;
            gap: 8px;
            margin-bottom: 5px;
        }
        
        .form-group label {
            font-size: 14px;
            font-weight: 600;
            color: #778873;
            text-transform: uppercase;
            letter-spacing: 0.5px;
            margin-bottom: 5px;
        }
        
        .form-group input {
            padding: 14px 16px;
            border-radius: 10px;
            border: 2px solid #e9ecef;
            background: #f8f9fa;
            color: #2c3e50;
            font-size: 16px;
            font-weight: 500;
            transition: all 0.3s ease;
            font-family: inherit;
            width: 100%;
            box-sizing: border-box;
        }
        
        .form-group input:focus {
            outline: none;
            border-color: #A1BC98;
            background: white;
            box-shadow: 0 0 0 3px rgba(161, 188, 152, 0.1);
        }
        
        .form-group small {
            font-size: 12px;
            font-weight: 400;
            color: #6c757d;
            margin-top: 4px;
            line-height: 1.4;
        }
        
        .form-group input[type="password"] {
            font-family: 'Courier New', monospace;
            letter-spacing: 1px;
        }
        
        .form-group input::placeholder {
            color: #adb5bd;
            font-style: italic;
        }
        
        .btn-save {
            background: #778873;
            color: white;
            padding: 15px;
            margin-top: 10px;
            font-weight: 600;
        }
        
        .btn-save:hover {
            background: #5f6e5c;
        }
        
        .status-indicator {
            display: inline-block;
            width: 12px;
            height: 12px;
            border-radius: 50%;
            margin-right: 8px;
            animation: pulse 2s infinite;
        }
        
        @keyframes pulse {
            0%, 100% { opacity: 1; }
            50% { opacity: 0.5; }
        }
        
        .success-text { color: #27ae60; }
        .warning-text { color: #f39c12; }
        .danger-text { color: #e74c3c; }
        .info-text { color: #3498db; }
        
        @media (max-width: 968px) {
            .main-content {
                grid-template-columns: 1fr;
            }
            
            .stats-grid {
                grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
            }
            
            .header h1 {
                font-size: 2em;
            }
        }
    </style>
</head>
<body>

    <div class="container">
        <div class="header">
            <h1>🏇 Betfair Place Betting Bot</h1>
            <p>Live Trading Dashboard</p>
        </div>
        
        <div class="warning-banner">
            <h3>⚠️ LIVE TRADING MODE</h3>
            <p>This bot places REAL bets with REAL money!</p>
        </div>
        
        <div class="controls">
            <button class="btn btn-start" onclick="startBot()">▶️ Start Bot</button>
            <button class="btn btn-stop" onclick="stopBot()">⏹️ Stop Bot</button>
        </div>
        
        <div class="stats-grid">
            <div class="stat-card">
                <div class="stat-label">Status</div>
                <div class="stat-value" id="botStatus">🔴 Stopped</div>
            </div>
            <div class="stat-card">
                <div class="stat-label">Connection</div>
                <div class="stat-value" id="connectionStatus">⭕ Not Connected</div>
            </div>
            <div class="stat-card">
                <div class="stat-label">Balance</div>
                <div class="stat-value" id="balance">$0.00</div>
            </div>
            <div class="stat-card">
                <div class="stat-label">Total Bets</div>
                <div class="stat-value" id="totalBets">0</div>
            </div>
            <div class="stat-card">
                <div class="stat-label">Successful</div>
                <div class="stat-value" id="successfulBets">0</div>
            </div>
            <div class="stat-card">
                <div class="stat-label">Failed</div>
                <div class="stat-value" id="failedBets">0</div>
            </div>
            <div class="stat-card">
                <div class="stat-label">Total Stake</div>
                <div class="stat-value" id="totalStake">$0.00</div>
            </div>
            <div class="stat-card">
                <div class="stat-label">Last Bet</div>
                <div class="stat-value" id="lastBet">Never</div>
            </div>
        </div>
        
        <div class="main-content">
            <div class="card">
                <h2>📝 Live Logs</h2>
                <div class="logs-container" id="logs">
                    <div class="log-entry">Waiting for bot to start...</div>
                </div>
            </div>
            
            <div class="card">
                <h2>⚙️ Configuration</h2>
                <div class="config-form">
                    <div class="form-group">
                        <label>Session Token</label>
                        <input type="password" id="sessionToken" placeholder="Enter Betfair session token">
                        <small>Your Betfair API session token (keep secure)</small>
                    </div>
                    <div class="form-group">
                        <label>App Key</label>
                        <input type="text" id="appKey" placeholder="Enter Betfair app key">
                        <small>Your Betfair application key</small>
                    </div>
                    <div class="form-group">
                        <label>Min Odds</label>
                        <input type="number" id="minOdds" step="0.1" value="2.0">
                        <small>Minimum odds to consider for betting</small>
                    </div>
                    <div class="form-group">
                        <label>Max Odds</label>
                        <input type="number" id="maxOdds" step="0.1" value="10.0">
                        <small>Maximum odds to consider for betting</small>
                    </div>
                    <div class="form-group">
                        <label>Stake ($)</label>
                        <input type="number" id="stake" step="0.5" value="2.0">
                        <small>Amount to stake per bet</small>
                    </div>
                    <button class="btn btn-save" onclick="saveConfig()">💾 Save Config</button>
                </div>
            </div>
        </div>
    </div>
    
    <script>
        function startBot() {
            if (!confirm('⚠️ START LIVE BETTING?\\n\\nThis will place REAL bets with REAL money!\\n\\nAre you sure?')) {
                return;
            }
            
            fetch('/api/start', { method: 'POST' })
                .then(response => response.json())
                .then(data => {
                    alert(data.message);
                    updateStatus();
                })
                .catch(error => alert('Error starting bot: ' + error));
        }
        
        function stopBot() {
            fetch('/api/stop', { method: 'POST' })
                .then(response => response.json())
                .then(data => {
                    alert(data.message);
                    updateStatus();
                })
                .catch(error => alert('Error stopping bot: ' + error));
        }
        
        function saveConfig() {
            const config = {
                session_token: document.getElementById('sessionToken').value,
                app_key: document.getElementById('appKey').value,
                min_odds: parseFloat(document.getElementById('minOdds').value),
                max_odds: parseFloat(document.getElementById('maxOdds').value),
                stake: parseFloat(document.getElementById('stake').value)
            };
            
            if (!config.session_token) {
                alert('⚠️ Please enter a session token!');
                return;
            }
            
            if (!config.app_key) {
                alert('⚠️ Please enter an app key!');
                return;
            }
            
            fetch('/api/config', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(config)
            })
                .then(response => response.json())
                .then(data => {
                    if (data.success) {
                        alert('✅ ' + data.message);
                    } else {
                        alert('❌ ' + data.message);
                    }
                })
                .catch(error => alert('Error saving config: ' + error));
        }
        
        function updateStatus() {
            fetch('/api/status')
                .then(response => response.json())
                .then(data => {
                    // Status
                    const statusEl = document.getElementById('botStatus');
                    if (data.status === 'running') {
                        statusEl.innerHTML = '<span class="status-indicator" style="background: #27ae60;"></span><span class="success-text">Running</span>';
                    } else {
                        statusEl.innerHTML = '<span class="status-indicator" style="background: #e74c3c;"></span><span class="danger-text">Stopped</span>';
                    }
                    
                    // Connection
                    const connEl = document.getElementById('connectionStatus');
                    const recentLogs = data.logs.join(' ');
                    if (!data.betfair_available) {
                        connEl.innerHTML = '<span class="status-indicator" style="background: #f39c12;"></span><span class="warning-text">Demo Mode</span>';
                    } else if (recentLogs.includes('Connected to Betfair')) {
                        connEl.innerHTML = '<span class="status-indicator" style="background: #27ae60;"></span><span class="success-text">Connected</span>';
                    } else if (recentLogs.includes('Failed to connect')) {
                        connEl.innerHTML = '<span class="status-indicator" style="background: #e74c3c;"></span><span class="danger-text">Failed</span>';
                    } else {
                        connEl.innerHTML = '<span class="status-indicator" style="background: #95a5a6;"></span><span style="color: #95a5a6;">Not Connected</span>';
                    }
                    
                    // Balance
                    document.getElementById('balance').textContent = 
                        `${data.currency} ${data.balance.toFixed(2)}`;
                    
                    // Stats
                    document.getElementById('totalBets').textContent = data.stats.total_bets;
                    document.getElementById('successfulBets').textContent = data.stats.successful_bets;
                    document.getElementById('failedBets').textContent = data.stats.failed_bets;
                    document.getElementById('totalStake').textContent = 
                        `${data.currency} ${data.stats.total_stake.toFixed(2)}`;
                    document.getElementById('lastBet').textContent = 
                        data.stats.last_bet_time || 'Never';
                    
                    // Config - Load session token and app key too
                    if (data.config.session_token) {
                        document.getElementById('sessionToken').value = data.config.session_token;
                    }
                    if (data.config.app_key) {
                        document.getElementById('appKey').value = data.config.app_key;
                    }
                    if (data.config.min_odds) {
                        document.getElementById('minOdds').value = data.config.min_odds;
                    }
                    if (data.config.max_odds) {
                        document.getElementById('maxOdds').value = data.config.max_odds;
                    }
                    if (data.config.stake) {
                        document.getElementById('stake').value = data.config.stake;
                    }
                    
                    // Logs
                    const logsEl = document.getElementById('logs');
                    logsEl.innerHTML = data.logs.map(log => 
                        `<div class="log-entry">${log}</div>`
                    ).join('');
                    logsEl.scrollTop = logsEl.scrollHeight;
                })
                .catch(error => console.error('Error:', error));
        }
        
        // Update every 3 seconds
        setInterval(updateStatus, 3000);
        updateStatus();
    </script>
</body>
</html>
"""

if __name__ == '__main__':
    print("\n" + "="*60)
    print("🏇 BETFAIR BOT DASHBOARD")
    print("="*60)
    print("Dashboard URL: http://localhost:5000")
    print("="*60)
    print("\n✅ Server starting...\n")
    
    app.run(debug=True, host='0.0.0.0', port=5000)