"""
Betfair Client Module - Handles all communication with Betfair API
"""

import betfairlightweight
from betfairlightweight import filters
from datetime import datetime, timedelta, timezone
import logging

class BetfairClient:
    """Handles Betfair API interactions"""
    
    def __init__(self, app_key, session_token):
        """
        Initialize Betfair client with session token
        
        Args:
            app_key (str): Betfair application key
            session_token (str): Pre-generated session token
        """
        self.app_key = app_key
        self.session_token = session_token
        self.api = None
        self.logger = logging.getLogger(__name__)
        
    def connect(self):
        """Connect to Betfair using session token"""
        try:
            # Create trading instance
            self.api = betfairlightweight.APIClient(
                username='',  # Not needed with session token
                password='',  # Not needed with session token
                app_key=self.app_key
            )
            
            # Set the session token manually
            self.api.session_token = self.session_token
            
            # Test the connection by getting account details
            try:
                account_details = self.api.account.get_account_details()
                self.logger.info(f"[OK] Connected successfully! Account: {account_details.currency_code}")
                return True
            except Exception as e:
                self.logger.error(f"[FAIL] Session token invalid or expired: {str(e)}")
                self.logger.error("Please generate a new session token and update config.json")
                return False
            
        except Exception as e:
            self.logger.error(f"[FAIL] Failed to connect: {str(e)}")
            return False
    
    def get_australian_thoroughbred_races(self, hours_ahead=24):
        """
        Get upcoming Australian thoroughbred races
        
        Args:
            hours_ahead (int): How many hours ahead to look
            
        Returns:
            list: Market catalogues for qualifying races
        """
        try:
            # Time range for races
            time_from = datetime.now(timezone.utc)
            time_to = time_from + timedelta(hours=hours_ahead)
            
            # Create filter for Australian thoroughbred races
            market_filter = filters.market_filter(
                event_type_ids=['7'],  # Horse Racing
                market_countries=['AU'],  # Australia
                market_type_codes=['WIN'],  # Win market
                market_start_time={
                    'from': time_from.strftime('%Y-%m-%dT%H:%M:%SZ'),
                    'to': time_to.strftime('%Y-%m-%dT%H:%M:%SZ')
                }
            )
            
            # Get market catalogues
            market_catalogues = self.api.betting.list_market_catalogue(
                filter=market_filter,
                max_results=100,
                market_projection=[
                    'RUNNER_DESCRIPTION',
                    'EVENT',
                    'MARKET_START_TIME',
                    'RUNNER_METADATA'
                ]
            )
            
            self.logger.info(f"[OK] Found {len(market_catalogues)} Australian races")
            return market_catalogues
            
        except Exception as e:
            self.logger.error(f"[FAIL] Error getting races: {str(e)}")
            return []
    
    def get_market_prices(self, market_id):
        """
        Get current prices for a market
        
        Args:
            market_id (str): Betfair market ID
            
        Returns:
            dict: Market prices or None
        """
        try:
            price_filter = filters.price_projection(
                price_data=['EX_BEST_OFFERS']
            )
            
            market_books = self.api.betting.list_market_book(
                market_ids=[market_id],
                price_projection=price_filter
            )
            
            if market_books and len(market_books) > 0:
                return market_books[0]
            
            return None
            
        except Exception as e:
            self.logger.error(f"[FAIL] Error getting prices for {market_id}: {str(e)}")
            return None
    
    def get_win_lay_price(self, runner):
        """
        Extract win lay price from runner data
        
        Args:
            runner: Runner object from market book
            
        Returns:
            float or None: Best lay price
        """
        try:
            if hasattr(runner, 'ex') and runner.ex.available_to_lay:
                best_lay = runner.ex.available_to_lay[0]
                return best_lay.price
            return None
        except:
            return None
    
    def get_place_back_price(self, runner):
        """
        Extract place back price from runner data
        
        Args:
            runner: Runner object from place market book
            
        Returns:
            float or None: Best back price
        """
        try:
            if hasattr(runner, 'ex') and runner.ex.available_to_back:
                best_back = runner.ex.available_to_back[0]
                return best_back.price
            return None
        except:
            return None
    
    def get_place_market_id(self, win_market_id):
        """
        Find the corresponding place market for a win market
        
        Args:
            win_market_id (str): Win market ID
            
        Returns:
            str or None: Place market ID
        """
        try:
            # Get the event ID from win market
            win_market = self.api.betting.list_market_catalogue(
                filter=filters.market_filter(market_ids=[win_market_id]),
                max_results=1,
                market_projection=['EVENT']
            )[0]
            
            event_id = win_market.event.id
            
            # Find place market for same event
            place_filter = filters.market_filter(
                event_ids=[event_id],
                market_type_codes=['PLACE']
            )
            
            place_markets = self.api.betting.list_market_catalogue(
                filter=place_filter,
                max_results=1
            )
            
            if place_markets:
                return place_markets[0].market_id
            
            return None
            
        except Exception as e:
            self.logger.error(f"[FAIL] Error finding place market: {str(e)}")
            return None
    
    def place_bet(self, market_id, selection_id, stake, price):
        """
        Place a back bet on Betfair
        
        Args:
            market_id (str): Market ID
            selection_id (int): Runner selection ID
            stake (float): Stake amount
            price (float): Odds to back at
            
        Returns:
            dict: Bet placement result
        """
        try:
            instruction = filters.place_instruction(
                order_type='LIMIT',
                selection_id=selection_id,
                side='BACK',
                limit_order=filters.limit_order(
                    size=stake,
                    price=price,
                    persistence_type='LAPSE'
                )
            )
            
            place_orders = self.api.betting.place_orders(
                market_id=market_id,
                instructions=[instruction]
            )
            
            if place_orders.status == 'SUCCESS':
                self.logger.info(f"[SUCCESS] Bet placed: ${stake} at {price}")
                return {
                    'success': True,
                    'bet_id': place_orders.instruction_reports[0].bet_id,
                    'placed_date': place_orders.instruction_reports[0].placed_date,
                    'size': place_orders.instruction_reports[0].size_matched,
                    'price': place_orders.instruction_reports[0].average_price_matched
                }
            else:
                self.logger.error(f"[FAIL] Bet placement failed: {place_orders.error_code}")
                return {
                    'success': False,
                    'error': place_orders.error_code
                }
                
        except Exception as e:
            self.logger.error(f"[FAIL] Error placing bet: {str(e)}")
            return {
                'success': False,
                'error': str(e)
            }
    
    def get_account_balance(self):
        """Get current account balance"""
        try:
            funds = self.api.account.get_account_funds()
            return funds.available_to_bet_balance
        except Exception as e:
            self.logger.error(f"[FAIL] Error getting balance: {str(e)}")
            return None