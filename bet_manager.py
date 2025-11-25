"""
Bet Manager Module - Manages betting decisions and risk
"""

import logging
from datetime import datetime

class BetManager:
    """Manages bets and tracks exposure"""
    
    def __init__(self, stake, per_race_stop_loss):
        """
        Initialize bet manager
        
        Args:
            stake (float): Fixed stake per bet
            per_race_stop_loss (float): Maximum loss per race
        """
        self.stake = stake
        self.per_race_stop_loss = per_race_stop_loss
        self.race_exposure = {}  # Track exposure per race
        self.placed_bets = []  # History of all bets
        self.logger = logging.getLogger(__name__)
    
    def can_bet_on_race(self, market_id):
        """
        Check if we can still bet on this race (within stop loss)
        
        Args:
            market_id (str): Market ID
            
        Returns:
            bool: True if we can bet, False if stop loss reached
        """
        current_exposure = self.race_exposure.get(market_id, 0)
        
        if current_exposure >= self.per_race_stop_loss:
            self.logger.warning(f"Stop loss reached for race {market_id}: ${current_exposure}")
            return False
        
        return True
    
    def record_bet(self, market_id, runner_name, selection_id, stake, price, bet_result):
        """
        Record a placed bet
        
        Args:
            market_id (str): Market ID
            runner_name (str): Horse name
            selection_id (int): Selection ID
            stake (float): Stake amount
            price (float): Odds
            bet_result (dict): Result from bet placement
        """
        bet_record = {
            'timestamp': datetime.now(),
            'market_id': market_id,
            'runner_name': runner_name,
            'selection_id': selection_id,
            'stake': stake,
            'price': price,
            'bet_id': bet_result.get('bet_id', 'N/A'),
            'success': bet_result.get('success', False),
            'error': bet_result.get('error', None)
        }
        
        self.placed_bets.append(bet_record)
        
        # Update race exposure
        if bet_result.get('success'):
            if market_id not in self.race_exposure:
                self.race_exposure[market_id] = 0
            self.race_exposure[market_id] += stake
        
        self.logger.info(f"Bet recorded: {runner_name} @ {price} - {'SUCCESS' if bet_result.get('success') else 'FAILED'}")
    
    def get_race_exposure(self, market_id):
        """Get current exposure for a race"""
        return self.race_exposure.get(market_id, 0)
    
    def get_total_exposure(self):
        """Get total exposure across all races"""
        return sum(self.race_exposure.values())
    
    def get_bet_count(self):
        """Get total number of bets placed"""
        return len([b for b in self.placed_bets if b['success']])
    
    def get_betting_summary(self):
        """Get summary of betting activity"""
        successful_bets = [b for b in self.placed_bets if b['success']]
        failed_bets = [b for b in self.placed_bets if not b['success']]
        
        total_staked = sum(b['stake'] for b in successful_bets)
        
        return {
            'total_bets': len(successful_bets),
            'failed_bets': len(failed_bets),
            'total_staked': total_staked,
            'races_bet_on': len(self.race_exposure),
            'total_exposure': self.get_total_exposure()
        }
    
    def print_summary(self):
        """Print betting summary to console"""
        summary = self.get_betting_summary()
        
        print("\n" + "=" * 50)
        print("BETTING SUMMARY")
        print("=" * 50)
        print(f"Total Successful Bets: {summary['total_bets']}")
        print(f"Failed Bet Attempts: {summary['failed_bets']}")
        print(f"Total Staked: ${summary['total_staked']:.2f}")
        print(f"Races Bet On: {summary['races_bet_on']}")
        print(f"Total Exposure: ${summary['total_exposure']:.2f}")
        print("=" * 50 + "\n")
    
    def print_recent_bets(self, count=5):
        """Print recent bets"""
        recent = self.placed_bets[-count:]
        
        if not recent:
            print("No bets placed yet.\n")
            return
        
        print("\n" + "=" * 50)
        print(f"LAST {len(recent)} BETS")
        print("=" * 50)
        
        for bet in recent:
            status = "✓" if bet['success'] else "✗"
            print(f"{status} {bet['timestamp'].strftime('%H:%M:%S')} - {bet['runner_name']} @ {bet['price']} (${bet['stake']})")
            if not bet['success']:
                print(f"   Error: {bet['error']}")
        
        print("=" * 50 + "\n")