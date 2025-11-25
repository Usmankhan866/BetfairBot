"""
Complete Betfair Bot Dashboard with Live Betting Integration
"""

from flask import Flask, render_template, jsonify, request
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
    return render_template('dashboard.html')

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

if __name__ == '__main__':
    print("\n" + "="*60)
    print("🏇 BETFAIR BOT DASHBOARD")
    print("="*60)
    print("Dashboard URL: http://localhost:5000")
    print("="*60)
    print("\n✅ Server starting...\n")
    
    app.run(debug=True, host='0.0.0.0', port=5000)
