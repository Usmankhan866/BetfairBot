"""
Complete Betfair Bot Dashboard with Live Betting Integration
Fixed version with proper balance tracking and state management
"""

from flask import Flask, render_template, jsonify, request
from flask_cors import CORS
import json
import threading
import time
from datetime import datetime
from collections import deque
import logging
import os

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
    "last_bet_time": None,
    "balance": 0.0  # Initialize balance
}
bot_instance = None
bot_lock = threading.Lock()

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

def add_log(message):
    """Add timestamped log entry"""
    timestamp = datetime.now().strftime("%H:%M:%S")
    log_entry = f"[{timestamp}] {message}"
    bot_logs.append(log_entry)
    logger.info(message)

def get_recent_logs(count=50):
    """Get recent log entries"""
    return list(bot_logs)[-count:]

def load_config():
    """Load configuration from file"""
    try:
        if os.path.exists('config.json'):
            with open('config.json', 'r') as f:
                return json.load(f)
    except Exception as e:
        logger.error(f"Error loading config: {e}")
    
    # Default config
    return {
        "account": {
            "balance": 0,
            "currency": "AUD"
        },
        "betting": {
            "min_odds": 2.0,
            "max_odds": 10.0,
            "stake": 2.0,
            "min_runners": 8,
            "max_runners": 14,
            "per_race_stop_loss": 20.0,
            "check_interval_seconds": 60
        },
        "session_token": "",
        "app_key": ""
    }

def save_config(config):
    """Save configuration to file"""
    try:
        with open('config.json', 'w') as f:
            json.dump(config, f, indent=4)
        return True
    except Exception as e:
        logger.error(f"Error saving config: {e}")
        return False

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
        global bot_stats
        
        if not BETFAIR_AVAILABLE:
            add_log("⚠️ Betfair modules not available - Demo mode")
            return False
            
        try:
            add_log("🔌 Connecting to Betfair...")
            
            # Validate credentials
            if not self.config.get('session_token') or not self.config.get('app_key'):
                add_log("❌ Missing session token or app key")
                return False
            
            self.client = BetfairClient(
                app_key=self.config['app_key'],
                session_token=self.config['session_token']
            )
            
            if not self.client.connect():
                add_log("❌ Failed to connect to Betfair")
                add_log("💡 Check: Session token, App key, Internet connection")
                return False
            
            add_log("✅ Connected to Betfair successfully")
            
            # Initialize bet manager
            self.bet_manager = BetManager(
                stake=self.config['betting']['stake'],
                per_race_stop_loss=self.config['betting'].get('per_race_stop_loss', 20.0)
            )
            
            # Check and update balance
            balance = self.client.get_account_balance()
            if balance is not None:
                with bot_lock:
                    bot_stats['balance'] = float(balance)
                add_log(f"💰 Account balance: ${balance:.2f}")
            else:
                add_log("⚠️ Could not retrieve account balance")
            
            return True
            
        except Exception as e:
            add_log(f"❌ Initialization error: {str(e)}")
            logger.exception("Initialization error details:")
            return False
    
    def update_balance(self):
        """Update account balance"""
        global bot_stats
        try:
            if self.client:
                balance = self.client.get_account_balance()
                if balance is not None:
                    with bot_lock:
                        bot_stats['balance'] = float(balance)
        except Exception as e:
            logger.error(f"Error updating balance: {e}")
    
    def process_race(self, market_catalogue):
        """Process a single race"""
        global bot_stats
        
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
                    edge = details.get('edge', 0)
                    add_log(f"💡 BET SIGNAL: {runner_name} @ {place_back_price} (Edge: {edge:.2%})")
                    
                    # Check stop loss
                    if not self.bet_manager.can_bet_on_race(market_id):
                        add_log(f"🛑 Stop loss reached for {event_name}")
                        break
                    
                    # Place bet
                    stake = self.config['betting']['stake']
                    add_log(f"🎯 Placing bet: ${stake:.2f} on {runner_name} @ {place_back_price}")
                    
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
                    with bot_lock:
                        if bet_result.get('success'):
                            bet_id = bet_result.get('bet_id', 'N/A')
                            add_log(f"✅ BET PLACED: {runner_name} - ID: {bet_id}")
                            bot_stats['successful_bets'] += 1
                            bets_placed += 1
                        else:
                            error = bet_result.get('error', 'Unknown error')
                            add_log(f"❌ BET FAILED: {error}")
                            bot_stats['failed_bets'] += 1
                        
                        bot_stats['total_bets'] += 1
                        bot_stats['total_stake'] += stake
                        bot_stats['last_bet_time'] = datetime.now().strftime("%H:%M:%S")
                    
                    # Update balance after bet
                    self.update_balance()
                    
                    # Small delay between bets
                    time.sleep(1)
            
            if bets_placed == 0:
                add_log(f"ℹ️ No opportunities in {event_name}")
            else:
                add_log(f"✅ Placed {bets_placed} bet(s) in {event_name}")
            
            self.processed_races.add(market_id)
            
        except Exception as e:
            add_log(f"❌ Error processing race: {str(e)}")
            logger.exception("Race processing error details:")
    
    def run(self):
        """Main bot loop"""
        self.running = True
        add_log("🤖 Bot started")
        
        check_interval = self.config['betting'].get('check_interval_seconds', 60)
        balance_update_counter = 0
        
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
                
                # Update balance periodically (every 5 cycles)
                balance_update_counter += 1
                if balance_update_counter >= 5:
                    self.update_balance()
                    balance_update_counter = 0
                
                # Wait
                if self.running:
                    add_log(f"⏳ Waiting {check_interval} seconds...")
                    time.sleep(check_interval)
                
            except Exception as e:
                add_log(f"❌ Bot error: {str(e)}")
                logger.exception("Bot loop error details:")
                time.sleep(30)
        
        add_log("🛑 Bot stopped")

def run_bot_thread(config):
    """Background thread for bot"""
    global bot_instance, bot_running
    
    if not BETFAIR_AVAILABLE:
        add_log("⚠️ Running in DEMO MODE - No Betfair connection")
        while bot_running:
            add_log("💤 Demo mode: Waiting for Betfair modules...")
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
        logger.exception("Bot thread error details:")
        bot_running = False

# Flask Routes
@app.route('/')
def index():
    """Serve dashboard HTML"""
    return render_template('dashboard.html')

@app.route('/api/status')
def get_status():
    """Get current bot status"""
    config = load_config()
    
    # Sanitize session token for display
    display_token = ""
    if config.get('session_token'):
        token = config['session_token']
        if len(token) > 10:
            display_token = token[:10] + "..." + token[-4:]
        else:
            display_token = token[:4] + "..."
    
    # Sanitize app key
    display_app_key = ""
    if config.get('app_key'):
        key = config['app_key']
        if len(key) > 10:
            display_app_key = key[:10] + "..." + key[-4:]
        else:
            display_app_key = key[:4] + "..."
    
    with bot_lock:
        stats_copy = bot_stats.copy()
    
    return jsonify({
        "status": "running" if bot_running else "stopped",
        "balance": stats_copy.get('balance', 0.0),
        "currency": config.get('account', {}).get('currency', 'AUD'),
        "stats": stats_copy,
        "config": {
            **config.get('betting', {}),
            "session_token": display_token,
            "app_key": display_app_key
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
        config = load_config()
        
        # Validate credentials
        if not config.get('session_token'):
            return jsonify({"success": False, "message": "Session token is required"})
        
        if not config.get('app_key'):
            return jsonify({"success": False, "message": "App key is required"})
        
        add_log("🚀 Starting bot...")
        
        bot_running = True
        bot_thread = threading.Thread(target=run_bot_thread, args=(config,), daemon=True)
        bot_thread.start()
        
        return jsonify({"success": True, "message": "Bot started successfully"})
    except Exception as e:
        bot_running = False
        add_log(f"❌ Failed to start: {str(e)}")
        logger.exception("Start bot error details:")
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
        
        # Validate input
        if not new_config:
            return jsonify({"success": False, "message": "No configuration provided"})
        
        # Load existing config
        config = load_config()
        
        # Update session token
        if 'session_token' in new_config:
            token = new_config['session_token'].strip()
            if token:
                config['session_token'] = token
                add_log("🔑 Session token updated")
        
        # Update app key
        if 'app_key' in new_config:
            key = new_config['app_key'].strip()
            if key:
                config['app_key'] = key
                add_log("🔐 App key updated")
        
        # Update betting config
        if 'betting' not in config:
            config['betting'] = {}
        
        if 'min_odds' in new_config:
            config['betting']['min_odds'] = float(new_config['min_odds'])
            add_log(f"📊 Min odds set to {new_config['min_odds']}")
        
        if 'max_odds' in new_config:
            config['betting']['max_odds'] = float(new_config['max_odds'])
            add_log(f"📊 Max odds set to {new_config['max_odds']}")
        
        if 'stake' in new_config:
            config['betting']['stake'] = float(new_config['stake'])
            add_log(f"💵 Stake set to ${new_config['stake']}")
        
        # Save config
        if save_config(config):
            add_log("⚙️ Configuration saved successfully")
            
            # Warn if bot is running
            if bot_running:
                return jsonify({
                    "success": True, 
                    "message": "Configuration saved! Restart bot to apply changes."
                })
            else:
                return jsonify({
                    "success": True, 
                    "message": "Configuration saved successfully!"
                })
        else:
            return jsonify({
                "success": False, 
                "message": "Failed to save configuration"
            })
            
    except ValueError as e:
        error_msg = f"Invalid value: {str(e)}"
        add_log(f"❌ {error_msg}")
        return jsonify({"success": False, "message": error_msg})
    except Exception as e:
        error_msg = f"Config error: {str(e)}"
        add_log(f"❌ {error_msg}")
        logger.exception("Config update error details:")
        return jsonify({"success": False, "message": error_msg})

@app.route('/api/stats/reset', methods=['POST'])
def reset_stats():
    """Reset bot statistics"""
    global bot_stats
    
    try:
        with bot_lock:
            balance = bot_stats.get('balance', 0.0)  # Preserve balance
            bot_stats = {
                "total_bets": 0,
                "total_stake": 0,
                "total_exposure": 0,
                "successful_bets": 0,
                "failed_bets": 0,
                "last_bet_time": None,
                "balance": balance
            }
        
        add_log("🔄 Statistics reset")
        return jsonify({"success": True, "message": "Statistics reset successfully"})
    except Exception as e:
        return jsonify({"success": False, "message": str(e)})

@app.route('/api/logs/clear', methods=['POST'])
def clear_logs():
    """Clear all log entries"""
    global bot_logs
    
    try:
        bot_logs.clear()
        add_log("🗑️ Logs cleared by user")
        return jsonify({"success": True, "message": "Logs cleared successfully"})
    except Exception as e:
        return jsonify({"success": False, "message": str(e)})

if __name__ == '__main__':
    print("\n" + "="*70)
    print("🏇 BETFAIR BOT DASHBOARD - LIVE TRADING SYSTEM")
    print("="*70)
    print("Dashboard URL: http://localhost:5000")
    print("="*70)
    print("\n⚠️  WARNING: This bot places REAL bets with REAL money!")
    print("📋 Make sure your config.json has valid credentials")
    print("="*70)
    print("\n✅ Server starting...\n")
    
    app.run(debug=True, host='0.0.0.0', port=5000, use_reloader=False)