"""
Flask Backend Server for Betfair Bot Dashboard
Connects the React frontend with the Python betting bot
"""

from flask import Flask, jsonify, request, send_from_directory
from flask_cors import CORS
import json
import threading
import time
from datetime import datetime
import os

# Import your bot modules
from betfair_client import BetfairClient
from calculator import BettingCalculator
from bet_manager import BetManager

app = Flask(__name__, static_folder='build', static_url_path='')
CORS(app)

# Global bot state
bot_state = {
    'status': 'stopped',
    'balance': 0,
    'stats': {
        'totalBets': 0,
        'successfulBets': 0,
        'totalStaked': 0,
        'totalExposure': 0
    },
    'recent_bets': [],
    'logs': [],
    'current_races': [],
    'config': {
        'app_key': '',
        'session_token': '',
        'stake': 10,
        'per_race_stop_loss': 50,
        'min_runners': 8,
        'max_runners': 14,
        'check_interval_seconds': 30,
        'bet_timing_minutes_before_start': 10
    }
}

# Bot instance
bot_thread = None
bot_running = False
client = None
calculator = None
bet_manager = None
processed_races = set()


def add_log(log_type, message):
    """Add log entry"""
    log_entry = {
        'time': datetime.now().strftime('%H:%M:%S'),
        'type': log_type,
        'message': message
    }
    bot_state['logs'].insert(0, log_entry)
    bot_state['logs'] = bot_state['logs'][:100]  # Keep last 100 logs


def load_config():
    """Load configuration from file"""
    try:
        with open('config.json', 'r') as f:
            config = json.load(f)
            bot_state['config'].update(config)
            add_log('info', 'Configuration loaded')
            return True
    except Exception as e:
        add_log('error', f'Failed to load config: {str(e)}')
        return False


def save_config():
    """Save configuration to file"""
    try:
        with open('config.json', 'w') as f:
            json.dump(bot_state['config'], f, indent=4)
        add_log('success', 'Configuration saved')
        return True
    except Exception as e:
        add_log('error', f'Failed to save config: {str(e)}')
        return False


def bot_loop():
    """Main bot loop running in separate thread"""
    global bot_running, client, calculator, bet_manager, processed_races
    
    add_log('info', 'Initializing bot...')
    
    # Initialize components
    try:
        client = BetfairClient(
            app_key=bot_state['config']['app_key'],
            session_token=bot_state['config']['session_token']
        )
        
        if not client.connect():
            add_log('error', 'Failed to connect to Betfair')
            bot_state['status'] = 'error'
            bot_running = False
            return
        
        add_log('success', 'Connected to Betfair')
        
        # Get balance
        balance = client.get_account_balance()
        if balance:
            bot_state['balance'] = balance
            add_log('info', f'Account balance: ${balance:.2f}')
        
        calculator = BettingCalculator()
        bet_manager = BetManager(
            stake=bot_state['config']['stake'],
            per_race_stop_loss=bot_state['config']['per_race_stop_loss']
        )
        
        add_log('success', 'Bot started successfully')
        
    except Exception as e:
        add_log('error', f'Initialization error: {str(e)}')
        bot_state['status'] = 'error'
        bot_running = False
        return
    
    # Main loop
    while bot_running:
        try:
            add_log('info', 'Checking for races...')
            
            # Get races
            races = client.get_australian_thoroughbred_races(hours_ahead=2)
            bot_state['current_races'] = [{
                'id': race.market_id,
                'name': race.event.name,
                'runners': len(race.runners),
                'start_time': race.market_start_time.strftime('%H:%M')
            } for race in races]
            
            add_log('info', f'Found {len(races)} Australian races')
            
            # Process each race (simplified for dashboard)
            for race in races:
                if not bot_running:
                    break
                
                # Process race logic here (similar to your main.py)
                # For brevity, this is simplified
                
            # Update stats from bet_manager
            summary = bet_manager.get_betting_summary()
            bot_state['stats'] = {
                'totalBets': summary['total_bets'],
                'successfulBets': summary['total_bets'],
                'totalStaked': summary['total_staked'],
                'totalExposure': summary['total_exposure']
            }
            
            # Wait before next check
            time.sleep(bot_state['config']['check_interval_seconds'])
            
        except Exception as e:
            add_log('error', f'Bot error: {str(e)}')
            time.sleep(10)
    
    add_log('warning', 'Bot stopped')
    bot_state['status'] = 'stopped'


# API Routes

@app.route('/')
def serve_frontend():
    """Serve React frontend"""
    return send_from_directory(app.static_folder, 'index.html')


@app.route('/api/status')
def get_status():
    """Get current bot status"""
    return jsonify(bot_state)


@app.route('/api/start', methods=['POST'])
def start_bot():
    """Start the bot"""
    global bot_thread, bot_running
    
    if bot_running:
        return jsonify({'success': False, 'message': 'Bot already running'})
    
    load_config()
    
    bot_running = True
    bot_state['status'] = 'running'
    bot_thread = threading.Thread(target=bot_loop)
    bot_thread.start()
    
    add_log('success', 'Bot started')
    return jsonify({'success': True, 'message': 'Bot started successfully'})


@app.route('/api/stop', methods=['POST'])
def stop_bot():
    """Stop the bot"""
    global bot_running
    
    if not bot_running:
        return jsonify({'success': False, 'message': 'Bot not running'})
    
    bot_running = False
    add_log('warning', 'Stopping bot...')
    
    return jsonify({'success': True, 'message': 'Bot stopped'})


@app.route('/api/config', methods=['GET', 'POST'])
def handle_config():
    """Get or update configuration"""
    if request.method == 'GET':
        return jsonify(bot_state['config'])
    
    elif request.method == 'POST':
        data = request.json
        bot_state['config'].update(data)
        save_config()
        return jsonify({'success': True, 'message': 'Configuration updated'})


@app.route('/api/balance')
def get_balance():
    """Get current account balance"""
    if client:
        try:
            balance = client.get_account_balance()
            if balance:
                bot_state['balance'] = balance
                return jsonify({'success': True, 'balance': balance})
        except:
            pass
    
    return jsonify({'success': False, 'balance': bot_state['balance']})


@app.route('/api/logs')
def get_logs():
    """Get recent logs"""
    return jsonify(bot_state['logs'])


@app.route('/api/bets')
def get_bets():
    """Get recent bets"""
    return jsonify(bot_state['recent_bets'])


@app.route('/api/races')
def get_races():
    """Get current races"""
    return jsonify(bot_state['current_races'])


if __name__ == '__main__':
    load_config()
    add_log('info', 'Server starting...')
    print("\n" + "="*60)
    print("Betfair Bot Dashboard Server")
    print("="*60)
    print("Dashboard URL: http://localhost:5000")
    print("API URL: http://localhost:5000/api/status")
    print("="*60 + "\n")
    
    app.run(debug=True, host='0.0.0.0', port=5000)