"""
Calculator Module - Implements Patrick's Place Betting Formula
"""

class BettingCalculator:
    """Calculates fair place odds and minimum required odds"""
    
    def __init__(self):
        # Divisor rules based on field size
        self.divisor_rules = {
            8: 5,
            9: 4, 10: 4, 11: 4, 12: 4, 13: 4, 14: 4
        }
        self.safety_margin = 1.10  # 10% buffer for commission
    
    def get_divisor(self, num_runners):
        """Get divisor based on number of runners"""
        return self.divisor_rules.get(num_runners)
    
    def calculate_fair_place_odds(self, win_lay_price, num_runners):
        """
        Calculate fair place odds from win lay price
        
        Formula: Place_fair = ((Win_Lay - 1) / Divisor) + 1
        
        Args:
            win_lay_price (float): Win market lay price
            num_runners (int): Number of runners in race
            
        Returns:
            float or None: Fair place odds, or None if race doesn't qualify
        """
        divisor = self.get_divisor(num_runners)
        
        if divisor is None:
            return None
        
        # Step 1: Calculate fair place price
        place_fair = ((win_lay_price - 1) / divisor) + 1
        
        return place_fair
    
    def calculate_minimum_place_odds(self, place_fair):
        """
        Add 10% safety margin to fair odds
        
        Formula: Place_min = 1 + (1.10 × (Place_fair - 1))
        
        Args:
            place_fair (float): Fair place odds
            
        Returns:
            float: Minimum required place odds
        """
        profit_part = place_fair - 1
        buffered_profit = profit_part * self.safety_margin
        place_min = 1 + buffered_profit
        
        return place_min
    
    def should_bet(self, win_lay_price, actual_place_price, num_runners):
        """
        Determine if we should place a bet
        
        Args:
            win_lay_price (float): Win market lay price
            actual_place_price (float): Current best back price in place market
            num_runners (int): Number of runners in race
            
        Returns:
            tuple: (should_bet: bool, details: dict)
        """
        # Calculate fair odds
        place_fair = self.calculate_fair_place_odds(win_lay_price, num_runners)
        
        if place_fair is None:
            return False, {
                'error': f'Race with {num_runners} runners does not qualify',
                'num_runners': num_runners
            }
        
        # Calculate minimum required odds
        place_min = self.calculate_minimum_place_odds(place_fair)
        
        # Decision
        should_place_bet = actual_place_price >= place_min
        
        details = {
            'win_lay_price': win_lay_price,
            'num_runners': num_runners,
            'divisor': self.get_divisor(num_runners),
            'place_fair': round(place_fair, 2),
            'place_min': round(place_min, 2),
            'actual_place_price': actual_place_price,
            'should_bet': should_place_bet,
            'edge': round(actual_place_price - place_min, 2) if should_place_bet else 0
        }
        
        return should_place_bet, details


# Test the calculator with Patrick's example
if __name__ == "__main__":
    calc = BettingCalculator()
    
    print("Testing with Patrick's Example:")
    print("=" * 50)
    print("Race: 10 runners")
    print("Win Lay Price: 3.0")
    print("Actual Place Back Price: 1.62")
    print()
    
    should_bet, details = calc.should_bet(
        win_lay_price=3.0,
        actual_place_price=1.62,
        num_runners=10
    )
    
    print(f"Divisor: {details['divisor']}")
    print(f"Fair Place Price: {details['place_fair']}")
    print(f"Minimum Required (with 10% buffer): {details['place_min']}")
    print(f"Actual Place Price Available: {details['actual_place_price']}")
    print(f"Should Bet: {details['should_bet']}")
    if should_bet:
        print(f"Edge: {details['edge']} (actual is {details['edge']} better than required)")