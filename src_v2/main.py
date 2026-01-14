import time
from datetime import datetime, timedelta
import pandas as pd
import numpy as np
from trading_functions import TradingFunctions
from data_ingestion import DataIngestion
from model import Classifier
from trading_utils import TradingPrice
from binance.client import Client
from env import demo_futures_api, demo_futures_secret, test_net

# Configuration
TOP_10_CRYPTOS = [
    "BTCUSDT",  # Bitcoin
    "ETHUSDT",  # Ethereum
    "BNBUSDT",  # Binance Coin
    "XRPUSDT",  # XRP
    "SOLUSDT",  # Solana
    "DOGEUSDT", # Dogecoin
    "ADAUSDT",  # Cardano
    "MATICUSDT",# Polygon (Note: Use POLUSDT if MATIC is deprecated, but mostly MATICUSDT exists)
    "DOTUSDT",  # Polkadot
    "AVAXUSDT"  # Avalanche
]

def get_next_candle_time():
    """Calculates the next 4H candle close time."""
    now = datetime.utcnow()
    # 4H candles close at 0, 4, 8, 12, 16, 20
    # We want the *next* boundary. 
    # If now is 04:00:00 -> Next is 08:00
    # If now is 03:59:59 -> Next is 04:00
    
    next_hour = ((now.hour // 4) + 1) * 4
    if next_hour >= 24:
        target = now.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=1)
    else:
        target = now.replace(hour=next_hour, minute=0, second=0, microsecond=0)
    return target

def wait_for_next_candle():
    """Sleeps until the next 4H candle close (with buffer)."""
    target = get_next_candle_time()
    now = datetime.utcnow()
    
    sleep_seconds = (target - now).total_seconds()
    
    # Add buffer (e.g., 2 mins) to ensure Binance has finalized the candle
    buffer_seconds = 120 
    total_sleep = sleep_seconds + buffer_seconds
    
    if total_sleep < 0:
        # Should rarely happen with the logic above, but safety first
        total_sleep = 0
        
    print(f"Next 4H candle closes at {target} UTC. Sleeping for {total_sleep/60:.2f} minutes.")
    time.sleep(total_sleep)

def is_within_trading_window(minutes_tolerance=15):
    """
    Checks if the current time is within 'minutes_tolerance' AFTER a 4H candle close.
    Example: If tolerance is 15, valid times are 00:00-00:15, 04:00-04:15, etc.
    This prevents the bot from executing 'stale' trades if started in the middle of a session.
    """
    now = datetime.utcnow()
    # Check if we are in the first X minutes of a 4-hour block
    if now.hour % 4 == 0 and now.minute < minutes_tolerance:
        return True
    return False

def get_total_usdt_capital(trading):
    """Calculates total available USDT equity."""
    try:
        balance_info = trading.get_balance()
        for asset in balance_info:
            if asset['asset'] == 'USDT':
                # Use balance + crossUnPnl for approximate equity
                # Note: 'balance' is wallet balance. 'crossUnPnl' is unrealized PnL.
                return float(asset['balance'])
    except Exception as e:
        print(f"Error fetching balance: {e}")
    return 1000.0 # Fallback default

def main():
    print("Starting CryptoV2 Bot with Portfolio Trading...")
    
    # Initialize components
    client = Client(demo_futures_api, demo_futures_secret, testnet=test_net)
    trading = TradingFunctions(client)
    data_ingestion = DataIngestion()
    model = Classifier()
    trading_price = TradingPrice()

    while True:
        try:
            print(f"\n--- Analysis cycle check at {datetime.utcnow()} ---")
            
            # Check if we are inside the valid execution window
            if not is_within_trading_window(minutes_tolerance=30):
                print("Outside of 30-minute post-close trading window. Skipping trade execution to prevent stale signals.")
                wait_for_next_candle()
                continue # Restart loop, which triggers valid timestamps check
            
            # Phase 1: Data Gathering & Prediction
            analysis_results = {}
            total_inverse_volilaty = 0
            
            print("Analyzing portfolio...")
            # Double check time again to ensure 'is_within' didn't pass us at minute 29 and we take 5 mins to run
            # but that's fine, as long as we STARTED freshness check.
            
            current_capital = get_total_usdt_capital(trading)
            print(f"Total USDT Capital: {current_capital}")

            # Safe usage fraction (e.g. use 90% of capital across all trades to leave buffer)
            deployable_capital = current_capital * 0.90 

            for symbol in TOP_10_CRYPTOS:
                try:
                    # 1. Get Data
                    df = data_ingestion.get_data(symbol)
                    if df.empty: 
                        print(f"Skipping {symbol}: No data found")
                        continue

                    # 2. Engineer Features
                    df_features = data_ingestion.__engineer_features__(df)
                    
                    if df_features.empty:
                        print(f"Skipping {symbol}: Feature engineering returned empty")
                        continue

                    # 3. Predict
                    probs = model.predict(df_features)
                    
                    # 4. Edge & Decision
                    edge = trading_price.calculate_edge(probs)
                    side, leverage, desc = trading_price.get_trade_decision(edge)

                    # 5. Volatility for Weighting
                    # Use the last calculated volatility. 
                    # If df_features has 'vol_20', we use that.
                    # It matches the prediction row.
                    volatility = df_features.iloc[-1]['vol_20']
                    
                    # Capture ATR for strategic orders
                    atr = df_features.iloc[-1]['atr_14']
                    
                    # Store results
                    analysis_results[symbol] = {
                        'side': side,
                        'leverage': leverage,
                        'desc': desc,
                        'volatility': volatility,
                        'edge': edge,
                        'atr': atr
                    }
                    
                    # Accumulate inverse volatility (Handle 0 vol case)
                    if volatility > 0:
                        total_inverse_volilaty += (1.0 / volatility)
                    
                    print(f"{symbol}: {side} ({desc}) | Edge: {edge:.4f} | Vol: {volatility:.4f}")

                except Exception as e:
                    print(f"Error analyzing {symbol}: {e}")
                    continue
            
            # Phase 2: Weighting & Execution
            if total_inverse_volilaty == 0:
                print("Total inverse volatility is 0, falling back to Equal Weighting")
                # Avoid division by zero
                total_inverse_volilaty = 1 # Dummy value, logic handled in loop
            
            print("\nExecuting Trades...")
            for symbol, result in analysis_results.items():
                try:
                    side = result['side']
                    leverage = result['leverage']
                    volatility = result['volatility']

                    # Weighting Algorithm: Inverse Volatility
                    if total_inverse_volilaty > 1 and volatility > 0:
                        weight = (1.0 / volatility) / total_inverse_volilaty
                    else:
                        weight = 1.0 / len(analysis_results) # Fallback Equal Weight

                    position_size_usdt = deployable_capital * weight
                    
                    # Min trade size check (Binance min is usually 5-10 USDT)
                    if position_size_usdt < 6: 
                        position_size_usdt = 6

                    print(f"--> {symbol}: Weight {weight:.2%} -> Size ${position_size_usdt:.2f}")

                    current_position = trading.get_current_position(symbol)
                    
                    if side == "NEUTRAL":
                        if current_position != 0:
                            print(f"    Closing {symbol} (NEUTRAL)")
                            trading.close_position(symbol)
                        else:
                            print(f"    {symbol} Flat.")
                    else:
                        # Re-balancing logic:
                        # Close existing if direction is wrong OR if size difference is substantial?
                        # For simplicity/robustness: Close & Re-open to match exact size/leverage
                        if current_position != 0:
                            print(f"    Closing existing {symbol} to re-balance/re-enter.")
                            trading.close_position(symbol)
                        
                        print(f"    Opening {side} {symbol}...")
                        # Get ATR from df_features for this symbol
                        # Note: We calculated df_features earlier but stored it inside the loop. 
                        # We need to retrieve it or store it in analyis_results.
                        # We stored 'volatility' (which is std dev), but not ATR.
                        # Let's fix gathering block above to store ATR.
                        atr = result.get('atr', 0)
                        
                        trading.place_strategic_order(
                            symbol=symbol,
                            side=side,
                            amount=position_size_usdt,
                            leverage=leverage,
                            atr=atr
                        )

                except Exception as e:
                    print(f"Error executing trade for {symbol}: {e}")

            print("Cycle complete.")
            wait_for_next_candle()
            
        except Exception as e:
            print(f"CRITICAL ERROR in main loop: {e}")
            print("Sleeping for 1 minute before retrying...")
            time.sleep(60)

if __name__ == "__main__":
    main()
